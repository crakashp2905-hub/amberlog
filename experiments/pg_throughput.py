"""Append throughput: SQLite against PostgreSQL, by number of writers.

`memory_fabric/storage/postgres.py` serialises appends on one row lock, and
its docstring needs a measured figure for what that costs rather than an
assertion. This is that figure.

Each writer opens its own handle -- one connection per thread, as both
backends are meant to be shared -- and appends single-event transactions as
fast as it can for a fixed duration. Reported: committed appends per second
in total, and the p50/p95 latency of one append as each writer saw it.

Run from an environment with `psycopg` and a Postgres DSN:

    MEMORY_FABRIC_TEST_PG=postgresql://... python -m experiments.pg_throughput
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory_fabric.eventlog import EventLog  # noqa: E402
from memory_fabric.events import Event  # noqa: E402


def event() -> Event:
    return Event(type="memory_created", ts=int(time.time() * 1000),
                 payload={"content": "Fault E03 at coastal: swap the cable.",
                          "n": 1},
                 agent_id="a", episode_id=None,
                 event_id=uuid.uuid4().hex, schema_version="0.9.0")


def measure(opener: Callable[[], Any], writers: int,
            seconds: float) -> dict[str, Any]:
    latencies: list[list[float]] = [[] for _ in range(writers)]
    barrier = threading.Barrier(writers)
    deadline = [0.0]
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        log = opener()
        try:
            barrier.wait()
            if index == 0:
                deadline[0] = time.perf_counter() + seconds
            while deadline[0] == 0.0:
                time.sleep(0)
            while time.perf_counter() < deadline[0]:
                started = time.perf_counter()
                log.append(event())
                latencies[index].append((time.perf_counter() - started) * 1000)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            log.close()

    threads = [threading.Thread(target=worker, args=(i,))
               for i in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    flat = sorted(x for row in latencies for x in row)
    return {
        "writers": writers,
        "appends": len(flat),
        "per_second": round(len(flat) / seconds, 1),
        "p50_ms": round(flat[len(flat) // 2], 3) if flat else None,
        "p95_ms": round(flat[int(0.95 * len(flat))], 3) if flat else None,
        "errors": [repr(e)[:120] for e in errors],
    }


def run(writer_counts: Sequence[int], seconds: float) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        for writers in writer_counts:
            path = str(Path(tmp) / f"log-{writers}.db")
            EventLog(path).close()
            row = measure(lambda: EventLog(path, busy_timeout_ms=60_000),
                          writers, seconds)
            rows.append({"backend": "sqlite", **row})
            print(f"  sqlite   writers={writers}: {row['per_second']}/s "
                  f"p95={row['p95_ms']}ms", file=sys.stderr)

    dsn = os.environ.get("MEMORY_FABRIC_TEST_PG")
    if dsn:
        import psycopg
        from memory_fabric.storage.postgres import PostgresEventLog

        for writers in writer_counts:
            schema = "tp_" + uuid.uuid4().hex[:10]
            PostgresEventLog(dsn, schema=schema).close()
            try:
                row = measure(lambda: PostgresEventLog(dsn, schema=schema),
                              writers, seconds)
                rows.append({"backend": "postgres", **row})
                print(f"  postgres writers={writers}: {row['per_second']}/s "
                      f"p95={row['p95_ms']}ms", file=sys.stderr)
            finally:
                with psycopg.connect(dsn, autocommit=True) as conn:
                    conn.execute(psycopg.sql.SQL(
                        "DROP SCHEMA IF EXISTS {} CASCADE").format(
                        psycopg.sql.Identifier(schema)))
    return {
        "experiment": "pg-throughput",
        "seconds_per_cell": seconds,
        "note": ("single-event transactions, one connection per writer, one "
                 "machine; a remote Postgres adds a network round trip per "
                 "append that this does not measure"),
        "rows": rows,
    }


def to_markdown(result: dict[str, Any]) -> str:
    lines = ["# Append throughput by backend and writers", "",
             f"{result['seconds_per_cell']} s per cell. {result['note']}.", "",
             "| backend | writers | appends/s | p50 ms | p95 ms | errors |",
             "|---|---|---|---|---|---|"]
    for r in result["rows"]:
        lines.append(f"| {r['backend']} | {r['writers']} | {r['per_second']} "
                     f"| {r['p50_ms']} | {r['p95_ms']} | {len(r['errors'])} |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--writers", type=int, nargs="*", default=[1, 2, 4, 8])
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = run(args.writers, args.seconds)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n",
                                  encoding="utf-8")
    print(to_markdown(result))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
