"""Multi-host federation: separate store servers, real HTTP, injected latency, an outage.

Each store runs as its own `memory-fabric federate` server process, with its
own database, and the stores talk to each other only over HTTP, through a
TCP proxy that adds latency to every hop. A driver then:

1. shares a memory A -> B -> C with signed network offers (`offer_remote`),
   each validated at the recipient;
2. corrects it at A and measures how long until C's copy is withdrawn,
   carried by the servers' own background managers (A to B, then B to C);
3. repeats with C's server stopped during the correction, restarts it, and
   measures convergence after it returns.

    python -m experiments.multihost                     # 3 stores, 50 ms per hop
    python -m experiments.multihost --latency-ms 200

`--mode compose` drives stores already running in separate containers
(`deploy/multihost/docker-compose.yml`, CI job `multihost`): separate network
stacks, still one physical machine. Neither mode is several physical
machines, and the result says which ran.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research" / "results" / "multihost.json"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class LatencyProxy:
    """Forwards TCP to a target, sleeping `delay_s` before each chunk in each direction."""

    def __init__(self, target_port: int, delay_s: float) -> None:
        self.target_port, self.delay_s = target_port, delay_s
        self.blocked = False
        """A partition: while set, new connections are refused and traffic is dropped."""
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(32)
        self.port = int(self.sock.getsockname()[1])
        threading.Thread(target=self._accept, daemon=True).start()

    def _pipe(self, src: socket.socket, dst: socket.socket) -> None:
        try:
            while True:
                data = src.recv(65536)
                if not data or self.blocked:
                    break
                time.sleep(self.delay_s)
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _accept(self) -> None:
        while True:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            if self.blocked:
                client.close()
                continue
            try:
                upstream = socket.create_connection(("127.0.0.1", self.target_port), timeout=5)
            except OSError:
                client.close()
                continue
            for a, b in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pipe, args=(a, b), daemon=True).start()


def wait_health(url: str, timeout_s: float = 30) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/federation/health", timeout=2):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"{url} did not come up")


class Topology:
    def __init__(self, names: list[str], latency_ms: float, workdir: Path) -> None:
        from memory_fabric import MemoryFabric

        self.names, self.dir = names, workdir
        self.db = {n: workdir / f"{n}.db" for n in names}
        self.store_id = {}
        for n in names:
            f = MemoryFabric(str(self.db[n]))
            self.store_id[n] = f.store_id
            f.close()
        self.port = {n: free_port() for n in names}
        self.key = {frozenset((a, b)): secrets.token_bytes(32) for a in names for b in names
                    if a < b}
        self.proxy: dict[tuple[str, str], LatencyProxy] = {}
        for a in names:
            for b in names:
                if a != b:
                    self.proxy[(a, b)] = LatencyProxy(self.port[b], latency_ms / 1000)
        self.procs: dict[str, subprocess.Popen] = {}

    def peers_file(self, me: str) -> Path:
        rows = [{"store_id": self.store_id[o], "key_id": "k1",
                 "key_hex": self.key[frozenset((me, o))].hex(),
                 "endpoint": f"http://127.0.0.1:{self.proxy[(me, o)].port}"}
                for o in self.names if o != me]
        path = self.dir / f"{me}.peers.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        return path

    def start(self, n: str) -> None:
        # stderr to a file, never a pipe nobody reads: a full pipe blocks the
        # server, and macOS's small pipe buffer did exactly that in CI.
        log = open(self.dir / f"{n}.log", "ab")
        self.procs[n] = subprocess.Popen(
            [sys.executable, "-m", "memory_fabric", "--db", str(self.db[n]),
             "--share-policy", "reviewed", "federate", "--peers", str(self.peers_file(n)),
             "--port", str(self.port[n]), "--maintain-interval", "1"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=log)
        log.close()
        try:
            wait_health(f"http://127.0.0.1:{self.port[n]}", timeout_s=60)
        except RuntimeError:
            print((self.dir / f"{n}.log").read_text(errors="replace")[-3000:], file=sys.stderr)
            raise

    def stop(self, n: str) -> None:
        proc = self.procs.pop(n, None)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stop_all(self) -> None:
        for n in list(self.procs):
            self.stop(n)

    def transport(self, me: str) -> Any:
        from memory_fabric.manager import load_peers
        from memory_fabric.transport import HttpTransport

        return HttpTransport(load_peers(self.peers_file(me)), self.store_id[me])


FED_PORT = 8767


def prepare_compose(names: list[str], workdir: Path) -> None:
    """Stores and peers files for containers that reach each other as http://<name>:8767."""
    from memory_fabric import MemoryFabric

    workdir.mkdir(parents=True, exist_ok=True)
    keys = {frozenset((a, b)): secrets.token_bytes(32).hex() for a in names for b in names
            if a < b}
    ids = {}
    for n in names:
        f = MemoryFabric(str(workdir / f"{n}.db"))
        ids[n] = f.store_id
        f.close()
    for me in names:
        rows = [{"store_id": ids[o], "key_id": "k1", "key_hex": keys[frozenset((me, o))],
                 "endpoint": f"http://{o}:{FED_PORT}"} for o in names if o != me]
        (workdir / f"{me}.peers.json").write_text(json.dumps(rows), encoding="utf-8")
    (workdir / "topology.json").write_text(json.dumps({"names": names, "store_id": ids}),
                                           encoding="utf-8")


