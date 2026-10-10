"""The shared read model: plain data, no formatting, no side effects.

Every function here is read-only. That is a hard requirement rather than a
convention: an observability tool that logs exposure events while an operator
browses would contaminate the very data the value estimates are computed from.
`preview_search` therefore goes to the index directly instead of through
`fabric.retrieve`, which would write `ExposureDecided` events.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable

from ..governance.sensitive import scrub, scrub_tree, secret_values
from ..model import (
    BLOCKED_STATES,
    SCHEMA_VERSION,
    EXPOSABLE_STATES,
    LifecycleState,
    MemoryType,
    Scope,
    SecurityClass,
    WEAK_BASES,
    WithdrawalBasis,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..fabric import MemoryFabric

PREVIEW_CHARS = 140


def jsonable(value: Any) -> Any:
    """Make a payload strictly valid JSON.

    An unknown value estimate carries infinite bounds, and `json.dumps` writes
    those as `Infinity` / `-Infinity` / `NaN`. Python reads them back happily,
    so a round-trip test never notices, but they are not valid JSON and
    `JSON.parse` rejects the whole document — which takes out every non-Python
    client, the dashboard included. Non-finite floats become null, which is what
    "no estimate" should have serialised to in the first place.

    Callers pair this with `allow_nan=False` so the invalid form can never be
    emitted silently again.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def iso(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


def safe_content(fabric: "MemoryFabric", text: str) -> tuple[str, list[str]]:
    """Redact secrets before content leaves for a screen.

    Quarantining a memory because it holds a credential, and then printing that
    credential in the review tool, would defeat the control that caught it: the
    secret would reach a terminal scrollback, a browser's memory and any
    screenshot of either. The reviewer needs to know *what kind* of secret is in
    there to decide what to do, not its value.

    The raw content is still in the store for anyone who genuinely needs it; it
    just is not what the observability surfaces hand out by default.
    """
    found = secret_values(fabric.firewall.detector, text)
    if not found:
        return text, []
    return scrub(text, found), sorted({kind for _, kind in found})


# --- rows -------------------------------------------------------------------


@dataclass
class MemoryRow:
    id: str
    type: str
    lifecycle_state: str
    scope: str
    tenant_id: str
    security_class: str
    content: str
    created_at: str | None
    created_by: str
    method: str
    version: int
    exposures: int
    withholdings: int
    citations: int
    value_mean: float | None
    value_n_eff: float
    value_contrastive: bool
    value_estimator: str
    parents: int
    children: int
    hypothesis_set: str | None
    context: dict[str, Any]
    capabilities: list[str]
    redacted_kinds: list[str] = field(default_factory=list)
    # What kind of evidence the last withdrawal rested on, or None if this
    # memory has never been withdrawn. Both surfaces read it from here, so the
    # CLI and the dashboard cannot tell different stories about it.
    withdrawal_basis: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AttentionItem:
    """Something a human should look at, with the command that acts on it.

    The suggested command is the part that makes the gate reachable: a reader who
    has never seen this codebase should be able to go from "this looks wrong" to
    doing something about it without asking anyone.
    """

    severity: str  # "high" | "medium" | "low"
    kind: str
    title: str
    detail: str
    action: str
    memory_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Overview:
    path: str
    events: int
    total_memories: int
    by_state: dict[str, int]
    by_scope: dict[str, int]
    by_type: dict[str, int]
    episodes: int
    episodes_with_outcome: int
    exposures: int
    withholdings: int
    never_exposed: int
    no_value_evidence: int
    contrastive_evidence: int
    open_hypothesis_sets: int
    oldest_memory: str | None
    newest_memory: str | None
    estimator: str
    configured_policy: str
    configured_policy_declares_overlap: bool
    # Derived from the log rather than from configuration: what actually
    # produced the data, which is the only thing that governs what can be
    # concluded from it.
    logged_policies: list[str] = field(default_factory=list)
    randomised_exposures: int = 0
    memories_with_both_arms: int = 0
    # The installed package's schema version, and every version that actually
    # wrote into this log. They differ whenever a store outlives an upgrade,
    # and the answer to "can this build read my log?" is the comparison.
    schema_version: str = SCHEMA_VERSION
    log_schema_versions: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LineageNodeView:
    id: str
    content: str
    lifecycle_state: str
    type: str
    depth: int
    truncated: bool = False
    children: list["LineageNodeView"] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "lifecycle_state": self.lifecycle_state,
            "type": self.type,
            "depth": self.depth,
            "truncated": self.truncated,
            "children": [c.to_json() for c in self.children],
        }


