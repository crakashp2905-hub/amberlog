"""The AGENTS.md 8a-8d checks as code (MF-033), run on every study's arm table.

- 8a: the threshold is a share of measured headroom, `bar(B, O, share)`;
  `headroom_ok` refuses a study whose ceiling leaves nothing to gain.
- 8b: no arm may beat the oracle; an arm above it proves the oracle wrong.
- 8c: no registered baseline may max the primary metric.
- 8d: the baseline is measured in this run, on this metric, k and split —
  `baseline_measured` checks the provenance fields say so.
"""

from __future__ import annotations

from typing import Any, Mapping


def bar(baseline: float, oracle: float, share: float) -> float:
    return baseline + share * (oracle - baseline)


def headroom_ok(baseline: float, oracle: float, minimum: float = 0.02) -> bool:
    return oracle - baseline >= minimum


def arms_above_oracle(scores: Mapping[str, float], oracle: str = "oracle", tol: float = 1e-9) -> list[str]:
    return [a for a, s in scores.items() if a != oracle and s > scores[oracle] + tol]


def baselines_maxing(scores: Mapping[str, float], baselines: list[str], maximum: float = 1.0,
                     tol: float = 1e-9) -> list[str]:
    return [b for b in baselines if scores.get(b, 0.0) >= maximum - tol]


def baseline_measured(provenance: Mapping[str, Any], metric: str, k: int | None, split: str) -> bool:
    return (provenance.get("measured_in_this_run") is True and provenance.get("metric") == metric
            and provenance.get("k") == k and provenance.get("split") == split)


def sanity(scores: Mapping[str, float], baselines: list[str], oracle: str = "oracle") -> dict[str, Any]:
    above = arms_above_oracle(scores, oracle)
    maxed = baselines_maxing(scores, baselines, maximum=scores[oracle])
    return {"arms_above_oracle": above, "baselines_at_ceiling": maxed,
            "ok": not above and not maxed}
