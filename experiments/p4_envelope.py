"""P4 — the operational envelope, measured rather than assumed.

Four questions the single-process team harness cannot answer: what happens with
many concurrent writers, what retrieval costs as a store grows, whether
authorisation holds under load, and whether the store converges after a kill
while contended.

**Not a test suite.** The invariants live in `tests/test_concurrency.py` and
`tests/test_multiprocess_crash.py`; this sweep pushes the same machinery to 10,
25 and 50 real processes and reports what it costs. A sweep that asserted
nothing would be theatre, so each row carries its own pass condition and the
run exits non-zero if any fails.

## Why real processes

Threads in one interpreter share a connection pool and would measure Python's
GIL rather than SQLite's locking. The existing concurrency tests use three or
four processes and **pass with the busy-timeout pragma removed**, because
writers do not reliably overlap on a fast disk — a weakness recorded in
`docs/VALIDATION.md`. At 50 writers the overlap should be real, which is the
other reason for this sweep.

## Do not assume linear

The brief for this work said so explicitly, and the team harness already found
one case where the naive expectation was wrong in the *good* direction:
retrieval latency rose 1.6x for ten times the agents and ten times the facts.
Every row here reports the measured figure next to the per-unit cost so a
departure from linear is visible rather than inferred.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from amberlog import Amberlog  # noqa: E402

WRITER = textwrap.dedent(
    """
    import json, sys
    sys.path.insert(0, {root!r})
    from amberlog import Amberlog

    path, label, count, timeout = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    fabric = Amberlog(path, auto_activate=True, encrypt_content=False,
                          busy_timeout_ms=timeout, recognise_copies=False)
    written, failures = 0, []
    try:
        for index in range(count):
            try:
                fabric.remember(agent_id=label,
                                content=f"{{label}} observed condition {{index}} at the yard")
                written += 1
            except Exception as exc:
                failures.append(type(exc).__name__)
    finally:
        fabric.close()
    print(json.dumps({{"label": label, "written": written, "failures": failures}}))
    """
)


@dataclass
class Row:
    scenario: str
    scale: str
    measured: dict[str, Any]
    passed: bool
    note: str = ""


@dataclass
class Envelope:
    rows: list[Row] = field(default_factory=list)

    def add(self, row: Row) -> None:
        self.rows.append(row)

    @property
    def ok(self) -> bool:
        return all(r.passed for r in self.rows)


# --- 1. concurrent writers --------------------------------------------------


def concurrent_writers(env: Envelope, counts: Sequence[int], appends: int) -> None:
    """N processes appending to one store. Every write must land, in order.

    `recognise_copies=False` in the writers on purpose: copy recognition is a
    linear scan of held content per write, so leaving it on would make this
    measure that scan rather than SQLite's write path. Its own cost is measured
    in scenario 2.
    """
    for writers in counts:
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            path = directory / "store.db"
            Amberlog(path, auto_activate=True, encrypt_content=False).close()
            script = directory / "writer.py"
            script.write_text(WRITER.format(root=str(ROOT)), encoding="utf-8")

            started = time.perf_counter()
            processes = [
                subprocess.Popen(
                    [sys.executable, str(script), str(path), f"w{i}",
                     str(appends), "20000"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for i in range(writers)
            ]
            results, crashed = [], 0
            for process in processes:
                out, err = process.communicate(timeout=600)
                if process.returncode != 0:
                    crashed += 1
                    continue
                results.append(json.loads(out.strip().splitlines()[-1]))
            elapsed = time.perf_counter() - started

            fabric = Amberlog(path, auto_activate=True, encrypt_content=False)
            try:
                stored = len(fabric.state.memories)
                sequences = [e.seq for e in fabric.log.read()]
                gaps = sequences != list(range(1, len(sequences) + 1))
            finally:
                fabric.close()

            expected = writers * appends
            written = sum(r["written"] for r in results)
            failures = sum(len(r["failures"]) for r in results)
            env.add(Row(
                scenario="concurrent writers",
                scale=f"{writers} processes x {appends} appends",
                measured={
                    "expected": expected,
                    "written": written,
                    "stored": stored,
                    "failures": failures,
                    "crashed_processes": crashed,
                    "sequence_gaps": gaps,
                    "wall_s": round(elapsed, 2),
                    "ms_per_append": round(elapsed * 1000 / max(1, expected), 3),
                },
                passed=(crashed == 0 and failures == 0 and written == expected
                        and stored == expected and not gaps),
                note="every append lands, the sequence has no gaps",
            ))


# --- 2. retrieval latency against store size --------------------------------


def retrieval_latency(env: Envelope, sizes: Sequence[int], queries: int = 40,
                      copies: bool = False) -> None:
    for size in sizes:
        fabric = Amberlog(
            ":memory:", auto_activate=True, encrypt_content=False,
            retrieval="lexical", recognise_copies=copies)
        try:
            write_started = time.perf_counter()
            for index in range(size):
                fabric.remember(
                    agent_id=f"ag-{index % 50:02d}",
                    content=(f"unit-{index % 97} requires {1 + index % 9}.{index % 10} m "
                             f"of clearance at the site-{index % 31} depot"), scope="team")
            write_ms = (time.perf_counter() - write_started) * 1000 / max(1, size)

            read_started = time.perf_counter()
            for q in range(queries):
                fabric.retrieve(
                    agent_id="ag-00",
                    query=f"how much clearance does unit-{q % 97} need at site-{q % 31}",
                    k=5, min_relevance=0.0)
            read_ms = (time.perf_counter() - read_started) * 1000 / queries
        finally:
            fabric.close()
        env.add(Row(
            scenario="retrieval latency" + (" (copy check on)" if copies else ""),
            scale=f"{size} memories",
            measured={"ms_per_retrieval": round(read_ms, 3),
                      "ms_per_write": round(write_ms, 3)},
            passed=True,
            note="reported, not gated: there is no registered latency budget",
        ))


# --- 3. authorisation under load --------------------------------------------


def authorisation_under_load(env: Envelope, agents: Sequence[int]) -> None:
    """Many agents, several tenants, one store. Zero cross-tenant exposure.

    A pass condition rather than a measurement: any leak fails the run whatever
    the latency said.
    """
    for count in agents:
        tenants = [f"tn-{i}" for i in range(4)]
        fabric = Amberlog(":memory:", auto_activate=True,
                              encrypt_content=False, retrieval="lexical",
                              recognise_copies=False)
        try:
            owner: dict[str, str] = {}
            for index in range(count * 4):
                tenant = tenants[index % len(tenants)]
                mid = fabric.remember(
                    agent_id=f"ag-{index % count:03d}",
                    tenant_id=tenant,
                    content=(f"tenant {tenant} unit-{index % 23} requires "
                             f"{1 + index % 9}.0 m of clearance at the depot"), scope="team")
                owner[mid] = tenant

            leaks = 0
            checked = 0
            started = time.perf_counter()
            for index in range(count):
                tenant = tenants[index % len(tenants)]
                result = fabric.retrieve(
                    agent_id=f"ag-{index:03d}", tenant_id=tenant,
                    query="how much clearance is required at the depot",
                    k=10, min_relevance=0.0)
                for memory in result.exposed:
                    checked += 1
                    if owner[memory.id] != tenant:
                        leaks += 1
            elapsed = (time.perf_counter() - started) * 1000 / max(1, count)
        finally:
            fabric.close()
        env.add(Row(
            scenario="authorisation under load",
            scale=f"{count} agents, 4 tenants, {count * 4} memories",
            measured={"exposures_checked": checked, "cross_tenant_leaks": leaks,
                      "ms_per_retrieval": round(elapsed, 3)},
            passed=leaks == 0,
            note="any non-zero leak fails the run whatever else it measured",
        ))


# --- 4. recovery after a kill while contended -------------------------------


def recovery_under_contention(env: Envelope, writers: int, appends: int) -> None:
    """Kill a contended store mid-write, reopen, and check it is usable.

    The existing fault scenarios kill a *quiet* store. The question here is
    whether a kill during real contention leaves the log readable and the
    sequence intact -- a partially written frame is the failure mode, and it is
    only reachable while others are writing.
    """
    with tempfile.TemporaryDirectory() as tmp:
        directory = pathlib.Path(tmp)
        path = directory / "store.db"
        Amberlog(path, auto_activate=True, encrypt_content=False).close()
        script = directory / "writer.py"
        script.write_text(WRITER.format(root=str(ROOT)), encoding="utf-8")

        processes = [
            subprocess.Popen(
                [sys.executable, str(script), str(path), f"w{i}", str(appends),
                 "20000"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for i in range(writers)
        ]
        time.sleep(0.25)
        victims = processes[: max(1, writers // 3)]
        for process in victims:
            process.kill()
        survived = 0
        for process in processes:
            try:
                out, _err = process.communicate(timeout=600)
            except subprocess.TimeoutExpired:
                process.kill()
                continue
            if process.returncode == 0 and out.strip():
                survived += 1

        reopened = Amberlog(path, auto_activate=True, encrypt_content=False)
        try:
            sequences = [e.seq for e in reopened.log.read()]
            gaps = sequences != list(range(1, len(sequences) + 1))
            stored = len(reopened.state.memories)
            # Still writable after the kill.
            reopened.remember(agent_id="after", content="a write after recovery", scope="team")
            usable = len(reopened.state.memories) == stored + 1
        finally:
            reopened.close()

    env.add(Row(
        scenario="recovery after a kill under contention",
        scale=f"{writers} writers, {len(victims)} killed mid-write",
        measured={"survivors": survived, "killed": len(victims),
                  "stored": stored, "sequence_gaps": gaps, "writable_after": usable},
        passed=(not gaps) and usable,
        note="no gaps in the log and the store still accepts writes",
    ))


# --- reporting --------------------------------------------------------------


def to_markdown(env: Envelope) -> str:
    lines = [
        "# P4 — operational envelope",
        "",
        "Real processes, not threads. Each row carries its own pass condition; "
        "a sweep that asserted nothing would be theatre.",
        "",
        "| scenario | scale | measured | pass |",
        "|---|---|---|---|",
    ]
    for row in env.rows:
        measured = ", ".join(f"{k}={v}" for k, v in row.measured.items())
        mark = "pass" if row.passed else "**FAIL**"
        lines.append(f"| {row.scenario} | {row.scale} | {measured} | {mark} |")
    lines += ["", "Pass conditions:", ""]
    seen = set()
    for row in env.rows:
        if row.note and row.note not in seen:
            seen.add(row.note)
            lines.append(f"- **{row.scenario}** — {row.note}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--writers", type=int, nargs="*", default=[10, 25, 50])
    parser.add_argument("--appends", type=int, default=10)
    parser.add_argument("--sizes", type=int, nargs="*",
                        default=[100, 1_000, 10_000])
    parser.add_argument("--agents", type=int, nargs="*", default=[10, 50, 100])
    parser.add_argument("--skip", nargs="*", default=[])
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    env = Envelope()
    if "writers" not in args.skip:
        concurrent_writers(env, args.writers, args.appends)
    if "latency" not in args.skip:
        retrieval_latency(env, args.sizes)
        retrieval_latency(env, args.sizes[:2], copies=True)
    if "auth" not in args.skip:
        authorisation_under_load(env, args.agents)
    if "recovery" not in args.skip:
        recovery_under_contention(env, max(args.writers), args.appends)

    text = to_markdown(env)
    print(text)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if env.ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
