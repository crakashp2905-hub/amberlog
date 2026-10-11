"""The relevance contract: what a task asks for, and what an assessment says.

Schemas and invariants only. No ranker, no features, no scoring — deliberately,
because the one way this project has repeatedly gone wrong is building a
mechanism before the thing that could falsify it, and a ranker written before
the benchmark gets tuned on whatever examples flatter it.

## Why relevance is a separate axis from everything already here

The store already answers four questions about a memory: is it *valid*
(lifecycle, contradiction, support), may this agent *access* it (scope,
capabilities, tenant), is it *current* (version, supersession), and has
exposing it ever *helped* (value estimates). None of those is relevance.

A memory can be relevant and false. It can be true, authorised and useless for
the task in front of the agent. It can be irrelevant this hour and the only
thing that matters the next. So:

> **Irrelevant means "do not put this in this context". It never means
> "delete", "quarantine", "retract", or "stop trusting".**

That is not a style preference. Phase A measured a withdrawal policy driving
task success from 0.608 down to 0.483 by removing memories that had merely been
present when an episode failed, and of naive blame's 87 withdrawals 57 were
about a completely different fault. A relevance signal that mutated lifecycle
would be the same mistake with a new name, so `RelevanceAssessment` has no
route to a lifecycle change and `tests/test_relevance_contract.py` asserts it.

## What the measurements predict about relevance ranking

Worth stating here rather than discovering it in a results file. Across Phase A
and PA′, success tracked one quantity: whether a correct memory reached the
prompt. Conversion given one was 93–98% in *every* arm, and coverage-to-success
correlated at +0.975. **Perfect selection over the existing corpus was worth
about +5 points**; the rest of the gap was corpus coverage, which is memory
construction and not retrieval.

So on that world, a perfect relevance engine has a ~5-point ceiling. That is
not an argument against building this — it is the reason the oracle arm is
mandatory (AGENTS.md principle 8a/8b) and the reason the benchmark comes before
the ranker. If the oracle ceiling on the new benchmark is also ~5 points, the
honest conclusion is that relevance ranking is not where the headroom is, and
it is much cheaper to learn that from an oracle than from a tuned ranker.

## Scores are not probabilities

`score` is an ordering signal with no calibrated interpretation unless a
specific model documents one, and `uncertainty` is likewise a spread and not a
posterior width. AGENTS.md principle 5 requires value estimates to carry a
distribution; relevance makes the weaker claim honestly rather than the
stronger one falsely. `label` is the thing a caller should branch on.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence

from .identity import DEFAULT_TENANT
from .ids import new_ulid

CONTRACT_VERSION = "1.0.0"
"""Versioned separately from `SCHEMA_VERSION`.