@dataclass
class SearchHit:
    id: str
    relevance: float
    content: str
    lifecycle_state: str
    retrievable: bool

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# --- builders ---------------------------------------------------------------


def _row(fabric: "MemoryFabric", memory_id: str) -> MemoryRow:
    memory = fabric.get(memory_id)
    stats = fabric.stats(memory_id)
    value = fabric.value(memory_id)
    state = fabric.state
    content, redacted = safe_content(fabric, memory.content)
    return MemoryRow(
        id=memory.id,
        type=memory.type.value,
        lifecycle_state=memory.lifecycle_state.value,
        scope=memory.scope.value,
        tenant_id=memory.tenant_id,
        security_class=memory.security_class.value,
        content=preview(content),
        redacted_kinds=redacted,
        created_at=iso(memory.created_at),
        created_by=memory.provenance.created_by,
        method=memory.provenance.method.value,
        version=memory.version,
        exposures=stats.exposures,
        withholdings=stats.withholdings,
        citations=stats.citations,
        value_mean=None if value.n_eff <= 0.0 else value.mean,
        value_n_eff=value.n_eff,
        value_contrastive=value.contrastive,
        value_estimator=value.estimator,
        parents=len(state.parents.get(memory.id, ())),
        children=len(state.children.get(memory.id, ())),
        hypothesis_set=memory.hypothesis_set,
        withdrawal_basis=state.withdrawal_basis.get(memory.id),
        context=dict(memory.context),
        capabilities=list(memory.capabilities),
    )


def memory_rows(
    fabric: "MemoryFabric",
    state: str | None = None,
    scope: str | None = None,
    type: str | None = None,
    query: str | None = None,
    limit: int | None = None,
    sort: str = "created",
    tenant: str | None = None,
) -> list[MemoryRow]:
    """Filtered listing. `query` is a substring match on content, not retrieval:
    listing must never depend on the embedder or touch the exposure log."""
    rows = [_row(fabric, memory_id) for memory_id in fabric.state.memories]

    if state:
        rows = [r for r in rows if r.lifecycle_state == state]
    if scope:
        rows = [r for r in rows if r.scope == scope]
    if tenant:
        rows = [r for r in rows if r.tenant_id == tenant]
    if type:
        rows = [r for r in rows if r.type == type]
    if query:
        needle = query.lower()
        rows = [r for r in rows if needle in r.content.lower() or needle in r.id.lower()]

    keys = {
        "created": lambda r: (r.created_at or "", r.id),
        "exposures": lambda r: (-r.exposures, r.id),
        "value": lambda r: (-(r.value_mean if r.value_mean is not None else -1e9), r.id),
        "state": lambda r: (r.lifecycle_state, r.id),
    }
    rows.sort(key=keys.get(sort, keys["created"]), reverse=sort == "created")
    return rows[:limit] if limit else rows


