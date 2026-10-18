"""Phase 4 — truth maintenance: recompute support, do not assume its loss.

The roadmap's §4.2 requirement, and the question the whole project is ultimately
asked: *can a harmful belief be corrected without withdrawing unrelated useful
knowledge?*

Until now the answer was no, and the reason was one unconditional loop.
`quarantine(propagate=True)` marked **every** descendant contested, so a
conclusion resting on two independent premises was treated exactly like one
resting on a single invalidated premise. `LineageGraph.evidence_is_independent`
existed to tell them apart and nothing called it.

Three distinctions do the work here.

**A justification is a set, not an edge.** A conclusion derived from A *and* B
has one justification `{A, B}` that fails if either fails. A conclusion derived
from A, and separately from B, has two justifications that each stand alone.
Provenance records parents but not which of those two shapes it was, so the
`JustificationKind` on the edge says which — and the default is the safe
reading.

**Copies are not corroboration.** Two memories that share an ancestor are one
piece of evidence wearing two hats (SECURITY.md T3). `independent_support`
refuses to count them twice, which is why an imported copy of A does not keep a
conclusion alive when A is retracted.

**Recency is not truth.** A newer version does not outrank an older
justification; only evidence does. Nothing here consults a timestamp.
"""

from __future__ import annotations

__stability__ = "stable"

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from .model import WITHDRAWN_STATES, LifecycleState


class JustificationKind(str, Enum):
    """How a parent supports a child.

    The roadmap lists eight edge types; these are the four that change what
    happens when a premise is invalidated. The rest (`generalized_from`,
    `specialized_from`, `validated_by`, `supersedes`) are recorded by
    `ProvenanceMethod` on the memory and do not alter support recomputation, so
    adding them as edge kinds would be ceremony.
    """

    REQUIRED = "required"
    """Part of a conjunction: the conclusion needs *all* parents in its group.
    The default, because assuming independence when it was not stated is the
    unsafe direction — it would keep a conclusion alive on support that never
    existed."""

    ALTERNATIVE = "alternative"
    """An independent justification on its own. The conclusion survives the loss
    of any one `ALTERNATIVE` parent, provided another survives."""

    COPIED = "copied"
    """A copy or import of the parent. **Never counts as independent support**:
    it is the same evidence, relocated."""

    CONTRADICTS = "contradicts"
    """Recorded for inspection; carries no support at all."""


@dataclass(frozen=True)
class SupportVerdict:
    """What remains of a conclusion's support after a premise was invalidated."""

    memory_id: str
    surviving: tuple[str, ...]
    lost: tuple[str, ...]
    independent_count: int
    verdict: str
    reason: str

    @property
    def still_justified(self) -> bool:
        return self.verdict == "justified"

    def to_json(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "surviving": list(self.surviving),
            "lost": list(self.lost),
            "independent_count": self.independent_count,
            "verdict": self.verdict,
            "reason": self.reason,
        }


JUSTIFIED = "justified"
"""At least one independent justification survives. Leave the conclusion alone."""

CONTESTED = "contested"
"""Support is incomplete or disputed. The conclusion stays representable and is
marked, which is what AGENTS.md principle 6 requires — nothing is silently
erased."""

UNSUPPORTED = "unsupported"
"""Every justification failed. Still contested rather than deleted: a conclusion
whose premises were withdrawn may be true anyway, and the project has measured
what indiscriminate withdrawal costs."""


