"""End-to-end validation across real process boundaries (plan Phase 2).

The unit suite tests retraction, recovery, tenancy and action-time checks
in-process. Each scenario here crosses a boundary those tests cannot: a
separately launched `agent-api` server, a separate CLI process that
quarantines, a store written by one process and read by another, and a child
killed with `os._exit` partway through a retraction.

    python -m experiments.e2e_validation         # runs all, writes the result
    python -m experiments.e2e_validation --quick # runs all, prints only

Every check prints PASS or FAIL. The exit code is non-zero if any check fails.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
CLI = [PY, "-m", "memory_fabric"]
WORKER = [PY, str(ROOT / "tests" / "crashworker.py")]
KEY_A, KEY_G = "aa" * 32, "cc" * 32

results: list[dict[str, Any]] = []


def check(scenario: str, name: str, ok: bool, detail: str = "") -> None:
    results.append({"scenario": scenario, "check": name, "ok": bool(ok), "detail": detail})
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=ROOT, **kw)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(port: int, op: str, body: dict, token: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/{op}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def wait_for(port: int, seconds: float = 20.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=1):
                return True
        except Exception:  # noqa: BLE001 - polling a server that is starting
            time.sleep(0.2)
    return False


# --- scenarios ---------------------------------------------------------------


def scenario_action_time_and_tenancy(tmp: Path) -> None:
    """A server process, a client over HTTP, and a CLI process that retracts."""
    from memory_fabric import MemoryFabric
    from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule

    print("E1 action-time checks and tenancy across processes")
    store = tmp / "e1.db"
    seed = MemoryFabric(store, auto_activate=True)
    fact = seed.remember("ag_seed", "Valve 7 on the coastal line is upstream of pump 3.",
                         tenant_id="tn_acme", scope="team")
    seed.close()
    agents = tmp / "agents"
    agents.write_text(f"ag_a:tn_acme:{KEY_A}\nag_g:tn_globex:{KEY_G}\n")
    port = free_port()
    server = subprocess.Popen(CLI + ["--db", str(store), "agent-api", "--agents-file",
                                     str(agents), "--port", str(port)],
                              cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        check("E1", "agent-api server starts in its own process", wait_for(port))
        tok_a = run(CLI + ["--db", str(store), "agent-api-issue", "--agents-file", str(agents),
                           "--agent", "ag_a"]).stdout.strip().splitlines()[-1]
        tok_g = run(CLI + ["--db", str(store), "agent-api-issue", "--agents-file", str(agents),
                           "--agent", "ag_g"]).stdout.strip().splitlines()[-1]

        status, body = post(port, "recall", {"query": "valve 7 coastal pump"}, tok_a)
        check("E1", "own tenant: recall finds the memory over HTTP",
              status == 200 and fact in [m["memory_id"] for m in body.get("memories", [])])
        status, body = post(port, "verify", {"memory_id": fact}, tok_a)
        check("E1", "own tenant: verify says usable", status == 200 and body.get("usable") is True)

        status, body = post(port, "recall", {"query": "valve 7 coastal pump"}, tok_g)
        check("E1", "other tenant: recall returns nothing",
              status == 200 and body.get("memories") == [])
        status, body = post(port, "fetch", {"memory_id": fact}, tok_g)
        check("E1", "other tenant: fetch is refused without content",
              status != 200 and "upstream" not in json.dumps(body))

        # A client handle opened now, with a certificate issued now: stale once
        # the CLI process below retracts.
        client = MemoryFabric(store)
        gate = ActionGate(client, ActionPolicy(tools={"open_valve": ToolRule("open_valve")},
                                               grants={"ag_a": frozenset({"open_valve"})}))
        cert = client.certify("open-valve-7", [fact], "ag_a", tenant_id="tn_acme")
        check("E1", "gate allows before the retraction",
              gate.authorize("open_valve", "ag_a", cert, tenant_id="tn_acme").allowed)

        done = run(CLI + ["--db", str(store), "quarantine", fact, "--reason",
                          "valve 7 is downstream, survey was wrong", "--basis", "contradicted"])
        check("E1", "a separate CLI process quarantines", done.returncode == 0,
              done.stderr.strip()[-120:])

        status, body = post(port, "verify", {"memory_id": fact}, tok_a)
        check("E1", "server process sees the retraction: verify not usable",
              status == 200 and body.get("usable") is False, str(body.get("reason_code")))
        decision = gate.authorize("open_valve", "ag_a", cert, tenant_id="tn_acme")
        check("E1", "gate in a third process refuses the stale certificate",
              not decision.allowed, ",".join(decision.reason_codes))
        status, body = post(port, "recall", {"query": "valve 7 coastal pump"}, tok_a)
        check("E1", "recall no longer returns it",
              fact not in [m["memory_id"] for m in body.get("memories", [])])
        client.close()
    finally:
        server.terminate()
        server.wait(timeout=20)


def scenario_crash_recovery(tmp: Path) -> None:
    """A child process killed with os._exit at two points of a retraction."""
    from memory_fabric import LifecycleState, MemoryFabric
    from memory_fabric.dispatcher import Dispatcher
    from memory_fabric.transport import InProcessTransport

    print("E2 crash during retraction, then recovery")
    origin, recipient = tmp / "origin.db", tmp / "recipient.db"
    run(WORKER + ["seed", str(origin)])
    imported = run(WORKER + ["share", str(origin), str(recipient)]).stdout.strip()
    r = MemoryFabric(recipient)
    recipient_id = r.store_id
    r.close()

    mid_crash = run(WORKER + ["crash_mid_retraction_transaction", str(origin), recipient_id])
    o = MemoryFabric(origin)
    memory_id = next(iter(o.state.memories))
    check("E2", "killed inside the retraction transaction: nothing survives",
          mid_crash.returncode == 70 and o.get(memory_id).lifecycle_state is LifecycleState.ACTIVE
          and not o.outbox.pending(), f"exit {mid_crash.returncode}")
    o.close()

    after_commit = run(WORKER + ["crash_after_retraction_commit", str(origin), recipient_id])
    o = MemoryFabric(origin)
    owed = o.outbox.pending()
    check("E2", "killed after commit: withdrawn locally and the delivery is still owed",
          after_commit.returncode == 70
          and o.get(memory_id).lifecycle_state is LifecycleState.QUARANTINED and len(owed) == 1,
          f"exit {after_commit.returncode}, {len(owed)} owed")
    r = MemoryFabric(recipient)
    check("E2", "the recipient has not seen it yet",
          r.get(imported).lifecycle_state is LifecycleState.ACTIVE)
    report = Dispatcher(o, InProcessTransport({recipient_id: r})).drain()
    check("E2", "a restarted dispatcher delivers it",
          r.get(imported).lifecycle_state is LifecycleState.QUARANTINED,
          f"enforced {report.enforced}")
    check("E2", "nothing remains owed", not o.outbox.pending())
    for name, store in (("origin", o), ("recipient", r)):
        check("E2", f"{name} hash chain verifies after the crash",
              store.log.chain.verify(list(store.log.read())).ok)
    o.close()
    r.close()


def scenario_backup_restore(tmp: Path) -> None:
    from memory_fabric import LifecycleState, MemoryFabric

    print("E3 backup and restore")
    store, copy = tmp / "b.db", tmp / "b-copy.db"
    f = MemoryFabric(store, auto_activate=True)
    keep = f.remember("ag", "Hoist 6 is rated 2 tonnes.", scope="team")
    gone = f.remember("ag", "Hoist 6 is rated 3 tonnes.", scope="team")
    f.quarantine(gone, reason="wrong", basis="contradicted")
    checkpoint = f.log.chain.checkpoint()
    f.close()
    done = run(CLI + ["--db", str(store), "backup", str(copy)])
    check("E3", "backup command succeeds", done.returncode == 0, done.stderr.strip()[-120:])
    c = MemoryFabric(copy)
    check("E3", "restored copy has the same memories and states",
          c.get(keep).lifecycle_state is LifecycleState.ACTIVE
          and c.get(gone).lifecycle_state is LifecycleState.QUARANTINED)
    check("E3", "restored copy keeps the store identity",
          c.store_id == MemoryFabric(store).store_id)
    check("E3", "restored copy verifies against the original's checkpoint",
          c.log.chain.verify_against(checkpoint).ok)
    doctor = run(CLI + ["--db", str(copy), "--json", "doctor"])
    check("E3", "doctor reports the restored copy sound",
          json.loads(doctor.stdout or "{}").get("sound") is True)
    c.close()


SCENARIOS: list[Callable[[Path], None]] = [
    scenario_action_time_and_tenancy, scenario_crash_recovery, scenario_backup_restore,
]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    with tempfile.TemporaryDirectory() as tmp:
        for scenario in SCENARIOS:
            try:
                scenario(Path(tmp))
            except Exception as exc:  # noqa: BLE001 - a crashed scenario is a failed check
                check(scenario.__name__, "scenario ran to completion", False,
                      f"{type(exc).__name__}: {exc}")
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if "--quick" not in argv:
        commit = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
        out = ROOT / "research" / "results"
        (out / "e2e-validation.json").write_text(json.dumps(
            {"commit": commit, "results": results}, indent=2) + "\n")
        rows = "\n".join(f"| {r['scenario']} | {r['check']} | {'PASS' if r['ok'] else '**FAIL**'} "
                         f"| {r['detail']} |" for r in results)
        (out / "e2e-validation.md").write_text(f"""# End-to-end validation across process boundaries

Produced by `python -m experiments.e2e_validation` at commit `{commit}`.
**{len(results) - len(failed)}/{len(results)} checks passed.**

- **E1**: an `agent-api` server in its own process, agents in two tenants over
  HTTP, a separate CLI process that quarantines, and an action gate in a third
  process holding a certificate issued before the retraction.
- **E2**: a child killed with `os._exit` inside, then just after, the
  transaction that records a retraction. The store is then reopened and the
  delivery recovered.
- **E3**: the `backup` command, then the copy opened as a store.

| scenario | check | result | detail |
|---|---|---|---|
{rows}
""")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