def overview(fabric: "MemoryFabric") -> Overview:
    health = fabric.health()
    state = fabric.state

    created = [m.created_at for m in state.memories.values() if m.created_at]
    contrastive = sum(
        1
        for memory_id in state.memories
        if (v := fabric.value(memory_id)).n_eff > 0.0 and v.contrastive
    )
    exposures = sum(1 for e in state.exposures if e.exposed)
    withholdings = sum(1 for e in state.exposures if not e.exposed)

    # What the log says, not what this process is configured to do. The exposure
    # policy is runtime configuration and is never persisted, so a reader's own
    # settings say nothing about how the stored data was produced.
    logged_policies = sorted({e.policy_id for e in state.exposures if e.policy_id})
    randomised = sum(1 for e in state.exposures if 0.0 < e.propensity < 1.0)

    outcomes = {
        episode_id
        for episode_id, episode in state.episodes.items()
        if episode.has_outcome and episode.verifier_id
    }
    arms: dict[str, set[bool]] = {}
    for record in state.exposures:
        if record.episode_id in outcomes:
            arms.setdefault(record.memory_id, set()).add(record.exposed)
    both_arms = sum(1 for seen in arms.values() if len(seen) == 2)

    report = Overview(
        path=fabric.log.path,
        events=health.events,
        total_memories=health.total,
        by_state=health.by_state,
        by_scope=health.by_scope,
        by_type=health.by_type,
        episodes=health.episodes,
        episodes_with_outcome=health.episodes_with_outcome,
        exposures=exposures,
        withholdings=withholdings,
        never_exposed=health.never_exposed,
        no_value_evidence=health.unverified,
        contrastive_evidence=contrastive,
        open_hypothesis_sets=health.open_hypothesis_sets,
        oldest_memory=iso(min(created)) if created else None,
        newest_memory=iso(max(created)) if created else None,
        estimator=fabric.estimator.id,
        configured_policy=fabric.policy.id,
        configured_policy_declares_overlap=bool(
            getattr(fabric.policy, "declares_overlap", False)
        ),
        logged_policies=logged_policies,
        randomised_exposures=randomised,
        memories_with_both_arms=both_arms,
        schema_version=SCHEMA_VERSION,
        log_schema_versions=fabric.log.schema_versions(),
        diagnostics=[],
    )
    report.diagnostics = _diagnostics(report)
    return report


def _version(text: str) -> tuple[int, ...]:
    """Compare versions numerically, because "0.10.0" sorts before "0.2.0" as a
    string and a reader told its log is older than it is would act on the wrong
    figures. Anything unparseable sorts lowest, which errs toward warning."""
    parts = []
    for piece in text.split("."):
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _diagnostics(report: Overview) -> list[str]:
    """Whether this store can answer value questions at all.

    Stated at the top level rather than buried per memory, because the usual
    honest answer for a new deployment is "not yet, and here is what is missing".
    A dashboard that showed value numbers without saying so would be inviting
    the reader to trust a correlation.
    """
    notes: list[str] = []

    if report.episodes == 0:
        notes.append(
            "No episodes recorded. Value cannot be estimated until work is run through "
            "start_episode / retrieve / record_outcome."
        )
    elif report.episodes_with_outcome == 0:
        notes.append(
            f"{report.episodes} episode(s) but no verified outcomes. Value estimation needs "
            "record_outcome() with a third-party verifier_id."
        )
    elif report.episodes_with_outcome < report.episodes:
        missing = report.episodes - report.episodes_with_outcome
        notes.append(
            f"{missing} of {report.episodes} episodes have no verified outcome and are "
            "excluded from value estimates."
        )

    if report.exposures + report.withholdings == 0:
        notes.append("No exposure decisions logged yet, so no memory has any evidence behind it.")
    elif report.randomised_exposures == 0:
        policies = ", ".join(report.logged_policies) or "unknown"
        notes.append(
            f"Every logged exposure decision was deterministic (policies: {policies}). "
            "This data cannot support causal value estimates however much of it accumulates, "
            "because there is no way to tell a memory helping from it being retrieved on "
            "easier tasks. Collect new data under an epsilon_greedy policy to create overlap."
        )

    if report.withholdings == 0 and report.exposures > 0:
        notes.append(
            "No memory has ever been withheld, so there is no comparison group: any value "
            "figure reflects which memories were retrieved, not what they contributed."
        )
    elif report.memories_with_both_arms == 0 and report.exposures > 0:
        notes.append(
            "No single memory has been both exposed and withheld across episodes with "
            "verified outcomes, so none has a comparison group of its own yet."
        )

    if not report.configured_policy_declares_overlap and report.randomised_exposures > 0:
        notes.append(
            f"Historic data contains randomised exposures, but this session's policy "
            f"({report.configured_policy}) is deterministic, so new episodes will not add to it."
        )

    newer = [v for v in report.log_schema_versions if _version(v) > _version(report.schema_version)]
    if newer:
        notes.append(
            f"This log contains events written by schema {', '.join(newer)}, newer than the "
            f"installed {report.schema_version}. Projections ignore events they do not "
            "recognise, so the figures above may be incomplete. Upgrade before acting on them."
        )

    if report.contrastive_evidence == 0 and report.total_memories > 0:
        notes.append(
            "No memory has contrastive value evidence, so none can be promoted beyond "
            "private scope by the firewall."
        )
    return notes