class JustificationGraph:
    """Support recomputation over the lineage graph."""

    def __init__(self, fabric: Any) -> None:
        self.fabric = fabric

    # --- edges -----------------------------------------------------------

    def kind_of(self, child: str, parent: str) -> JustificationKind:
        """The edge kind, read from the child's context.

        Stored on the child rather than in a separate table because an edge is
        created with the child and never without it, and a second table would
        be one more thing to keep consistent with the log.
        """
        memory = self.fabric.state.memories.get(child)
        if memory is None:
            return JustificationKind.REQUIRED
        kinds = memory.context.get("justifications") or {}
        raw = kinds.get(parent)
        if raw is None:
            # An import is a copy of its origin by construction, whatever the
            # caller said, so it can never be independent corroboration.
            from .federation import imported_from

            if imported_from(self.fabric, child) is not None:
                return JustificationKind.COPIED
            return JustificationKind.REQUIRED
        try:
            return JustificationKind(str(raw))
        except ValueError:
            return JustificationKind.REQUIRED

    def parents_of(self, memory_id: str) -> list[str]:
        return sorted(self.fabric.state.parents.get(memory_id, ()))

    def withdrawn_copies_of(self, memory_id: str) -> list[str]:
        """Members of this memory's copy component that are withdrawn."""
        closure = getattr(self.fabric, "_copy_closure", None)
        if closure is None:
            return []
        memories = self.fabric.state.memories
        return sorted(
            other for other in closure(memory_id)
            if other in memories
            and memories[other].lifecycle_state in WITHDRAWN_STATES
        )

    def parent_version(self, child: str, parent: str) -> int | None:
        """The exact parent version the child was derived from.

        Provenance always recorded it; before Phase 1 the projection discarded
        it. A conclusion derived from v2 is not supported by v3 having replaced
        it — that has to be re-checked, not assumed.
        """
        return self.fabric.state.parent_versions.get((child, parent))

    # --- support ---------------------------------------------------------

    def is_usable(self, memory_id: str) -> bool:
        """Whether a premise can carry support right now.

        Requires `ACTIVE`, matching the enforcement layer where only an active
        memory is usable. Three states are deliberately *not* support:

        * `quarantined` / `deprecated` / `deleted` — withdrawn.
        * `candidate` — never reviewed. A released premise returns here rather
          than to active, so a conclusion does not silently regain support the
          moment someone undoes a retraction; somebody has to validate it again.
        * `contested` — itself disputed. A conclusion resting on an open
          question is an open question.

        An earlier version only excluded the blocked states, which let an
        unreviewed candidate justify a conclusion. A recovery test caught it.
        """
        memory = self.fabric.state.memories.get(memory_id)
        if memory is None:
            return False
        return memory.lifecycle_state is LifecycleState.ACTIVE

    def independent_support(
        self, memory_ids: Iterable[str], tainted_by: Iterable[str] = ()
    ) -> list[str]:
        """Thin the set down to members that are independent of each other
        **and of the premises that were lost**.

        Two memories sharing an ancestor are one piece of evidence, so the first
        is kept and the second dropped. And a survivor descended from a *lost*
        premise is not fresh support at all — it is the retracted evidence
        wearing a different hat, which is the whole "copies are not
        corroboration" claim (SECURITY.md T3).

        Omitting `tainted_by` was a real bug: a copy of a retracted premise kept
        a conclusion alive, because the copy was checked against the other
        survivors and never against the thing it came from.

        Deterministic order, because an operator reading two runs of the same
        store should see the same answer.
        """
        graph = self.fabric.lineage_graph
        tainted = list(tainted_by)
        kept: list[str] = []
        for candidate in sorted(memory_ids):
            if any(
                not graph.evidence_is_independent([candidate, lost])
                for lost in tainted
            ):
                continue
            if all(
                graph.evidence_is_independent([candidate, existing])
                for existing in kept
            ):
                kept.append(candidate)
        return kept

    def recompute(self, memory_id: str) -> SupportVerdict:
        """Does this conclusion still stand?

        Not "did an ancestor fail" — that is the question the old unconditional
        loop answered, and answering it is what destroyed independently
        justified knowledge.
        """
        # A recognised copy is the same document as its original, not a
        # conclusion drawn from it, so it has no parent edge -- and without
        # this check a copy of withdrawn evidence read as a justified root
        # observation, while the engine had already contested it. The two
        # disagreeing is what invariant 8 exists to catch, and `faultsim`'s
        # `cycle_terminates` did.
        withdrawn_copies = self.withdrawn_copies_of(memory_id)
        if withdrawn_copies:
            return SupportVerdict(
                memory_id=memory_id, surviving=(), lost=tuple(withdrawn_copies),
                independent_count=0, verdict=CONTESTED,
                reason=(
                    "same document as withdrawn "
                    + ", ".join(withdrawn_copies)
                    + "; a copy is not independent support"
                ),
            )

        parents = self.parents_of(memory_id)
        if not parents:
            # A root observation is its own justification. Invalidating a
            # conclusion does not invalidate the observation it came from.
            return SupportVerdict(
                memory_id=memory_id, surviving=(), lost=(), independent_count=0,
                verdict=JUSTIFIED, reason="root observation; no premises to lose",
            )

        surviving: list[str] = []
        lost: list[str] = []
        required_total = 0
        required_surviving = 0
        alternatives: list[str] = []
        copies: list[str] = []
        version_moved: list[str] = []

        for parent in parents:
            kind = self.kind_of(memory_id, parent)
            if kind is JustificationKind.CONTRADICTS:
                continue
            if kind is JustificationKind.REQUIRED:
                required_total += 1

            usable = self.is_usable(parent)
            moved = False
            recorded = self.parent_version(memory_id, parent)
            if usable and recorded is not None:
                moved = self.fabric.state.memories[parent].version != recorded

            if usable and not moved:
                surviving.append(parent)
                if kind is JustificationKind.REQUIRED:
                    required_surviving += 1
                elif kind is JustificationKind.ALTERNATIVE:
                    alternatives.append(parent)
                elif kind is JustificationKind.COPIED:
                    copies.append(parent)
            else:
                lost.append(parent)
                if moved:
                    version_moved.append(parent)

        independent = self.independent_support(alternatives, tainted_by=lost)
        all_requirements_met = required_surviving == required_total

        # Justified when every conjunct survives *and* the conclusion rests on
        # something: either it had requirements and they all hold, or it had
        # alternatives and at least one independent one holds.
        #
        # The earlier version demanded a surviving ALTERNATIVE in every case,
        # which called a pure conjunction with all its premises intact
        # "contested" — a conclusion with one required premise that was never
        # withdrawn is justified, and a test for recovering from a false
        # retraction caught it.
        if all_requirements_met and (required_total > 0 or independent):
            return SupportVerdict(
                memory_id=memory_id, surviving=tuple(surviving), lost=tuple(lost),
                independent_count=len(independent), verdict=JUSTIFIED,
                reason=(
                    f"{len(independent)} independent justification(s) survive: "
                    + ", ".join(independent)
                    if independent
                    else f"all {required_total} required premise(s) hold"
                ),
            )

        if version_moved:
            # A premise was revised, not withdrawn. The recorded justification
            # is gone but a newer version exists, so this needs revalidating
            # against the new evidence rather than declaring support absent —
            # which is §4.4's "revalidation against new evidence".
            return SupportVerdict(
                memory_id=memory_id, surviving=tuple(surviving), lost=tuple(lost),
                independent_count=len(independent), verdict=CONTESTED,
                reason=(
                    "premise(s) revised since this was derived ("
                    + ", ".join(version_moved)
                    + "); revalidate against the new version"
                ),
            )

        if not surviving:
            return SupportVerdict(
                memory_id=memory_id, surviving=(), lost=tuple(lost),
                independent_count=0, verdict=UNSUPPORTED,
                reason="every justification failed",
            )

        if copies and not independent:
            # The trap this exists to avoid: a copy of a retracted premise is
            # not fresh support for the conclusion.
            return SupportVerdict(
                memory_id=memory_id, surviving=tuple(surviving), lost=tuple(lost),
                independent_count=0, verdict=CONTESTED,
                reason=(
                    "remaining support is a copy of lost evidence, "
                    "which is not independent corroboration"
                ),
            )

        return SupportVerdict(
            memory_id=memory_id, surviving=tuple(surviving), lost=tuple(lost),
            independent_count=len(independent), verdict=CONTESTED,
            reason=(
                "a required premise was lost"
                if not all_requirements_met
                else "support is incomplete"
            ),
        )

    def recompute_descendants(self, memory_id: str) -> list[SupportVerdict]:
        """Every descendant, nearest first, so a verdict is computed after the
        verdicts it may depend on."""
        graph = self.fabric.lineage_graph
        nodes = sorted(graph.descendants(memory_id), key=lambda n: n.depth)
        return [self.recompute(node.memory_id) for node in nodes]


def justification_context(
    parents: Iterable[tuple[str, JustificationKind]] | None = None,
) -> dict[str, Any]:
    """Build the context fragment that records edge kinds.

    Supplied at `derive` time, because that is when the caller knows whether the
    premises were a conjunction or genuine alternatives — and nothing else can
    recover it afterwards.
    """
    if not parents:
        return {}
    return {
        "justifications": {
            parent: kind.value if isinstance(kind, JustificationKind) else str(kind)
            for parent, kind in parents
        }
    }
