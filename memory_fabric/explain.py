"""The provenance answer: "why does the system remember this?"

This is the product's lead capability (CRITICAL_REVIEW section 11). It needs no
outcome signal, so it works in every deployment, and it answers the question
compliance teams already ask.

The trace is assembled from the event log rather than from a summary field, so it
cannot drift out of step with what actually happened.
"""

from __future__ import annotations

__stability__ = "stable"

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .events import EventType
from .governance.sensitive import scrub, secret_values
from .model import (
    WEAK_BASES,
    LifecycleState,
    Memory,
    ValueEstimate,
    WithdrawalBasis,
)

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric


@dataclass
class TraceStep:
    kind: str
    ts: int
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


@dataclass
class Explanation:
    memory_id: str
    memory: Memory
    value: ValueEstimate
    created_by: str
    method: str
    source_episodes: list[str] = field(default_factory=list)
    root_memories: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    supports: list[str] = field(default_factory=list)
    versions: int = 1
    exposures: int = 0
    withholdings: int = 0
    citations: int = 0
    contested_with: list[str] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    redacted_kinds: list[str] = field(default_factory=list)

    def narrative(self) -> str:
        """Plain-language rendering, for a dashboard panel or a CLI."""
        memory = self.memory
        lines: list[str] = [
            f"Memory {self.memory_id} (v{memory.version}, {memory.type.value})",
            f'  "{_truncate(memory.content, 200)}"',
            "",
            f"  State:      {memory.lifecycle_state.value} / scope {memory.scope.value}"
            f" / {memory.security_class.value}",
            f"  Created by: {self.created_by} ({self.method})",
        ]
        if self.source_episodes:
            lines.append(f"  From episodes: {', '.join(self.source_episodes)}")
        if self.derived_from:
            lines.append(f"  Derived from:  {', '.join(self.derived_from)}")
        if self.root_memories and self.root_memories != [self.memory_id]:
            lines.append(f"  Traces back to: {', '.join(self.root_memories)}")
        if self.supports:
            lines.append(f"  Supports:      {', '.join(self.supports)}")

        lines += [
            "",
            f"  Exposed {self.exposures}x, withheld {self.withholdings}x,"
            f" cited {self.citations}x, {self.versions} version(s)",
            f"  Value: {_format_value(self.value)}",
        ]
        if self.contested_with:
            lines.append(f"  Contested against: {', '.join(self.contested_with)}")
        if self.redacted_kinds:
            lines.append("")
            lines.append(
                f"  Secrets redacted for display: {', '.join(self.redacted_kinds)}. "
                "The stored value is unchanged."
            )
        if self.caveats:
            lines.append("")
            lines.append("  Caveats:")
            lines.extend(f"    - {c}" for c in self.caveats)
        if self.trace:
            lines.append("")
            lines.append("  History:")
            lines.extend(f"    {step}" for step in self.trace)
        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "memory": self.memory.to_json(),
            "value": self.value.to_json(),
            "created_by": self.created_by,
            "method": self.method,
            "source_episodes": self.source_episodes,
            "root_memories": self.root_memories,
            "derived_from": self.derived_from,
            "supports": self.supports,
            "versions": self.versions,
            "exposures": self.exposures,
            "withholdings": self.withholdings,
            "citations": self.citations,
            "contested_with": self.contested_with,
            "redacted_kinds": self.redacted_kinds,
            "caveats": self.caveats,
            "trace": [{"kind": s.kind, "ts": s.ts, "detail": s.detail} for s in self.trace],
        }

    def __str__(self) -> str:
        return self.narrative()


def explain_memory(fabric: "MemoryFabric", memory_id: str) -> Explanation:
    memory = fabric.get(memory_id)
    stats = fabric.stats(memory_id)
    lineage = fabric.lineage(memory_id)
    graph = fabric.lineage_graph

    hset = (
        fabric.state.hypothesis_sets.get(memory.hypothesis_set)
        if memory.hypothesis_set
        else None
    )
    contested_with = sorted(hset.memory_ids - {memory_id}) if hset else []

    # One source of truth for the value shown and the caveats about it. Reading
    # the live estimate in the header and the projected one in the caveats let
    # the two contradict each other.
    value = fabric.value(memory_id)

    # Redact here, not only in the dashboard. An explanation is a display
    # surface too: printing one to a terminal used to show the credential the
    # firewall had just quarantined the memory for containing.
    secrets = secret_values(fabric.firewall.detector, memory.content)
    redacted_kinds = sorted({kind for _, kind in secrets})

    explanation = Explanation(
        memory_id=memory_id,
        memory=memory.evolve(content=scrub(memory.content, secrets)),
        value=value,
        redacted_kinds=redacted_kinds,
        created_by=memory.provenance.created_by,
        method=memory.provenance.method.value,
        source_episodes=list(memory.provenance.source_episodes),
        root_memories=graph.roots(memory_id),
        derived_from=[pid for pid, _ in memory.provenance.parents],
        supports=sorted(fabric.state.children.get(memory_id, ())),
        versions=lineage.versions,
        exposures=stats.exposures,
        withholdings=stats.withholdings,
        citations=stats.citations,
        contested_with=contested_with,
        trace=[
            TraceStep(s.kind, s.ts, scrub(s.detail, secrets))
            for s in _build_trace(fabric, memory_id)
        ],
        caveats=_build_caveats(fabric, memory, stats, value),
    )
    return explanation