def propagation_rows(fabric: "MemoryFabric") -> list[dict[str, Any]]:
    """Retractions still in flight, with the state of each recipient.

    Invariant 9 requires offline, pending, unknown and failed to be *explicit*.
    The rows carry the state verbatim from the outbox rather than collapsing it
    to a health colour, because "we have not heard from this recipient" and
    "this recipient confirmed enforcement" are the two answers an operator most
    needs to keep apart.
    """
    rows: list[dict[str, Any]] = []
    for row in fabric.outbox.pending():
        acks = fabric.outbox.acknowledgements(row.retraction_id)
        ack = acks.get(row.recipient)
        rows.append(
            {
                "retraction_id": row.retraction_id,
                "recipient": row.recipient,
                "state": row.state.value,
                "attempts": row.attempts,
                "last_error": row.last_error,
                "origin_memory_id": row.retraction.origin_memory_id,
                "origin_memory_version": row.retraction.origin_memory_version,
                "reason_code": row.retraction.reason_code,
                "acknowledged_state": None if ack is None else ack.state.value,
                "acknowledged_at": None if ack is None else ack.at,
            }
        )
    return rows


def attention(fabric: "MemoryFabric") -> list[AttentionItem]:
    """The triage list: what needs a human, worst first."""
    items: list[AttentionItem] = []
    state = fabric.state

    for memory in state.memories.values():
        safe, redacted = safe_content(fabric, memory.content)
        short = preview(safe, 80)
        if redacted:
            short += f"\nContains {', '.join(redacted)}; the value is hidden here."

        if memory.lifecycle_state is LifecycleState.QUARANTINED:
            basis = fabric.state.withdrawal_basis.get(
                memory.id, WithdrawalBasis.UNSTATED.value
            )
            weak = basis in {b.value for b in WEAK_BASES}
            detail = (
                f"{short}\nNot exposed to any agent. Review, then release or forget it."
                f"\nWithdrawn on: {basis}."
            )
            if weak:
                # The withdrawal is the thing under suspicion here, not the
                # memory. Phase A measured this basis cutting the rate at which
                # a *correct* memory reached the prompt from 60% of episodes to
                # 18%, because actions are shared between situations and the
                # memory that agreed with a mistake usually had nothing to do
                # with causing it.
                detail += (
                    "\nThat basis does not support a withdrawal on its own: being "
                    "present when something failed is agreement, not causation, and "
                    "this rule was measured removing more correct memory than wrong. "
                    "Release it unless there is evidence about the memory itself."
                )
            items.append(
                AttentionItem(
                    severity="high",
                    kind="withdrawn_on_weak_evidence" if weak else "quarantined",
                    title=(
                        "Withdrawn on weak evidence"
                        if weak
                        else "Quarantined, pending review"
                    ),
                    detail=detail,
                    action=(
                        f"memory-fabric release {memory.id} --actor you"
                        if weak
                        else f"memory-fabric show {memory.id}"
                    ),
                    memory_id=memory.id,
                )
            )
        elif memory.lifecycle_state is LifecycleState.CONTESTED:
            if memory.hypothesis_set:
                items.append(
                    AttentionItem(
                        severity="medium",
                        kind="disagreement",
                        title=f"Contested by disagreement ({memory.hypothesis_set})",
                        detail=f"{short}\nA conflicting memory exists. Resolve it with evidence, "
                        "not by picking a side.",
                        action=f"memory-fabric lineage {memory.id}",
                        memory_id=memory.id,
                    )
                )
            else:
                items.append(
                    AttentionItem(
                        severity="high",
                        kind="retracted_ancestor",
                        title="Justification retracted",
                        detail=f"{short}\nAn ancestor was quarantined, so this no longer rests on "
                        "anything. Re-check it against whatever replaced its source.",
                        action=f"memory-fabric lineage {memory.id} --direction ancestors",
                        memory_id=memory.id,
                    )
                )

        if (
            memory.scope is not Scope.PRIVATE
            and memory.security_class is SecurityClass.RESTRICTED
        ):
            items.append(
                AttentionItem(
                    severity="high",
                    kind="restricted_shared",
                    title="Restricted memory outside private scope",
                    detail=f"{short}\nThis should not have left private scope.",
                    action=f"memory-fabric audit {memory.id}",
                    memory_id=memory.id,
                )
            )

    for hset in state.hypothesis_sets.values():
        if not hset.resolved:
            members = sorted(hset.memory_ids)
            items.append(
                AttentionItem(
                    severity="medium",
                    kind="open_hypothesis_set",
                    title=f"Unresolved disagreement: {hset.id}",
                    detail=f"{len(members)} competing memories, none deleted. "
                    "Design an experiment rather than choosing a winner.",
                    action=f"memory-fabric show {members[0]}",
                    memory_id=members[0],
                )
            )

    for decision in retention_preview(fabric):
        items.append(
            AttentionItem(
                severity="low",
                kind=f"retention_{decision['action']}",
                title=f"Retention would {decision['action']} this memory",
                detail=decision["reason"],
                action="memory-fabric retention --apply",
                memory_id=decision["memory_id"],
            )
        )

    items.sort(key=lambda i: (_SEVERITY_ORDER.get(i.severity, 9), i.kind, i.memory_id or ""))
    return items