class ComposeTopology:
    """Stores already running in separate containers (deploy/multihost/docker-compose.yml).

    The servers talk to each other over the Docker network by service name.
    This driver, on the host, opens each store's file through the shared
    work directory and reaches each server on its published port
    (18767 + index), so its own offers do not cross the container network,
    while every retraction between stores does.
    """

    def __init__(self, workdir: Path, compose_file: Path) -> None:
        topo = json.loads((workdir / "topology.json").read_text(encoding="utf-8"))
        self.names, self.store_id, self.dir = topo["names"], topo["store_id"], workdir
        self.db = {n: workdir / f"{n}.db" for n in self.names}
        self.compose = ["docker", "compose", "-f", str(compose_file)]
        self.host_port = {n: 18767 + i for i, n in enumerate(self.names)}

    def peers_file(self, me: str) -> Path:
        return self.dir / f"{me}.peers.json"

    def start(self, n: str) -> None:
        subprocess.run([*self.compose, "start", n], check=True)
        wait_health(f"http://127.0.0.1:{self.host_port[n]}", timeout_s=60)

    def stop(self, n: str) -> None:
        subprocess.run([*self.compose, "stop", n], check=True)

    def stop_all(self) -> None:
        pass  # the compose file owns the containers

    def transport(self, me: str) -> Any:
        from memory_fabric.manager import load_peers
        from memory_fabric.transport import HttpTransport, Peer, PeerRegistry

        registry = PeerRegistry()
        for name, sid in self.store_id.items():
            peer = load_peers(self.peers_file(me)).get(sid)
            if peer is not None:
                registry.add(Peer(sid, f"http://127.0.0.1:{self.host_port[name]}", peer.key,
                                  peer.key_id))
        return HttpTransport(registry, self.store_id[me])


def open_store(path: Path) -> Any:
    from memory_fabric import MemoryFabric
    from memory_fabric.governance.firewall import SHARE_POLICIES, Firewall

    return MemoryFabric(str(path), firewall=Firewall(rules=SHARE_POLICIES["reviewed"]))


def share_chain(topo: Topology, text: str) -> dict[str, str]:
    """A -> B -> C by signed network offers; each import validated at its recipient."""
    from memory_fabric.federation import offer_remote

    ids: dict[str, str] = {}
    names = topo.names
    a = open_store(topo.db[names[0]])
    ids[names[0]] = a.remember("tech", text, scope="team")
    a.validate(ids[names[0]], actor="lead")
    a.close()
    for sender, recipient in zip(names, names[1:]):
        src = open_store(topo.db[sender])
        result = offer_remote(src, ids[sender], topo.transport(sender),
                              topo.store_id[recipient], recipient_agent="op")
        src.close()
        if not result.accepted:
            raise RuntimeError(f"{sender} -> {recipient} refused: {result.reasons}")
        dst = open_store(topo.db[recipient])
        dst.validate(result.imported_memory_id, actor="reviewer")
        dst.close()
        ids[recipient] = result.imported_memory_id
    return ids


def state_of(topo: Topology, name: str, memory_id: str) -> str:
    f = open_store(topo.db[name])
    try:
        return f.get(memory_id).lifecycle_state.value
    finally:
        f.close()


def correct_and_wait(topo: Topology, ids: dict[str, str], timeout_s: float) -> float | None:
    from memory_fabric import correction

    a = open_store(topo.db[topo.names[0]])
    t0 = time.perf_counter()
    correction.apply(a, ids[topo.names[0]], reason="re-measured", actor="lead")
    a.close()
    last = topo.names[-1]
    while time.perf_counter() - t0 < timeout_s:
        if state_of(topo, last, ids[last]) != "active":
            return time.perf_counter() - t0
        time.sleep(0.25)
    return None


def scenario(topo: Any) -> dict[str, Any]:
    """Share, correct, measure; then correct with the last store down, restart, measure."""
    from memory_fabric import correction

    names = topo.names
    t0 = time.perf_counter()
    ids = share_chain(topo, "Line 3 conveyor belt speed is 40 m/min.")
    share_s = time.perf_counter() - t0
    converge_s = correct_and_wait(topo, ids, timeout_s=60)
    states = {n: state_of(topo, n, ids[n]) for n in names}

    ids2 = share_chain(topo, "Line 4 conveyor belt speed is 55 m/min.")
    last = names[-1]
    topo.stop(last)
    a = open_store(topo.db[names[0]])
    correction.apply(a, ids2[names[0]], reason="re-measured", actor="lead")
    a.close()
    time.sleep(4)
    while_down = state_of(topo, last, ids2[last])
    t1 = time.perf_counter()
    topo.start(last)
    recovered_s = None
    while time.perf_counter() - t1 < 90:
        if state_of(topo, last, ids2[last]) != "active":
            recovered_s = time.perf_counter() - t1
            break
        time.sleep(0.25)
    return {"stores": len(names), "share_chain_s": round(share_s, 2),
            "correction_reached_last_store_s": None if converge_s is None else round(converge_s, 2),
            "states_after_correction": states,
            "last_store_while_offline": while_down,
            "converged_after_restart_s": None if recovered_s is None else round(recovered_s, 2)}