def _build_trace(fabric: "MemoryFabric", memory_id: str) -> list[TraceStep]:
    """Readable history from the audit trail, skipping retrieval noise."""
    steps: list[TraceStep] = []
    for event in fabric.audit_trail(memory_id):
        payload = event.payload
        if event.type == EventType.MEMORY_CREATED:
            steps.append(TraceStep("created", event.ts, f"by {event.agent_id}"))
        elif event.type == EventType.MEMORY_VERSIONED:
            version = payload.get("memory", {}).get("version")
            steps.append(
                TraceStep("revised", event.ts, f"to v{version}: {payload.get('reason', '')}")
            )
        elif event.type == EventType.LIFECYCLE_CHANGED:
            steps.append(
                TraceStep(
                    "lifecycle",
                    event.ts,
                    f"{payload['from']} -> {payload['to']} by {payload['actor']}"
                    f" ({payload['reason']})",
                )
            )
        elif event.type == EventType.SCOPE_CHANGED:
            if payload["from"] == payload["to"]:
                steps.append(
                    TraceStep(
                        "share refused",
                        event.ts,
                        f"{payload['firewall_decision']}: {'; '.join(payload['reasons'])}",
                    )
                )
            else:
                steps.append(
                    TraceStep(
                        "scope",
                        event.ts,
                        f"{payload['from']} -> {payload['to']}"
                        f" ({payload['firewall_decision']})",
                    )
                )
        elif event.type == EventType.CONFLICT_DETECTED:
            others = [m for m in payload["memory_ids"] if m != memory_id]
            steps.append(
                TraceStep(
                    "conflict",
                    event.ts,
                    f"against {', '.join(others)} (detector {payload['detector_id']},"
                    f" confidence {payload['confidence']})",
                )
            )
        elif event.type == EventType.VALUE_ESTIMATED:
            estimate = payload["estimate"]
            steps.append(
                TraceStep(
                    "value",
                    event.ts,
                    f"{estimate['mean']:.3f} (n_eff {estimate['n_eff']:.1f},"
                    f" {payload['estimator_id']})",
                )
            )
    return steps


def _build_caveats(
    fabric: "MemoryFabric", memory: Memory, stats, value: ValueEstimate
) -> list[str]:
    """State what the trace does *not* establish.

    An explanation that omits its own limits is worse than no explanation,
    because it invites the reader to treat a correlation as a cause.
    """
    caveats: list[str] = []

    if value.n_eff <= 0.0:
        caveats.append("No value evidence: this memory has never been evaluated against outcomes.")
    elif value.n_eff < 10.0:
        caveats.append(
            f"Value rests on little evidence (n_eff {value.n_eff:.1f}); the interval is wide."
        )

    if value.n_eff > 0.0 and not value.contrastive:
        caveats.append(
            f"Estimator {value.estimator!r} is not contrastive: the figure is the average "
            "outcome of episodes where this memory was exposed, not the difference it made. "
            "It cannot show that the memory helped."
        )

    if not getattr(fabric.policy, "declares_overlap", False):
        caveats.append(
            f"Exposure policy {fabric.policy.id!r} is deterministic, so value figures are "
            "observational: they cannot separate this memory helping from it being "
            "retrieved on easier tasks."
        )

    if stats.citations and not value.n_eff:
        caveats.append(
            "Citations are self-reported by the agent and are not evidence of value."
        )

    if memory.lifecycle_state is LifecycleState.CONTESTED:
        # Contested has two distinct causes and they call for different actions:
        # a live disagreement needs evidence, a retracted ancestor needs the
        # derived claim re-checked against whatever replaced its source.
        if memory.hypothesis_set:
            caveats.append(
                "Contested: a conflicting memory exists and the question is unresolved."
            )
        else:
            caveats.append(
                "Contested: an ancestor this memory was derived from has been retracted, "
                "so its justification no longer holds and it needs re-checking."
            )
    if memory.lifecycle_state is LifecycleState.QUARANTINED:
        basis = fabric.state.withdrawal_basis.get(
            memory.id, WithdrawalBasis.UNSTATED.value
        )
        caveats.append(
            f"Quarantined on '{basis}': not exposed to agents, pending review."
        )
        if basis in {b.value for b in WEAK_BASES}:
            # "Why does the system remember this?" has to be answerable about a
            # withdrawal too, and the honest answer here is that the withdrawal
            # may be the error. Phase A measured this basis cutting the rate at
            # which a correct memory reached the prompt from 60% of episodes to
            # 18%.
            caveats.append(
                "That basis does not support a withdrawal on its own: presence at a "
                "failure is agreement, not causation, and the rule was measured "
                "removing more correct memory than wrong. This memory may have been "
                "withdrawn in error."
            )

    episodes_without_outcome = sum(
        1 for e in fabric.state.episodes.values() if not e.has_outcome
    )
    if episodes_without_outcome and value.n_eff > 0.0:
        caveats.append(
            f"{episodes_without_outcome} episode(s) have no verified outcome and are "
            "excluded from the value estimate."
        )
    return caveats


def _format_value(value: ValueEstimate) -> str:
    if value.n_eff <= 0.0:
        return "not yet estimated"
    return (
        f"{value.mean:+.3f} [{value.ci_low:+.3f}, {value.ci_high:+.3f}]"
        f" (n_eff {value.n_eff:.1f}, {value.estimator})"
    )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
