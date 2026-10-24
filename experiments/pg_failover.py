"""PostgreSQL failover: what survives when the primary dies mid-write?

A real primary and a streaming replica (`pg_basebackup -R`), run locally. A
writer appends memories and records which ones the store acknowledged. The
primary is killed with `pg_ctl stop -m immediate` partway through, the
replica is promoted, and the writer reopens the store through a multi-host
URL (`host=a,b`, `target_session_attrs=read-write`). That is libpq's own
client-side failover, so no proxy is involved. Run twice:

- `sync`: `synchronous_standby_names='*'`, so a commit waits for the replica;
- `async`: the default, where a commit can be acknowledged before the
  replica has it.

Checked on the promoted node: every acknowledged write is present (or how
many are lost), the hash chain verifies, sequence numbers have no gap,
`doctor` is sound, and writes after the failover succeed and chain on.

    python -m experiments.pg_failover            # needs postgres binaries and a non-root user

Not pre-registered: an operational test. Postgres refuses to run as root, so
the servers run as `--os-user` (default `pgtest`).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BIN = Path("/usr/lib/postgresql/16/bin")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Cluster:
    def __init__(self, base: Path, user: str, sync: bool) -> None:
        self.base, self.user, self.sync = base, user, sync
        self.p1, self.p2 = free_port(), free_port()
        self.primary, self.replica = base / "primary", base / "replica"

    def sh(self, *cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["runuser", "-u", self.user, "--", *cmd], capture_output=True,
                              text=True, check=check)

    def up(self) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        shutil.chown(self.base, self.user)
        self.sh(str(BIN / "initdb"), "-D", str(self.primary), "-A", "trust", "-U", "postgres")
        conf = [f"port = {self.p1}", "listen_addresses = '127.0.0.1'", "wal_level = replica",
                "max_wal_senders = 4", "hot_standby = on", "unix_socket_directories = ''"]
        if self.sync:
            conf += ["synchronous_standby_names = '*'", "synchronous_commit = on"]
        with open(self.primary / "postgresql.conf", "a") as fh:
            fh.write("\n".join(conf) + "\n")
        with open(self.primary / "pg_hba.conf", "a") as fh:
            fh.write("host replication all 127.0.0.1/32 trust\n")
        self.sh(str(BIN / "pg_ctl"), "-D", str(self.primary), "-l", str(self.base / "p.log"),
                "-w", "start")
        self.sh(str(BIN / "pg_basebackup"), "-h", "127.0.0.1", "-p", str(self.p1), "-U",
                "postgres", "-D", str(self.replica), "-R", "-X", "stream")
        with open(self.replica / "postgresql.conf", "a") as fh:
            fh.write(f"port = {self.p2}\n")
        self.sh(str(BIN / "pg_ctl"), "-D", str(self.replica), "-l", str(self.base / "r.log"),
                "-w", "start")

    def url(self) -> str:
        return (f"postgresql://postgres@127.0.0.1:{self.p1},127.0.0.1:{self.p2}/postgres"
                "?target_session_attrs=read-write&connect_timeout=3")

    def promoted_url(self) -> str:
        return f"postgresql://postgres@127.0.0.1:{self.p2}/postgres"

    def kill_primary(self) -> None:
        self.sh(str(BIN / "pg_ctl"), "-D", str(self.primary), "-m", "immediate", "stop",
                check=False)

    def promote(self) -> None:
        self.sh(str(BIN / "pg_ctl"), "-D", str(self.replica), "-w", "promote")

    def drop_sync_requirement(self) -> None:
        """Runbook step after promoting a sync replica: it has no standby of its own."""
        self.sh(str(BIN / "psql"), "-h", "127.0.0.1", "-p", str(self.p2), "-U", "postgres",
                "-c", "ALTER SYSTEM SET synchronous_standby_names = ''",
                "-c", "SELECT pg_reload_conf()")

    def sql(self, query: str) -> str:
        return self.sh(str(BIN / "psql"), "-h", "127.0.0.1", "-p", str(self.p2), "-U",
                       "postgres", "-At", "-c", query).stdout

    def down(self) -> None:
        for d in (self.primary, self.replica):
            self.sh(str(BIN / "pg_ctl"), "-D", str(d), "-m", "immediate", "stop", check=False)


def run_mode(sync: bool, user: str, writes: int) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT))
    from memory_fabric import MemoryFabric

    base = Path(tempfile.mkdtemp(prefix=f"mffo-{'sync' if sync else 'async'}-", dir="/var/tmp"))
    cluster = Cluster(base, user, sync)
    out: dict[str, Any] = {"mode": "sync" if sync else "async"}
    try:
        cluster.up()
        fabric = MemoryFabric(cluster.url(), auto_activate=True)
        acknowledged: list[str] = []
        failed_during = 0
        kill_at = writes // 2
        for i in range(writes):
            if i == kill_at:
                cluster.kill_primary()
                started = time.perf_counter()
                cluster.promote()
                out["promotion_s"] = round(time.perf_counter() - started, 2)
                # pg_basebackup copied synchronous_standby_names: a promoted
                # sync replica waits at every commit for a standby it does not
                # have, and statement_timeout does not interrupt that wait (the
                # first run of this harness hung there). Detect the condition
                # instead of writing into it, then apply the runbook step.
                names = cluster.sql("SHOW synchronous_standby_names").strip()
                standbys = int(cluster.sql("SELECT count(*) FROM pg_stat_replication").strip() or 0)
                out["writes_block_after_promotion"] = bool(names) and standbys == 0
                if out["writes_block_after_promotion"]:
                    cluster.drop_sync_requirement()
                try:
                    fabric.close()
                except Exception:  # noqa: BLE001 - the connection is already gone
                    pass
                reopened = time.perf_counter()
                fabric = MemoryFabric(cluster.url(), auto_activate=True)
                out["reconnect_s"] = round(time.perf_counter() - reopened, 2)
            try:
                acknowledged.append(fabric.remember("ag_writer", f"Pump P-{i}: relief pressure "
                                                                  f"is {10 + i % 30} bar."))
            except Exception as exc:  # noqa: BLE001 - counted, never hidden
                failed_during += 1
                out.setdefault("errors", []).append(f"{type(exc).__name__}: {str(exc)[:120]}")
        fabric.close()

        check = MemoryFabric(cluster.promoted_url())
        try:
            present = set(check.state.memories)
            lost = [m for m in acknowledged if m not in present]
            events = list(check.log.read())
            seqs = [e.seq for e in events]
            out.update({
                "writes_attempted": writes,
                "acknowledged": len(acknowledged),
                "failed_writes": failed_during,
                "acknowledged_lost": len(lost),
                "acknowledged_lost_before_kill": sum(1 for m in lost
                                                     if acknowledged.index(m) < kill_at),
                "chain_verifies": check.log.chain.verify(events).ok,
                "seq_gapless": seqs == list(range(seqs[0], seqs[0] + len(seqs))) if seqs else True,
                "writes_after_failover": sum(1 for m in acknowledged[kill_at:] if m in present),
            })
        finally:
            check.close()
        doctor = subprocess.run([sys.executable, "-m", "memory_fabric", "--db",
                                 cluster.promoted_url(), "--json", "doctor"],
                                capture_output=True, text=True, cwd=ROOT)
        try:
            out["doctor_sound"] = json.loads(doctor.stdout).get("sound")
        except ValueError:
            out["doctor_sound"] = None
            out["doctor_error"] = (doctor.stderr or doctor.stdout)[-300:]
    finally:
        cluster.down()
        shutil.rmtree(base, ignore_errors=True)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--os-user", default="pgtest")
    p.add_argument("--writes", type=int, default=200)
    args = p.parse_args(argv)
    if not (BIN / "postgres").exists():
        print("postgres binaries not found", file=sys.stderr)
        return 2
    results = [run_mode(True, args.os_user, args.writes), run_mode(False, args.os_user, args.writes)]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    out = ROOT / "research" / "results"
    (out / "pg-failover.json").write_text(json.dumps({"commit": commit, "results": results},
                                                     indent=2) + "\n")
    rows = "\n".join(
        f"| {r['mode']} | {r.get('acknowledged')}/{r.get('writes_attempted')} "
        f"| {r.get('failed_writes')} | **{r.get('acknowledged_lost')}** "
        f"| {r.get('chain_verifies')} | {r.get('seq_gapless')} | {r.get('doctor_sound')} "
        f"| {r.get('writes_after_failover')} | {r.get('promotion_s')} s / {r.get('reconnect_s')} s |"
        for r in results)
    (out / "pg-failover.md").write_text(f"""# PostgreSQL failover: primary killed mid-write, replica promoted

Produced by `python -m experiments.pg_failover` at commit `{commit}`; raw numbers in
[pg-failover.json](pg-failover.json). PostgreSQL 16, a primary and a streaming
replica on one machine. {results[0].get('writes_attempted')} writes, primary killed (`-m immediate`) at the halfway
point, replica promoted, the client reopened through a multi-host URL
(`target_session_attrs=read-write`). An operational test, not pre-registered.

| replication | acknowledged | failed writes | acknowledged and lost | chain verifies | seq gapless | doctor sound | writes after failover | promote / reconnect |
|---|---|---|---|---|---|---|---|---|
{rows}

Writes blocked on the promoted node before the runbook step:
{', '.join(f"{r['mode']}: {r.get('writes_block_after_promotion')}" for r in results)}.
""")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
