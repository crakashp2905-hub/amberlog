"""The background memory manager: the store maintains itself.

Every maintenance job already existed, and none of them ran unless someone
ran it. Retractions owed to other stores waited for a person to run the
dispatcher. Retention waited for `retention --apply`. The auditor's findings
waited for someone to scan. A store that needs a person to remember these
is not governed between visits.

`MemoryManager` runs them on its own, on an interval:

| task | what it does | bounded by |
|---|---|---|
| `dispatch` | delivers owed retractions to peer stores and retries failed ones | the outbox's own retry and backoff; needs a peer list |
| `retention` | applies the store's retention policy | the policy in force. **Deprecations** are applied; **deletions** (terminal) only with `allow_delete`, otherwise they are reported as waiting |
| `audit` | scans what changed since the last cycle for the auditor's triggers | read-only |
| `conflicts` | finds active memories that contradict each other (`conflicts.py`) | read-only: queued for review, never resolved |
| `checkpoint` | records the integrity chain head, and writes it outside the store if a directory is configured | append-only |
| `health` | runs the doctor's checks | read-only |

**Autonomous, and no further than its brief.**

- **It starts by itself.** `serve`, `agent-api` and `mcp` start it unless
  told not to, and `memory-fabric maintain` runs it on its own.
- **It recovers by itself.** Each task is isolated, so one failing never
  stops the others. A task that keeps failing backs off exponentially, up to
  32 cycles, and is retried.
- **It coordinates by itself.** It holds a lease (`ManagerLease`), taken and
  renewed inside a write transaction. So many processes can start a manager,
  but only one maintains a store at a time, and another takes over within a
  few intervals if the holder dies.
- **It records itself.** Every cycle is a `MaintenanceRan` event with what
  each task did or why it failed, and the doctor reports a manager that has
  stopped.
- **It takes no terminal step by default.** Retention's `delete` moves a
  memory to a state nothing leaves, so an unattended process applies it only
  when the owner opts in (`allow_delete`, `--retention-delete`). The first
  run of this manager, on a demo store, applied three deletions before this
  rule existed. It never resolves a contradiction, and never validates or
  releases. Those stay
  with people, through the review queue, which is where its findings go
  (`findings()`).
"""

from __future__ import annotations

__stability__ = "beta"

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from . import events as ev
from .ids import new_ulid

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric
    from .transport import Transport

TASKS = ("sources", "dispatch", "retention", "audit", "conflicts", "checkpoint", "health")
MAX_BACKOFF = 32


def load_peers(path: str | os.PathLike[str]) -> Any:
    """A `PeerRegistry` from a JSON file: [{store_id, endpoint, key_hex, key_id?}].

    The keys are secrets, so the file is read and never logged or printed.
    """
    from .transport import Peer, PeerRegistry

    registry = PeerRegistry()
    for row in json.loads(Path(path).read_text(encoding="utf-8")):
        registry.add(Peer(store_id=row["store_id"], endpoint=row["endpoint"],
                          key=bytes.fromhex(row["key_hex"]), key_id=row.get("key_id", "k1")))
    return registry


@dataclass
class TaskState:
    failures: int = 0
    skip_until_cycle: int = 0


@dataclass
class ManagerReport:
    leader: bool
    tasks: dict[str, Any] = field(default_factory=dict)


