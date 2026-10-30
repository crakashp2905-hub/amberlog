"""The lifecycle and deletion center: what to keep, what to remove, what landed.

One view over four questions an administrator asks on a schedule, each finding
carrying the command that acts on it (the convention `attention` set):

- **rules**: the retention policy in force, and what a sweep would do now
  (a dry run; nothing is applied).
- **stale**: active memories nobody has been shown in `stale_days`, and
  candidates that have waited longer than the policy allows for review.
- **sensitive**: memories quarantined for a secret whose content is still
  readable (the key was never destroyed), and memories that the screens as
  they are *now* would quarantine -- screens improve, and a memory written
  before an improvement was never checked by it.
- **deletions**: what has been erased, by whom, and, for erased or withdrawn
  memories that had been sent to other stores, what each store acknowledged.

Read-only: it runs no sweep, erases nothing and sends nothing.
"""

from __future__ import annotations

__stability__ = "beta"

import time
from typing import TYPE_CHECKING, Any

from .events import EventType
from .governance.erasure import ERASED_MARKER
from .model import FirewallDecision, LifecycleState, WithdrawalBasis

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

DAY_MS = 86_400_000


def center(fabric: "MemoryFabric", stale_days: int = 90, now_ms: int | None = None) -> dict[str, Any]:
    from .correction import status as retraction_status
    from .observability.report import retention_preview

    now = now_ms if now_ms is not None else int(time.time() * 1000)
    state = fabric.state
    policy = fabric.retention
    last_seen: dict[str, int] = {}
    for record in state.exposures:
        if record.exposed:
            last_seen[record.memory_id] = max(last_seen.get(record.memory_id, 0), record.ts)

    stale, waiting = [], []
    for memory in state.memories.values():
        age = now - (memory.created_at or now)
        if memory.lifecycle_state is LifecycleState.ACTIVE:
            seen = last_seen.get(memory.id)
            idle = now - (seen if seen is not None else (memory.created_at or now))
            if idle > stale_days * DAY_MS:
                stale.append({"memory_id": memory.id, "idle_days": idle // DAY_MS,
                              "ever_shown": seen is not None,
                              "command": f"memory_fabric --db <store> forget {memory.id} "
                                         f"--reason stale --actor <you>"})
        elif memory.lifecycle_state is LifecycleState.CANDIDATE \
                and age > policy.unused_candidate_days * DAY_MS:
            waiting.append({"memory_id": memory.id, "waiting_days": age // DAY_MS,
                            "command": "memory_fabric --db <store> review"})

    readable_secrets, rescreened = [], []
    for memory in state.memories.values():
        if memory.content == ERASED_MARKER:
            continue
        basis = state.withdrawal_basis.get(memory.id)
        if memory.lifecycle_state is LifecycleState.QUARANTINED \
                and basis == WithdrawalBasis.SENSITIVE_DATA.value:
            readable_secrets.append({
                "memory_id": memory.id,
                "command": f"memory_fabric --db <store> erase {memory.id} "
                           f"--reason 'leaked credential' --actor <you>"})
        elif memory.lifecycle_state in (LifecycleState.ACTIVE, LifecycleState.CANDIDATE):
            ruling = fabric.firewall.screen_ingest(memory.content)
            if ruling.decision is FirewallDecision.QUARANTINE:
                rescreened.append({
                    "memory_id": memory.id, "finding": "; ".join(ruling.reasons),
                    "command": f"memory_fabric --db <store> quarantine {memory.id} "
                               f"--reason 'current screens flag it' --actor <you>"})

    erasures = []
    for event in fabric.log.read_types([EventType.CONTENT_ERASED]):
        erasures.append({"memory_id": event.payload.get("memory_id"), "actor": event.agent_id,
                         "ts": event.ts, "reason": event.payload.get("reason", "")})
    propagation = []
    for memory_id in sorted(state.shared_to):
        memory = state.memories.get(memory_id)
        if memory is None or memory.lifecycle_state is LifecycleState.ACTIVE:
            continue
        rows = retraction_status(fabric, memory_id)
        stores = sorted(state.shared_to[memory_id])
        reached = {r["store_id"] for r in rows if r["state"] in ("enforced", "verified")}
        propagation.append({"memory_id": memory_id, "stores": stores,
                            "confirmed": sorted(reached & set(stores)),
                            "outstanding": sorted(set(stores) - reached),
                            "command": f"memory_fabric --db <store> correct {memory_id} --status"})

    return {
        "rules": {"deprecated_grace_days": policy.deprecated_grace_days,
                  "quarantine_grace_days": policy.quarantine_grace_days,
                  "unused_candidate_days": policy.unused_candidate_days,
                  "protected_tags": sorted(policy.protected_tags),
                  "sweep_would": retention_preview(fabric)},
        "stale": stale, "waiting_for_review": waiting,
        "sensitive": {"readable_secrets": readable_secrets, "flagged_by_current_screens": rescreened},
        "deletions": {"erased": erasures, "propagation": propagation},
    }
