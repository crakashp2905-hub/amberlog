"""Retention: deciding what may be deleted, and protecting what must not be.

The rare-but-critical problem (CRITICAL_REVIEW section 2.5) lives here. A
memory that matters once a year never accumulates evidence, so any
frequency-based or credit-based rule deletes it. Retention therefore reasons
about expected value, P(situation) x impact, and keeps an explicit protected
class that no automatic rule may remove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..model import LifecycleState, Memory, MemoryStats, ValueEstimate

DAY_MS = 86_400_000


@dataclass
class RetentionDecision:
    memory_id: str
    action: str  # "keep" | "deprecate" | "delete"
    reason: str


@dataclass
class RetentionPolicy:
    """Time and evidence based, with protections that override both."""

    deprecated_grace_days: int = 30
    quarantine_grace_days: int = 90
    unused_candidate_days: int = 14
    protected_tags: frozenset[str] = frozenset({"protected", "critical", "rare"})
    min_impact_to_protect: float = 0.5

    # Memories whose ids are listed here are never deleted automatically.
    protected_ids: set[str] = field(default_factory=set)

    def is_protected(self, memory: Memory, stats: MemoryStats) -> tuple[bool, str]:
        if memory.id in self.protected_ids:
            return True, "explicitly protected"
        tags = {str(t) for t in (memory.context.get("tags") or ())}
        overlap = tags & self.protected_tags
        if overlap:
            return True, f"protected tag: {', '.join(sorted(overlap))}"
        impact = memory.context.get("impact")
        if isinstance(impact, (int, float)) and float(impact) >= self.min_impact_to_protect:
            # High impact times low frequency still deserves retention: the
            # rollback procedure you need once a year.
            return True, f"high stated impact {float(impact):.2f} despite low usage"
        return False, ""

    def decide(
        self, memory: Memory, stats: MemoryStats, now_ms: int
    ) -> RetentionDecision:
        protected, why = self.is_protected(memory, stats)
        if protected:
            return RetentionDecision(memory.id, "keep", why)

        if memory.created_at <= 0:
            # An unset creation time is a data problem, not an age of zero.
            # Treating it as "brand new" would quietly make the memory
            # immortal, so say so instead of guessing.
            return RetentionDecision(
                memory.id, "keep", "creation time unknown; cannot judge age"
            )

        age_days = (now_ms - memory.created_at) / DAY_MS
        state = memory.lifecycle_state

        if state is LifecycleState.DELETED:
            return RetentionDecision(memory.id, "keep", "already deleted")

        if state is LifecycleState.DEPRECATED and age_days >= self.deprecated_grace_days:
            return RetentionDecision(
                memory.id,
                "delete",
                f"deprecated and {age_days:.0f}d old (grace {self.deprecated_grace_days}d)",
            )

        if state is LifecycleState.QUARANTINED and age_days >= self.quarantine_grace_days:
            return RetentionDecision(
                memory.id,
                "delete",
                f"quarantined and {age_days:.0f}d old (grace {self.quarantine_grace_days}d)",
            )

        if (
            state is LifecycleState.CANDIDATE
            and stats.exposures == 0
            and age_days >= self.unused_candidate_days
        ):
            return RetentionDecision(
                memory.id,
                "deprecate",
                f"candidate never exposed in {age_days:.0f}d",
            )

        return RetentionDecision(memory.id, "keep", "within policy")

    def sweep(
        self,
        memories: Iterable[tuple[Memory, MemoryStats]],
        now_ms: int,
    ) -> list[RetentionDecision]:
        decisions = [self.decide(m, s, now_ms) for m, s in memories]
        return [d for d in decisions if d.action != "keep"]


def expected_value(probability: float, impact: float) -> float:
    """Retention ranks on this, not on observed retrieval frequency."""
    return probability * impact


# --- which value signal to rank retention on (H2, 2026-10-01) ---------------
#
# If you add value-ranked retention, rank on `naive_usage`, not on the
# propensity-corrected `amortized` estimator. That is counter-intuitive and is
# measured, not assumed: research/results/h2-credit-driven-retention.md.
#
# Amortized wins decisively on *rank correlation* with true value (H1: 0.76 vs
# 0.47) and still loses on retention (-0.012, interval through zero). Two
# reasons. Perfect knowledge of value only reaches 0.485 success against
# random's 0.352, and naive captures 93% of that; and harm is directly visible
# in the raw outcome, because a bad memory that gets followed produces
# failures, so the debiasing that wins on ordering buys little at the single
# threshold a budget decision actually asks about.
#
# Two things that measurement does *not* say:
#   - Ranking by retrieval frequency is worse than random and keeps only 9% of
#     rare-but-correct memories. Never fall back to "keep what is retrieved
#     most".
#   - Amortized preserved rare-but-correct memories far better than naive
#     (87% vs 61%). If rare knowledge matters more than mean success for your
#     store, that trade runs the other way.
RETENTION_VALUE_ESTIMATOR = "naive_usage"


def should_keep_for_rarity(
    value: ValueEstimate, probability: float, impact: float, threshold: float
) -> bool:
    """A memory with weak observed evidence is still worth keeping when the
    situation it covers is rare and costly."""
    if value.n_eff >= 10.0 and value.ci_high < 0.0:
        return False  # Solid evidence that it is harmful.
    return expected_value(probability, impact) >= threshold