def partition(topo: Topology, a: str, b: str, blocked: bool) -> None:
    """Cut (or heal) the link between two stores in both directions; both stay up."""
    topo.proxy[(a, b)].blocked = blocked
    topo.proxy[(b, a)].blocked = blocked


def network_scenarios(topo: Topology) -> dict[str, Any]:
    """A partition with both servers up, and two corrections at once at different stores."""
    from memory_fabric import correction

    names = topo.names
    first, mid, last = names[0], names[1], names[-1]
    out: dict[str, Any] = {}

    ids = share_chain(topo, "Line 5 conveyor belt speed is 35 m/min.")
    partition(topo, mid, last, True)
    a = open_store(topo.db[first])
    correction.apply(a, ids[first], reason="re-measured", actor="lead")
    a.close()
    time.sleep(4)
    out["partition_mid_withdrawn"] = state_of(topo, mid, ids[mid]) != "active"
    out["partition_last_while_cut"] = state_of(topo, last, ids[last])
    healed = time.perf_counter()
    partition(topo, mid, last, False)
    out["partition_converged_after_heal_s"] = None
    while time.perf_counter() - healed < 90:
        if state_of(topo, last, ids[last]) != "active":
            out["partition_converged_after_heal_s"] = round(time.perf_counter() - healed, 2)
            break
        time.sleep(0.25)

    x = share_chain(topo, "Line 6 conveyor belt speed is 45 m/min.")
    y = share_chain(topo, "Line 7 conveyor belt speed is 50 m/min.")
    started = time.perf_counter()

    def withdraw(store: str, memory_id: str) -> None:
        f = open_store(topo.db[store])
        try:
            correction.apply(f, memory_id, reason="re-measured", actor="lead")
        finally:
            f.close()

    threads = [threading.Thread(target=withdraw, args=(first, x[first])),
               threading.Thread(target=withdraw, args=(mid, y[mid]))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out["concurrent_converged_s"] = None
    while time.perf_counter() - started < 90:
        if (state_of(topo, last, x[last]) != "active"
                and state_of(topo, last, y[last]) != "active"):
            out["concurrent_converged_s"] = round(time.perf_counter() - started, 2)
            break
        time.sleep(0.25)
    out["concurrent_origin_y_still_active"] = state_of(topo, first, y[first]) == "active"
    for n in names:
        f = open_store(topo.db[n])
        try:
            out[f"chain_verifies_{n}"] = f.log.chain.verify(list(f.log.read())).ok
        finally:
            f.close()
    return out


def run(stores: int, latency_ms: float, network: bool = False) -> dict[str, Any]:
    names = [chr(ord("a") + i) for i in range(stores)]
    with tempfile.TemporaryDirectory() as tmp:
        topo = Topology(names, latency_ms, Path(tmp))
        try:
            for n in names:
                topo.start(n)
            result = scenario(topo)
            if network:
                result.update(network_scenarios(topo))
        finally:
            topo.stop_all()
    return {"latency_ms_per_hop": latency_ms, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--mode", choices=("processes", "prepare", "compose"),
                        default="processes")
    parser.add_argument("--stores", type=int, default=3)
    parser.add_argument("--latency-ms", type=float, default=50)
    parser.add_argument("--workdir", type=Path, default=ROOT / "deploy" / "multihost" / "work")
    parser.add_argument("--compose-file", type=Path,
                        default=ROOT / "deploy" / "multihost" / "docker-compose.yml")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    names = [chr(ord("a") + i) for i in range(args.stores)]
    if args.mode == "prepare":
        prepare_compose(names, args.workdir)
        print(f"prepared {len(names)} stores in {args.workdir}")
        return 0
    if args.mode == "compose":
        topo = ComposeTopology(args.workdir, args.compose_file)
        for n in topo.names:
            wait_health(f"http://127.0.0.1:{topo.host_port[n]}", timeout_s=60)
        body = {"latency_ms_per_hop": None, **scenario(topo),
                "note": "separate containers and network stacks on one physical machine"}
    else:
        body = run(args.stores, args.latency_ms)
    result = {"mode": args.mode, "machine": platform.platform(),
              "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                       capture_output=True, text=True, cwd=ROOT).stdout.strip(),
              **body}
    print(json.dumps(result, indent=2))
    out = args.out or (OUT if args.mode == "processes"
                       else OUT.with_name("multihost-compose.json"))
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    ok = (result["correction_reached_last_store_s"] is not None
          and result["last_store_while_offline"] == "active"
          and result["converged_after_restart_s"] is not None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