def retention_preview(fabric: "MemoryFabric") -> list[dict[str, Any]]:
    """Dry-run retention. Never applies anything."""
    return [
        {"memory_id": d.memory_id, "action": d.action, "reason": d.reason}
        for d in fabric.sweep_retention(apply=False)
    ]


def lineage_tree(
    fabric: "MemoryFabric",
    memory_id: str,
    direction: str = "descendants",
    max_depth: int = 6,
) -> LineageNodeView:
    """Nested derivation tree, in either direction.

    `LineageGraph` returns flat lists with depths, which suits set operations
    like "the retraction set" but not display. This walks the edges directly.
    """
    if direction not in ("descendants", "ancestors"):
        raise ValueError("direction must be 'descendants' or 'ancestors'")
    edges = fabric.state.children if direction == "descendants" else fabric.state.parents

    def build(current: str, depth: int, seen: frozenset[str]) -> LineageNodeView:
        memory = fabric.get(current)
        node = LineageNodeView(
            id=current,
            content=preview(safe_content(fabric, memory.content)[0], 90),
            lifecycle_state=memory.lifecycle_state.value,
            type=memory.type.value,
            depth=depth,
        )
        neighbours = sorted(edges.get(current, ()))
        if depth >= max_depth:
            node.truncated = bool(neighbours)
            return node
        for neighbour in neighbours:
            # `seen` guards against a malformed log rather than trusting that
            # provenance edges are acyclic.
            if neighbour in seen or neighbour not in fabric.state.memories:
                continue
            node.children.append(build(neighbour, depth + 1, seen | {neighbour}))
        return node

    return build(memory_id, 0, frozenset({memory_id}))


