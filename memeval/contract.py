"""An evaluation contract that cannot be satisfied by the usual mistakes.

A `Registration` is written **before** the run: the hypothesis, the primary
metric, the baselines, the ceiling, the share of headroom that counts as
success, and the smallest effect worth acting on. `evaluate()` then applies it
to what the run produced, mechanically.

The point is the verdicts it refuses to give. Each refusal is a mistake MemoryFabric's own experiments made and published:

| refusal | the case |
|---|---|
| **INVALID: baseline not measured** | X1 took `B = 0.000` from another document's table -- a different metric at a different budget. On the registered metric a plain baseline scored 1.000. |
| **INVALID: ceiling exceeded** | Phase A's oracle was bounded by its retrieval budget; an arm beat it and proved it was not a ceiling. |
| **ABANDONED: no headroom** | P2's `full_context` baseline reached the oracle's 0.800, so no method could pass. X4's oracle was 2.5 points above a vector store. |
| **UNDERPOWERED** | X4's minimum detectable effect was 0.10-0.14 against an observed 0.04. |
| **INVALID: too few seeds** | AGENTS.md requires five. |

A registration that would produce one of these is not refused at the end of a
multi-hour run; `check_before_run()` reports the ones that can be known in
advance -- an expected headroom too small to pass, a run too small to
resolve the bar -- so they are caught before the compute is spent.

H3's mistake, a margin of +0.030 against a ceiling of +0.027, cannot be
written here at all: the bar is a share of the measured headroom, never an
absolute margin, so it is always below the ceiling by construction.

## What it does not do

It does not decide whether a hypothesis is worth testing, whether a world can
exhibit the effect, or whether a fixture encodes the answer -- the last of which
`checks.fixture_independence` exists for, as a test-time check. It makes a
specific class of reporting error impossible to publish without the contract
saying so; it does not make an experiment good.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from . import power


class Outcome(str, Enum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT SUPPORTED"
    ABANDONED = "ABANDONED"
    UNDERPOWERED = "UNDERPOWERED"
    INVALID = "INVALID"


@dataclass
class Verdict:
    outcome: Outcome
    reasons: list[str] = field(default_factory=list)
    baseline: float | None = None
    ceiling: float | None = None
    headroom: float | None = None
    bar: float | None = None
    mechanism: float | None = None
    share_of_headroom: float | None = None
    realised_mde: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {k: (v.value if isinstance(v, Enum) else v)
                for k, v in self.__dict__.items()}


@dataclass
class Registration:
    """What an experiment commits to before it runs."""

    hypothesis: str
    metric: str
    mechanism: str
    baselines: Sequence[str]
    ceiling: str
    share_of_headroom: float = 0.40
    abandon_at_headroom: float = 0.05
    min_effect: float = 0.05
    """The smallest effect worth acting on. The run must be able to resolve it."""
    seeds_required: int = 5

    def __post_init__(self) -> None:
        if not self.baselines:
            raise ValueError("a registration needs at least one baseline")
        if not 0 < self.share_of_headroom <= 1:
            raise ValueError("share_of_headroom must be in (0, 1]")
        if self.mechanism in self.baselines or self.mechanism == self.ceiling:
            raise ValueError("the mechanism cannot also be a baseline or the "
                             "ceiling")

    # --- before the run ----------------------------------------------------

    def check_before_run(self, *, n_pairs: int, expected_discordance: float,
                         expected_headroom: float | None = None) -> list[str]:
        """Problems knowable before any compute is spent.

        Returns a list of reasons; empty means none were found. Not a
        guarantee -- the realised discordance and headroom are checked again
        in `evaluate()` -- but it catches the registrations that could never
        have produced a supported result.
        """
        problems = []
        mde = power.mde_paired(n_pairs, expected_discordance)
        if mde > self.min_effect:
            problems.append(
                f"the run cannot resolve the effect it registers: MDE {mde:.3f} "
                f"against a minimum effect of {self.min_effect:.3f}; it needs "
                f"about {power.pairs_needed(self.min_effect, expected_discordance)} "
                f"paired units, not {n_pairs}")
        if expected_headroom is not None:
            if expected_headroom <= self.abandon_at_headroom:
                problems.append(
                    f"expected headroom {expected_headroom:.3f} is at or below "
                    f"the abandonment threshold {self.abandon_at_headroom:.3f}: "
                    f"measure the ceiling before running the mechanism")
            needed = self.share_of_headroom * expected_headroom
            if needed < mde:
                problems.append(
                    f"passing needs a gain of {needed:.3f} over the baseline, "
                    f"below the MDE {mde:.3f}: a pass could not be told from noise")
        return problems

    # --- after the run -----------------------------------------------------

    def evaluate(self, arms: Mapping[str, Mapping[str, Any]], *,
                 seeds: int, n_pairs: int | None = None,
                 discordance: float | None = None) -> Verdict:
        """Apply the registration to the run, refusing what it cannot support.

        `arms` maps an arm name to its results, which must include `metric`.
        Every registered baseline and the ceiling must be **present in `arms`**,
        because a baseline that is not measured in the run is a number from
        somewhere else -- X1's mistake.
        """
        verdict = Verdict(outcome=Outcome.INVALID)

        missing = [b for b in self.baselines if b not in arms
                   or arms[b].get(self.metric) is None]
        if missing:
            verdict.reasons.append(
                f"registered baseline(s) {missing} were not measured in this "
                f"run; a baseline quoted from elsewhere is not a baseline")
        if self.ceiling not in arms or arms[self.ceiling].get(self.metric) is None:
            verdict.reasons.append(f"the ceiling {self.ceiling!r} was not measured")
        if self.mechanism not in arms or arms[self.mechanism].get(self.metric) is None:
            verdict.reasons.append(f"the mechanism {self.mechanism!r} was not measured")
        if seeds < self.seeds_required:
            verdict.reasons.append(
                f"{seeds} seed(s) against the {self.seeds_required} required")
        if verdict.reasons:
            return verdict

        ceiling = float(arms[self.ceiling][self.metric])
        baseline = max(float(arms[b][self.metric]) for b in self.baselines)
        mechanism = float(arms[self.mechanism][self.metric])
        verdict.ceiling, verdict.baseline, verdict.mechanism = (
            ceiling, baseline, mechanism)

        above = {name: float(row[self.metric]) for name, row in arms.items()
                 if name != self.ceiling and row.get(self.metric) is not None
                 and float(row[self.metric]) > ceiling + 1e-9}
        if above:
            verdict.reasons.append(
                f"arm(s) {sorted(above)} scored above the ceiling {ceiling:.4f}: "
                f"the ceiling is wrong, and nothing measured against it means "
                f"what it says")
            return verdict

        # Rounded to the precision it is compared at: 1.0 - 0.95 is
        # 0.050000000000000044, which would otherwise pass a `<= 0.05` test it
        # should fail.
        headroom = round(ceiling - baseline, 6)
        verdict.headroom = headroom
        if headroom <= self.abandon_at_headroom:
            verdict.outcome = Outcome.ABANDONED
            verdict.reasons.append(
                f"headroom {headroom:.4f} is at or below {self.abandon_at_headroom}: "
                f"a baseline already reaches the ceiling, so the metric cannot "
                f"distinguish the mechanism")
            return verdict

        bar = baseline + self.share_of_headroom * headroom
        verdict.bar = round(bar, 6)
        verdict.share_of_headroom = round((mechanism - baseline) / headroom, 6)

        if n_pairs is not None and discordance is not None:
            mde = power.mde_paired(n_pairs, discordance)
            verdict.realised_mde = round(mde, 6)
            needed = bar - baseline
            if mde > needed:
                verdict.outcome = Outcome.UNDERPOWERED
                verdict.reasons.append(
                    f"the realised MDE {mde:.4f} exceeds the gain needed to pass "
                    f"({needed:.4f}): this run could not have told a pass from "
                    f"noise")
                return verdict

        verdict.outcome = (Outcome.SUPPORTED if mechanism >= bar - 1e-9
                           else Outcome.NOT_SUPPORTED)
        return verdict