class MemoryManager:
    def __init__(self, fabric: "MemoryFabric", *, interval_s: float = 60.0,
                 transport: "Transport | None" = None, checkpoint_dir: str | None = None,
                 holder: str | None = None, clock: Callable[[], float] = time.time,
                 allow_delete: bool = False) -> None:
        self.fabric = fabric
        self.interval_s = interval_s
        self.transport = transport
        self.checkpoint_dir = checkpoint_dir
        self.holder = holder or f"manager-{os.getpid()}-{new_ulid()[-6:]}"
        self.clock = clock
        self.allow_delete = allow_delete
        self.cycle = 0
        self.state = {t: TaskState() for t in TASKS}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- leadership --------------------------------------------------------

    def _lease_ms(self) -> int:
        return int(self.interval_s * 3 * 1000)

    def acquire(self) -> bool:
        """Take or renew the lease, atomically. True when this manager leads."""
        fabric = self.fabric
        now = int(self.clock() * 1000)
        with fabric.lock, fabric._transaction():
            latest = None
            for event in fabric.log.read_types([ev.EventType.MANAGER_LEASE]):
                latest = event.payload
            if latest is not None and latest["holder"] != self.holder \
                    and int(latest["expires_ms"]) > now:
                return False
            fabric._emit(ev.manager_lease(ts=fabric.now(), holder=self.holder,
                                          expires_ms=now + self._lease_ms()))
        return True

    # --- one cycle -----------------------------------------------------------

    def _since(self) -> int:
        last = 0
        for event in self.fabric.log.read_types([ev.EventType.MAINTENANCE_RAN]):
            last = int(event.payload.get("until_seq", 0))
        return last

    def run_once(self) -> ManagerReport:
        # The whole cycle holds the store's lock. A server shares one database
        # connection between its request threads and this one, and parts of a
        # cycle read the log directly; unlocked, that is F1 again (concurrent
        # statements on one SQLite connection). Found when CI's MCP test
        # crashed at shutdown with the manager mid-call.
        with self.fabric.lock:
            return self._run_once_locked()

    def _run_once_locked(self) -> ManagerReport:
        if callable(getattr(self.fabric, "refresh", None)):
            self.fabric.refresh()
        if not self.acquire():
            return ManagerReport(leader=False)
        self.cycle += 1
        since = self._since()
        until = self.fabric.log.head_seq
        report: dict[str, Any] = {}
        for task in TASKS:
            st = self.state[task]
            if self.cycle < st.skip_until_cycle:
                report[task] = {"skipped": f"backing off after {st.failures} failure(s)"}
                continue
            try:
                report[task] = getattr(self, f"_task_{task}")(since)
                st.failures = 0
            except Exception as exc:  # noqa: BLE001 - one task never stops the others
                st.failures += 1
                st.skip_until_cycle = self.cycle + min(MAX_BACKOFF, 2 ** st.failures)
                report[task] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        self.fabric._emit(ev.maintenance_ran(ts=self.fabric.now(), holder=self.holder,
                                             since_seq=since, until_seq=until, tasks=report))
        return ManagerReport(leader=True, tasks=report)

    # --- tasks ---------------------------------------------------------------

    def _task_sources(self, since: int) -> dict[str, Any]:
        """Discredit sources the injection screens caught, and tell the peers holding their memories.

        Only the hostile signal, an ingest screen catching an injection, is
        acted on. T2 measured that discrediting on ordinary withdrawals
        punishes honest authors. A notice that cannot be delivered now is sent
        again next cycle: sending is idempotent at the recipient.
        """
        from .model import WithdrawalBasis

        caught: set[str] = set()
        for memory_id, basis in self.fabric.state.withdrawal_basis.items():
            memory = self.fabric.state.memories.get(memory_id)
            if memory is None or basis != WithdrawalBasis.SENSITIVE_DATA.value:
                continue
            reason = self._withdrawal_reason(memory_id)
            if "injection" in reason and not isinstance(memory.context.get("federation"), dict):
                caught.add(memory.provenance.created_by)
        sent, failed = 0, []
        for author in sorted(caught):
            notice = self.fabric.discredit_source(author, actor=self.holder)
            if self.transport is None or not hasattr(self.transport, "send_notice"):
                continue
            for peer in self.fabric.notice_recipients(author):
                try:
                    self.transport.send_notice(peer, notice)
                    sent += 1
                except Exception as exc:  # noqa: BLE001 - retried next cycle
                    failed.append(f"{peer}: {type(exc).__name__}")
        return {"discredited": sorted(caught), "notices_sent": sent, "failed": failed[:10]}

    def _withdrawal_reason(self, memory_id: str) -> str:
        reason = ""
        for event in self.fabric.log.read_types([ev.EventType.LIFECYCLE_CHANGED]):
            if event.payload.get("memory_id") == memory_id:
                reason = str(event.payload.get("reason") or "")
        return reason.lower()

    def _task_dispatch(self, since: int) -> dict[str, Any]:
        if self.transport is None:
            pending = len(self.fabric.outbox.pending())
            return {"skipped": "no peers configured", "pending": pending}
        from .dispatcher import Dispatcher

        result = Dispatcher(self.fabric, self.transport).run_once()
        return {k: v for k, v in getattr(result, "__dict__", {}).items()
                if isinstance(v, (int, float, str))}

    def _task_retention(self, since: int) -> dict[str, Any]:
        actions = {"deprecate", "delete"} if self.allow_delete else {"deprecate"}
        applied = self.fabric.sweep_retention(apply=True, actor=self.holder, actions=actions)
        waiting = [] if self.allow_delete else self.fabric.sweep_retention(
            apply=False, actions={"delete"})
        return {"applied": len(applied),
                "actions": sorted({d.action for d in applied}),
                "deletions_waiting_for_opt_in": len(waiting)}

    def _task_audit(self, since: int) -> dict[str, Any]:
        from .auditor import Auditor

        triggers = Auditor(self.fabric).scan(since_seq=since)
        return {"triggers": len(triggers),
                "items": [{"kind": t.kind, "subject": t.subject} for t in triggers[:50]]}

    def _task_conflicts(self, since: int) -> dict[str, Any]:
        from .conflicts import claim, find_conflicts
        from .model import LifecycleState

        active = [m for m in self.fabric.state.memories.values()
                  if m.lifecycle_state is LifecycleState.ACTIVE]
        new = {m.id for m in active if self.fabric.state.created_seq.get(m.id, 0) > since}
        by_identifier: dict[frozenset[str], list[Any]] = {}
        for m in active:
            ids = claim(m.content)[0]
            if ids:
                by_identifier.setdefault(ids, []).append(m)
        found = []
        for group in by_identifier.values():
            if len(group) < 2 or not any(m.id in new for m in group):
                continue
            for conflict in find_conflicts(group):
                if any(m.id in new for m in conflict):
                    found.append(sorted(m.id for m in conflict))
        return {"conflicts": len(found), "items": found[:50]}

    def _task_checkpoint(self, since: int) -> dict[str, Any]:
        cp = self.fabric.log.chain.checkpoint()
        out: dict[str, Any] = {"seq": cp.seq, "chain_digest": cp.chain_digest}
        if self.checkpoint_dir:
            directory = Path(self.checkpoint_dir)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{self.fabric.store_id}.checkpoint.jsonl"
            with target.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({**cp.to_json(), "at_ms": int(self.clock() * 1000)}) + "\n")
            out["written_to"] = str(target)
        return out

    def _task_health(self, since: int) -> dict[str, Any]:
        from .cli import DOCTOR_CHECKS

        levels: dict[str, int] = {}
        problems = []
        for check in DOCTOR_CHECKS:
            if getattr(check, "__name__", "") == "_check_manager":
                continue  # the manager does not grade itself
            finding = check(self.fabric)
            level = getattr(finding, "status", "ok")
            levels[level] = levels.get(level, 0) + 1
            if level != "ok":
                problems.append(getattr(finding, "name", "?"))
        return {"levels": levels, "problems": problems}

    # --- running on its own --------------------------------------------------

    def start(self) -> "MemoryManager":
        """Run in the background until `stop()` or process exit."""
        if self._thread is not None and self._thread.is_alive():
            return self

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.run_once()
                except Exception:  # noqa: BLE001 - the loop itself must never die
                    pass
                self._stop.wait(self.interval_s)

        self._thread = threading.Thread(target=loop, name="memory-manager", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)


def last_run(fabric: "MemoryFabric") -> Mapping[str, Any] | None:
    """The latest `MaintenanceRan` payload with its timestamp, or None if none ever ran."""
    out = None
    for event in fabric.log.read_types([ev.EventType.MAINTENANCE_RAN]):
        out = {**event.payload, "ts": event.ts, "holder": event.agent_id}
    return out


def findings(fabric: "MemoryFabric") -> list[dict[str, Any]]:
    """What the latest cycle found that needs a person: conflicts, audit triggers, health."""
    run = last_run(fabric)
    if run is None:
        return []
    tasks = run.get("tasks", {})
    out: list[dict[str, Any]] = []
    for ids in (tasks.get("conflicts") or {}).get("items", []):
        out.append({"kind": "conflict", "memory_ids": ids,
                    "why": "these memories give different values for the same claim"})
    for item in (tasks.get("audit") or {}).get("items", []):
        out.append({"kind": f"audit:{item['kind']}", "subject": item["subject"]})
    for name in (tasks.get("health") or {}).get("problems", []):
        out.append({"kind": "health", "check": name})
    return out