An assessment is not stored in the event log — it is derived, reproducible from
a context and a corpus state, and cheaper to recompute than to migrate. Tying
it to the log's schema version would force a store migration every time a
feature weight changed.
"""


class RelevanceLabel(str, Enum):
    """The thing a caller branches on."""

    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    UNCERTAIN = "uncertain"
    """A first-class outcome, not a failure to decide.

    Forcing a binary label when the signals do not support one is how a
    retrieval system comes to look confident about a corpus it has not
    covered. `uncertain` is what an honest engine returns when the evidence for
    *either* answer is thin, and the benchmark scores abstention separately.
    """


class ReasonCode(str, Enum):
    """Why a memory was included or left out.

    Generated from the decision path, never written after the fact to make a
    plausible story. The set is closed so a report can aggregate over it, and
    the gate codes are deliberately distinguishable from the ranking ones: an
    operator asking "why did the agent not see this?" needs to know whether it
    was ranked low or refused outright, and those have different remedies.
    """

    # --- included -----------------------------------------------------
    DIRECT_MATCH = "direct_match"
    ENTITY_LINK = "entity_link"
    TEMPORAL_APPLICABILITY = "temporal_applicability"
    SUPPORTS_HYPOTHESIS = "supports_hypothesis"
    CONTRADICTS_HYPOTHESIS = "contradicts_hypothesis"
    DEPENDENCY_REQUIRED = "dependency_required"
    CRITICAL_FACT = "critical_fact"

    # --- excluded by ranking or budget --------------------------------
    LOW_RELEVANCE = "low_relevance"
    DUPLICATE_OR_REDUNDANT = "duplicate_or_redundant"
    OVER_BUDGET = "over_budget"
    CONTEXT_MISMATCH = "context_mismatch"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

    # --- excluded by a hard gate --------------------------------------
    #
    # Never a ranking outcome. A hard gate is not a low score, and collapsing
    # them would let a tuning change appear to fix an authorisation failure.
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    BLOCKED_LIFECYCLE = "blocked_lifecycle"
    UNAUTHORIZED = "unauthorized"
    WRONG_TENANT = "wrong_tenant"

    @property
    def is_hard_gate(self) -> bool:
        return self in _HARD_GATES


_HARD_GATES = frozenset(
    {
        ReasonCode.SUPERSEDED,
        ReasonCode.RETRACTED,
        ReasonCode.BLOCKED_LIFECYCLE,
        ReasonCode.UNAUTHORIZED,
        ReasonCode.WRONG_TENANT,
    }
)


class MissingSignal:
    """A feature that could not be computed, as distinct from one that scored 0.

    A singleton rather than `None` or `0.0`. Both of those read as "this
    memory has no lexical overlap" when the truth is "no lexical index was
    configured", and the difference decides whether a low rank is a property of
    the memory or of the deployment. The contract requires missing to stay
    missing all the way into the explanation.
    """

    _instance: "MissingSignal | None" = None

    def __new__(cls) -> "MissingSignal":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "MISSING"

    def __bool__(self) -> bool:
        """False, so `if features.get(x):` cannot silently treat it as a score.

        A truthy sentinel would be worse: it would read as a present signal
        wherever someone forgot to check.
        """
        return False


MISSING = MissingSignal()

FeatureValue = float | MissingSignal


@dataclass(frozen=True)
class ContextSnapshot:
    """What a task is asking for, frozen at a point in time.

    Immutable and identified, because an assessment is only meaningful relative
    to a context and an audit that cannot say *which* context is not an audit.

    `state_facts` holds what the caller asserts about the world now, and
    `inferred` holds anything a model guessed. They are separate fields on
    purpose: an inferred field must never set authorisation or risk, and the
    only way to guarantee that is to be able to tell them apart downstream.
    """

    task_text: str
    goal: str = ""
    constraints: tuple[str, ...] = ()
    agent_id: str = ""
    agent_role: str = ""
    tenant_id: str = DEFAULT_TENANT
    scope: str = ""
    event_time: int | None = None
    """The time the task is *about*, which is not the time it is asked.

    Separate from a memory's recorded time so "what was true then" and "what
    did we know then" stay different questions.
    """
    state_facts: Mapping[str, Any] = field(default_factory=dict)
    inferred: Mapping[str, Any] = field(default_factory=dict)
    entities: tuple[str, ...] = ()
    token_budget: int = 0
    policy_version: str = ""
    context_id: str = field(default_factory=lambda: "cx_" + new_ulid())
    snapshot_revision: int = 1
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.task_text.strip():
            raise ValueError("a context needs a task")
        if self.token_budget < 0:
            raise ValueError("a token budget cannot be negative")
        overlap = set(self.state_facts) & set(self.inferred)
        if overlap:
            # Otherwise a reader cannot tell which value won, and the one that
            # won might be the guess.
            raise ValueError(
                f"a field cannot be both observed and inferred: {sorted(overlap)}"
            )

    def evolve(self, **changes: Any) -> "ContextSnapshot":
        """A changed context is a **new** context, with its own id.

        The whole point of the contract is that changing the task can change
        relevance without touching a single memory. Reusing the id would make
        two different questions share one audit record.
        """
        changes.setdefault("context_id", "cx_" + new_ulid())
        changes.setdefault("snapshot_revision", self.snapshot_revision + 1)
        return replace(self, **changes)

    def to_json(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "task_text": self.task_text,
            "goal": self.goal,
            "constraints": list(self.constraints),
            "agent_id": self.agent_id,
            "agent_role": self.agent_role,
            "tenant_id": self.tenant_id,
            "scope": self.scope,
            "event_time": self.event_time,
            "state_facts": dict(self.state_facts),
            "inferred": dict(self.inferred),
            "entities": list(self.entities),
            "token_budget": self.token_budget,
            "policy_version": self.policy_version,
            "snapshot_revision": self.snapshot_revision,
            "contract_version": self.contract_version,
        }


@dataclass(frozen=True)
class RelevanceEvidence:
    """One signal's contribution, in terms a human can check.

    `contribution` may be `MISSING`, and an explanation naming a missing signal
    is more useful than one that silently omits it: "no vector index
    configured" tells an operator something actionable, while an absent row
    tells them nothing.
    """

    signal: str
    explanation: str
    contribution: FeatureValue = MISSING
    source_ids: tuple[str, ...] = ()

    @property
    def is_missing(self) -> bool:
        return isinstance(self.contribution, MissingSignal)

    def to_json(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "explanation": self.explanation,
            "contribution": None if self.is_missing else self.contribution,
            "contribution_missing": self.is_missing,
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True)
class RelevanceAssessment:
    """What the engine thinks about one memory version for one context.

    Bound to an exact `(memory_id, memory_version, context_id)`. Both halves
    matter: a memory revised after the assessment is a different claim, and the
    same memory is a different answer for a different task.

    Carries no route to a lifecycle change, by construction. There is no
    `quarantine`, no `withdraw`, no lifecycle field — relevance proposes what
    goes in a context and nothing else.
    """

    memory_id: str
    memory_version: int
    context_id: str
    label: RelevanceLabel
    score: float | None = None
    """An ordering signal, **not** a probability unless a model documents
    calibration. `None` when the engine has no basis for one, which is
    different from zero."""
    uncertainty: float | None = None
    evidence: tuple[RelevanceEvidence, ...] = ()
    model_version: str = ""
    feature_version: str = ""
    contract_version: str = CONTRACT_VERSION
    assessed_at: int = 0

    def __post_init__(self) -> None:
        if self.memory_version < 1:
            raise ValueError("an assessment binds to a concrete memory version")
        if self.label is RelevanceLabel.UNCERTAIN and self.score is not None:
            # Not forbidden in principle, but a score on an uncertain label is
            # read as a ranking position, and ranking on a label that means
            # "we do not know" is how an unevaluated memory outranks an
            # evaluated one. The exposure policy made exactly that mistake.
            raise ValueError(
                "an uncertain assessment must not carry a score; the label is "
                "the claim and a score would be read as a rank"
            )
        if not self.evidence:
            raise ValueError(
                "an assessment without evidence is not auditable; say which "
                "signals were missing rather than omitting them"
            )

    @property
    def applies_to(self) -> tuple[str, int, str]:
        return (self.memory_id, self.memory_version, self.context_id)

    def applies(self, memory_id: str, memory_version: int, context_id: str) -> bool:
        """Whether this assessment may be used for this exact question.

        The guard against a stale assessment being applied after a revision, or
        reused for a different task. Checked rather than assumed, because the
        failure is silent: a wrong answer that looks like a cached one.
        """
        return self.applies_to == (memory_id, memory_version, context_id)

    @property
    def missing_signals(self) -> tuple[str, ...]:
        return tuple(e.signal for e in self.evidence if e.is_missing)

    def to_json(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "memory_version": self.memory_version,
            "context_id": self.context_id,
            "label": self.label.value,
            "score": self.score,
            "uncertainty": self.uncertainty,
            "evidence": [e.to_json() for e in self.evidence],
            "model_version": self.model_version,
            "feature_version": self.feature_version,
            "contract_version": self.contract_version,
            "assessed_at": self.assessed_at,
            "missing_signals": list(self.missing_signals),
        }


@dataclass(frozen=True)
class SelectionDecision:
    """Whether one memory made it into the context, and why.

    Both outcomes are recorded. Logging only what was included makes an
    omission undiagnosable — the failure mode the research documents call
    retrieval regret, and the reason this carries a reason code even on the
    happy path.
    """

    memory_id: str
    memory_version: int
    included: bool
    reasons: tuple[ReasonCode, ...]
    relevance_score: float | None = None
    token_cost: int = 0
    integrity_revision: int = 0

    def __post_init__(self) -> None:
        if not self.reasons:
            raise ValueError("a selection decision needs at least one reason")
        if self.included and any(r.is_hard_gate for r in self.reasons):
            # The invariant that matters most in this file: a hard gate is not
            # a weight to be outvoted. If this ever constructs, something has
            # let a relevance score overrule authorisation or retraction.
            blocking = [r.value for r in self.reasons if r.is_hard_gate]
            raise ValueError(
                f"cannot include a memory refused by a hard gate: {blocking}"
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "memory_version": self.memory_version,
            "included": self.included,
            "reasons": [r.value for r in self.reasons],
            "relevance_score": self.relevance_score,
            "token_cost": self.token_cost,
            "integrity_revision": self.integrity_revision,
        }


@dataclass(frozen=True)
class ContextPackage:
    """What the agent will see, plus everything that did not make it.

    Bound to an `integrity_revision` — the log head when it was assembled — so
    a consequential action can re-verify rather than trust a package that may
    have been overtaken by a retraction. That is the same time-of-check /
    time-of-use defence `ExposureToken` makes for a single memory, at the level
    of a whole context.
    """

    context_id: str
    decisions: tuple[SelectionDecision, ...]
    integrity_revision: int
    token_budget: int
    token_count: int = 0
    unresolved_conflicts: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.token_budget and self.token_count > self.token_budget:
            raise ValueError(
                f"assembled {self.token_count} tokens against a budget of "
                f"{self.token_budget}; the assembler must omit rather than overflow"
            )

    @property
    def selected(self) -> tuple[SelectionDecision, ...]:
        return tuple(d for d in self.decisions if d.included)

    @property
    def omitted(self) -> tuple[SelectionDecision, ...]:
        return tuple(d for d in self.decisions if not d.included)

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(d.memory_id for d in self.selected)

    def blocked_by_gate(self) -> tuple[SelectionDecision, ...]:
        """Omissions a ranking change could not fix.

        Kept distinct in the reporting because the remedies differ: a low rank
        is a tuning question, an authorisation refusal is a policy question,
        and conflating them lets a weight change look like it fixed a
        permission bug.
        """
        return tuple(
            d for d in self.omitted if any(r.is_hard_gate for r in d.reasons)
        )

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in self.decisions:
            for reason in decision.reasons:
                counts[reason.value] = counts.get(reason.value, 0) + 1
        return dict(sorted(counts.items()))

    def to_json(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "integrity_revision": self.integrity_revision,
            "token_budget": self.token_budget,
            "token_count": self.token_count,
            "selected": [d.memory_id for d in self.selected],
            "decisions": [d.to_json() for d in self.decisions],
            "unresolved_conflicts": list(self.unresolved_conflicts),
            "missing_evidence": list(self.missing_evidence),
            "reason_counts": self.reason_counts(),
            "contract_version": self.contract_version,
        }


def assert_no_lifecycle_authority(obj: object) -> None:
    """Fail loudly if a relevance type grows a route to mutating a memory.

    Called by the contract tests rather than at runtime. It exists because the
    invariant is about what the code *cannot* do, and that kind of property
    rots silently — somebody adds a convenience method and nothing fails.

    The names are the ones that would actually appear: the store's own
    lifecycle API.
    """
    forbidden = (
        "quarantine",
        "release",
        "forget",
        "validate",
        "revise",
        "erase_content",
        "lifecycle_state",
        "set_lifecycle",
        "delete",
    )
    found = [name for name in forbidden if hasattr(obj, name)]
    if found:
        raise AssertionError(
            f"{type(obj).__name__} exposes lifecycle authority: {found}. "
            "Relevance decides what enters a context, never what a memory is."
        )