def memory_detail(fabric: "MemoryFabric", memory_id: str) -> dict[str, Any]:
    """Everything one memory's page shows."""
    explanation = fabric.explain(memory_id)
    memory = fabric.get(memory_id)
    # One set of values, scrubbed from every derived string below. The
    # explanation payload re-embeds the raw memory, so scrubbing only
    # `full_content` would leave the secret sitting in the response.
    found = secret_values(fabric.firewall.detector, memory.content)
    redacted = sorted({kind for _, kind in found})
    return {
        "row": _row(fabric, memory_id).to_json(),
        "explanation": scrub_tree(explanation.to_json(), found),
        "narrative": scrub(explanation.narrative(), found),
        "descendants": lineage_tree(fabric, memory_id, "descendants").to_json(),
        "ancestors": lineage_tree(fabric, memory_id, "ancestors").to_json(),
        "versions": [
            {
                "version": m.version,
                "content": safe_content(fabric, m.content)[0],
                "created_at": iso(m.created_at),
            }
            for m in fabric.history(memory_id)
        ],
        "audit": [
            {
                "seq": e.seq,
                "type": e.type,
                "ts": iso(e.ts),
                "agent_id": e.agent_id,
                "episode_id": e.episode_id,
                "payload": _audit_payload(e.payload),
            }
            for e in fabric.audit_trail(memory_id)
        ],
        "full_content": scrub(memory.content, found),
        "redacted_kinds": redacted,
        "structured": dict(memory.structured) if memory.structured else None,
    }


def _audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop the embedded memory snapshot from audit rows.

    A `MemoryCreated` payload contains the whole memory, which would repeat the
    content on every row and bury the fields that explain what changed.
    """
    return {k: v for k, v in payload.items() if k not in ("memory", "candidates")}


def episode_rows(fabric: "MemoryFabric", limit: int | None = None) -> list[dict[str, Any]]:
    episodes = sorted(
        fabric.state.episodes.values(), key=lambda e: e.started_at, reverse=True
    )
    exposures_by_episode: dict[str, int] = {}
    for record in fabric.state.exposures:
        if record.episode_id and record.exposed:
            exposures_by_episode[record.episode_id] = (
                exposures_by_episode.get(record.episode_id, 0) + 1
            )
    rows = [
        {
            "id": episode.id,
            "agent_id": episode.agent_id,
            "task_id": episode.task_id,
            "context": dict(episode.context),
            "started_at": iso(episode.started_at),
            "outcome": episode.outcome,
            "verifier_id": episode.verifier_id,
            "exposures": exposures_by_episode.get(episode.id, 0),
        }
        for episode in episodes
    ]
    return rows[:limit] if limit else rows


def preview_search(
    fabric: "MemoryFabric", query: str, k: int = 10, all_states: bool = True
) -> list[SearchHit]:
    """Search without logging anything.

    Deliberately does not call `fabric.retrieve`. That would write
    `ExposureDecided` events and quietly enter an operator's browsing into the
    data every value estimate is computed from.
    """
    restrict = None
    if not all_states:
        restrict = {
            memory_id
            for memory_id, memory in fabric.state.memories.items()
            if memory.lifecycle_state in EXPOSABLE_STATES
        }
    hits = fabric.index.search(query, k=k, restrict_to=restrict)
    out: list[SearchHit] = []
    for memory_id, score in hits:
        memory = fabric.state.memories.get(memory_id)
        if memory is None:
            continue
        out.append(
            SearchHit(
                id=memory_id,
                relevance=score,
                content=preview(safe_content(fabric, memory.content)[0]),
                lifecycle_state=memory.lifecycle_state.value,
                retrievable=memory.lifecycle_state in EXPOSABLE_STATES
                and memory.lifecycle_state not in BLOCKED_STATES,
            )
        )
    return out


def enum_values() -> dict[str, list[str]]:
    """Filter options, so both surfaces offer exactly the same ones."""
    return {
        "lifecycle_state": [s.value for s in LifecycleState],
        "scope": [s.value for s in Scope],
        "type": [t.value for t in MemoryType],
        "security_class": [s.value for s in SecurityClass],
    }
