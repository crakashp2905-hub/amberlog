"""Audit the SUPPORTED claims against standards that postdate them.

Every supported result in this project was measured **before**
`experiments/checks.py` existed, and before X5 established that a registered
threshold also needs a power calculation. Six apparatus faults were found in
two days of looking — a threshold larger than its own ceiling, an oracle
bounded by its retrieval budget, a metric a baseline already maxed, a baseline
quoted at the wrong metric and budget, an AUC published as its own complement,
and a result reported below its own detection threshold.

None of those faults was in a mechanism. All were in the thing measuring it.
So the question this module asks is not "is the fabric good" but:

> **Would each supported claim still be supported under the standards the
> failures taught us?**

That is the honest way to shore up the positive claims, and it is cheaper than
re-running them: every input below is a number **traced to the result document
that reported it**, cited in `source`, and the arithmetic is done here rather
than asserted in prose.

## What is checked

* **Power.** For a proportion-difference claim, is the reported effect above the minimum detectable effect at the reported n? `MDE = 2.80 * sqrt(d / n)` for a paired comparison at 80% power and two-sided 0.05, and `2.80 * sqrt(2 * p * (1 - p) / n)` for two independent groups. An effect below its own MDE is not evidence, whatever its p-value.
* **Headroom.** Was `C - B` large enough that the threshold was reachable (principle 8a), and not so small that a baseline had already maxed the metric (8c)?
* **Replication.** How many seeds, and was it measured on a frozen split or a second population?

Claims of **absence** — "zero stale citations", "no memory acted on after
retraction" — are marked `absence` and get a different treatment: the question
there is not effect size but whether n was large enough for a non-zero rate to
have shown up, which is `1 - (1 - r)**n` for a true rate `r`.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

Z80 = 2.80
"""z for 80% power at two-sided alpha 0.05 (1.96 + 0.84)."""


@dataclass
class Claim:
    name: str
    source: str
    kind: str                      # "difference" | "absence"
    effect: float | None = None    # reported effect size
    n: int | None = None           # observations the effect rests on
    seeds: int | None = None
    paired: bool = True
    baseline: float | None = None  # B
    ceiling: float | None = None   # C
    replicated: str = "no"
    deterministic: bool = False
    """No sampling noise: the arm returns the same answer for the same case.

    The MDE framing does not apply, and reporting one would be a false
    failure. X3 flips 3 of 3 cases from 0.000 to 1.000 with no stochastic
    component, so the question is not "could this be noise" -- it cannot be --
    but "would a fourth case also flip", which is generalisation and is
    answered by a held-out split rather than by a bigger n.
    """

    note: str = ""

    def mde(self) -> float | None:
        """Minimum detectable effect at the reported n."""
        if not self.n or self.n <= 1:
            return None
        if self.kind == "absence" or self.deterministic:
            return None
        if self.paired:
            # Discordance is unreported in every one of these documents, so it
            # is approximated by the effect itself -- the smallest value
            # consistent with the reported difference, which makes this the
            # most *favourable* MDE each claim could have. A claim that fails
            # here fails under any assumption.
            d = max(abs(self.effect or 0.0), 0.02)
            return Z80 * math.sqrt(d / self.n)
        p = self.baseline if self.baseline is not None else 0.5
        p = min(max(p, 0.01), 0.99)
        return Z80 * math.sqrt(2 * p * (1 - p) / self.n)

    def detectable_rate(self, confidence: float = 0.95) -> float | None:
        """For an absence claim: the smallest true rate that would almost
        certainly have shown up at this n.

        `1 - (1 - r)**n >= confidence`, solved for r. A zero observed at n=30
        is consistent with a true rate of 9.5%, which is worth knowing before
        quoting the zero.
        """
        if self.kind != "absence" or not self.n:
            return None
        return 1.0 - (1.0 - confidence) ** (1.0 / self.n)

    def headroom(self) -> float | None:
        if self.baseline is None or self.ceiling is None:
            return None
        return round(self.ceiling - self.baseline, 4)

    def verdict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "source": self.source,
                               "kind": self.kind, "n": self.n,
                               "seeds": self.seeds,
                               "replicated": self.replicated}
        issues: list[str] = []

        if self.kind == "absence":
            rate = self.detectable_rate()
            out["smallest_rate_95pc_detectable"] = (
                None if rate is None else round(rate, 4))
            if rate is not None and rate > 0.05:
                issues.append(
                    f"a zero at n={self.n} is consistent with a true rate up "
                    f"to {rate:.1%}")
        elif self.deterministic:
            out["effect"] = self.effect
            out["mde_at_this_n"] = None
            out["cases"] = self.n
            issues.append(
                f"deterministic, so power does not apply; the uncertainty is "
                f"generalisation from {self.n} case(s) and needs a held-out "
                f"split rather than a larger n")
        else:
            mde = self.mde()
            out["effect"] = self.effect
            out["mde_at_this_n"] = None if mde is None else round(mde, 4)
            if mde is None:
                issues.append("n not reported, so power cannot be checked")
            elif (self.effect or 0.0) < mde:
                issues.append(
                    f"effect {self.effect} is below its own MDE {mde:.3f}")
            elif (self.effect or 0.0) < 2 * mde:
                issues.append(
                    f"effect {self.effect} is under 2x its MDE {mde:.3f}: "
                    f"real but thin")

        head = self.headroom()
        out["B"], out["C"], out["headroom"] = (
            self.baseline, self.ceiling, head)
        if head is not None and head <= 0.05:
            issues.append(
                f"headroom {head} <= 0.05: a baseline had nearly maxed the "
                f"metric (principle 8c)")

        if (self.seeds or 0) < 5:
            issues.append(
                f"{self.seeds or 0} seeds against AGENTS.md's requirement of 5")
        if self.replicated == "no":
            issues.append("not replicated on a second split or population")

        out["issues"] = issues
        out["holds"] = not [i for i in issues if
                            "below its own MDE" in i
                            or "cannot be checked" in i
                            or "principle 8c" in i]
        out["note"] = self.note
        return out


# Every number below is traced to the document named in `source`. Nothing here
# is recalled or inferred.
CLAIMS = [
    Claim(
        name="PB2 — retraction propagation",
        source="research/results/phase-b-federated-agents.md",
        kind="difference", effect=0.17, n=240, seeds=5, paired=True,
        replicated="both sharing policies",
        note="17% -> 0% acting on origin-retracted memory, 240 decisions per "
             "arm. The effect is large relative to n and it held under two "
             "policies, which is the nearest thing here to a replication.",
    ),
    Claim(
        name="H4b — contested hypotheses preserved",
        source="research/results/h4-topology-and-diversity.md",
        kind="difference", effect=0.095, n=200, seeds=200, paired=True,
        replicated="live run with three real models",
        note="P(correct) 0.905 -> 1.000, 200 replications per cell. "
             "Simulation, but the live multi-agent run tested the same "
             "mechanism with models that genuinely disagreed.",
    ),
    Claim(
        name="H1 — causal value is estimable",
        source="research/results/h1-causal-credit.md",
        kind="difference", effect=0.29, n=2000, seeds=10, paired=True,
        replicated="two corpus sizes",
        note="rho 0.76 against a naive 0.47. The only supported result whose "
             "own document discusses power.",
    ),
    Claim(
        name="P3b — agent teams",
        source="research/results/p3b-agent-teams.md",
        kind="difference", effect=0.19, n=300, seeds=5, paired=True,
        baseline=0.780, ceiling=1.000,
        replicated="agent-count sweep to 100",
        note="fabric 0.970 against the best baseline's 0.780, oracle 1.000. "
             "The agent is deterministic, so seed variance is the only noise "
             "and the 19-point gap is far outside it. Nothing here is "
             "evidence about model behaviour, which section 6 of that result "
             "states as a choice.",
    ),
    Claim(
        name="Copy recognition — no double-counted support",
        source="research/results/p2b-copy-recognition.md",
        kind="absence", n=30, seeds=5,
        replicated="both splits",
        note="0.000 stale citations and 0.000 unrecognised copies, matching "
             "the oracle on both splits. An absence claim: the question is "
             "what rate a zero at this n could hide.",
    ),
    Claim(
        name="Live multi-agent — disagreement preserved",
        source="research/results/live-multi-agent.md",
        kind="difference", effect=0.80, n=10, seeds=1, paired=True,
        replicated="no",
        note="80% confidently wrong -> 0% with three real disagreeing models. "
             "The effect is enormous, and it is one run with no seeds: it is "
             "the demonstration that H4b's mechanism survives real "
             "disagreement, not an independent measurement of its size.",
    ),
    Claim(
        name="X3 — scoped adjustments",
        source="research/results/x3-scoped-adjustments.md",
        kind="difference", effect=1.0, n=3, seeds=1, paired=True,
        deterministic=True, baseline=0.0, ceiling=1.0,
        replicated="no — test split is 0.000 at a ceiling of 0.000",
        note="0.000 -> 1.000 on dev, 3 cases of 3. Deterministic, so there is "
             "no sampling noise, but three cases is three cases and the test "
             "split was abandoned in advance at a zero ceiling.",
    ),
]


def run() -> dict[str, Any]:
    rows = [claim.verdict() for claim in CLAIMS]
    holding = [r for r in rows if r["holds"]]
    return {
        "audit": "supported-claims",
        "standard": ("power at the reported n, headroom per principles 8a/8c, "
                     "seeds per AGENTS.md, and replication"),
        "claims": len(rows),
        "hold_under_current_standards": len(holding),
        "rows": rows,
    }


def to_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Audit — do the supported claims hold under the current standards?",
        "",
        f"{result['hold_under_current_standards']} of {result['claims']} hold. "
        "Every input is traced to the result document that reported it; the "
        "arithmetic is in `experiments/audit_supported.py`.",
        "",
        "| claim | n | seeds | effect | MDE at this n | headroom | holds |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in result["rows"]:
        effect = row.get("effect")
        mde = row.get("mde_at_this_n")
        if row["kind"] == "absence":
            effect = "absence"
            mde = f"rate <= {row['smallest_rate_95pc_detectable']:.1%} undetectable"
        elif mde is None:
            mde = "n/a (deterministic)"
        lines.append(
            f"| {row['name']} | {row['n']} | {row['seeds']} | {effect} | "
            f"{mde} | {row['headroom'] if row['headroom'] is not None else '—'} | "
            f"{'**yes**' if row['holds'] else '**NO**'} |")
    lines += ["", "## Issues raised, per claim", ""]
    for row in result["rows"]:
        lines.append(f"**{row['name']}** — {row['source']}")
        if row["issues"]:
            for issue in row["issues"]:
                lines.append(f"- {issue}")
        else:
            lines.append("- nothing raised")
        lines.append(f"- _{row['note']}_")
        lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)
    result = run()
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
    text = json.dumps(result, indent=2) if args.as_json else to_markdown(result)
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
