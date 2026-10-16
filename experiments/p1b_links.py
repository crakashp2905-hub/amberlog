"""P1b — discriminating links for covering candidates.

Registered in `research/prereg/p1b-discriminating-links.md` before the change.
Runs the chain with `chains.DISCRIMINATING_COVER` off and on, over the same
cases:

- `dev`: the relevance_v2 dev split, chain families;
- `holdout`: 24 fresh chain cases built by the frozen generator at indices
  100–111, written to a git-ignored file and scored once;
- `test`: the frozen test split, **contaminated** for this change (P1 saw the
  wrong-axle failure there), reported and never used as evidence.

    python -m research.bench.relevance_v2.build   # dev/test, if not built
    python -m experiments.p1b_links
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from experiments import p1_chains as p1
from experiments import relevance_bench as rb
from memory_fabric import chains

HERE = Path(__file__).resolve().parent.parent
HOLDOUT = "holdout_p1b"
HOLDOUT_INDICES = range(100, 112)


def build_holdout() -> int:
    from research.bench.relevance_v2 import build as B

    cases = [B.BUILDERS[f](i) for f in p1.CHAIN_FAMILIES for i in HOLDOUT_INDICES]
    B.shuffle_corpora(cases)
    path = HERE / "research" / "bench" / "relevance_v2" / f"{HOLDOUT}.json"
    path.write_text(json.dumps({"benchmark": "relevance_v2", "split": HOLDOUT,
                                "cases": cases}) + "\n", encoding="utf-8")
    return len(cases)


def pooled(outcomes) -> float:
    rows = [o for o in outcomes if o.sufficient is not None]
    return sum(1 for o in rows if o.sufficient) / len(rows) if rows else 0.0


def measure(split: str) -> dict[str, Any]:
    out: dict[str, Any] = {"split": split}
    for name, flag in (("chain_before", False), ("chain_after", True)):
        chains.DISCRIMINATING_COVER = flag
        try:
            outcomes = p1.run_chain(split, k=p1.DEFAULT_K, families=p1.CHAIN_FAMILIES)
        finally:
            chains.DISCRIMINATING_COVER = False
        out[name] = {
            "sufficiency": pooled(outcomes),
            "by_family": {f: pooled([o for o in outcomes if o.family == f])
                          for f in p1.CHAIN_FAMILIES},
            "nodes_explored": p1.summarise(outcomes)["nodes_explored"],
            "mean_steps": p1.summarise(outcomes)["mean_steps"],
            "cases": len(outcomes),
        }
    result = rb.run(split, k=p1.DEFAULT_K, benchmark=p1.BENCHMARK, arms=["lexical", "oracle"])
    for arm in ("lexical", "oracle"):
        rows = [r for r in result["_reports"][arm].cases
                if r.family in p1.CHAIN_FAMILIES and r.sufficient is not None]
        out[arm] = sum(1 for r in rows if r.sufficient) / len(rows) if rows else 0.0
    return out


def verdict(dev: dict[str, Any], holdout: dict[str, Any]) -> dict[str, Any]:
    b = holdout["chain_before"]["sufficiency"]
    s = holdout["chain_after"]["sufficiency"]
    ceiling = holdout["oracle"]
    v: dict[str, Any] = {"B": b, "S": s, "ceiling": ceiling,
                         "threshold": b + 0.4 * (ceiling - b)}
    dev_ok = dev["chain_after"]["sufficiency"] >= dev["chain_before"]["sufficiency"]
    v["dev_not_worse"] = dev_ok
    above = [a for a in ("chain_before", "chain_after")
             if holdout[a]["sufficiency"] > ceiling + 1e-9]
    v["arms_above_ceiling"] = above
    if b >= 0.9:
        v["verdict"] = "INCONCLUSIVE (headroom too small)"
    elif s >= v["threshold"] and dev_ok:
        v["verdict"] = "SUPPORTED"
    else:
        v["verdict"] = "NOT SUPPORTED"
    v["closed_share"] = (s - b) / (ceiling - b) if ceiling > b else None
    return v


def to_markdown(r: dict[str, Any]) -> str:
    v = r["verdict"]

    def row(name: str, d: dict[str, Any]) -> str:
        return (f"| {name} | {d['lexical']:.3f} | {d['chain_before']['sufficiency']:.3f} "
                f"| **{d['chain_after']['sufficiency']:.3f}** | {d['oracle']:.3f} "
                f"| {d['chain_before']['by_family']['multi_hop_4']:.3f} → "
                f"{d['chain_after']['by_family']['multi_hop_4']:.3f} "
                f"| {d['chain_before']['nodes_explored']} → {d['chain_after']['nodes_explored']} |")

    closed = "—" if v["closed_share"] is None else f"{v['closed_share']:.0%}"
    return f"""# P1b — discriminating links for covering candidates

Registered in [p1b-discriminating-links.md](../prereg/p1b-discriminating-links.md)
before the change. Produced by `python -m experiments.p1b_links` at commit
`{r['commit']}`; raw numbers in [p1b-links.json](p1b-links.json).

**{v['verdict']}.** On the fresh holdout, the chain's sufficiency goes from
{v['B']:.3f} to {v['S']:.3f} against an oracle ceiling of {v['ceiling']:.3f}
(threshold {v['threshold']:.3f}; {closed} of the headroom closed). Dev not
worse: {v['dev_not_worse']}. Arms above the ceiling: {v['arms_above_ceiling'] or 'none'}.

Sufficiency, pooled over `multi_hop_3` and `multi_hop_4`, k = {p1.DEFAULT_K}:

| split | lexical | chain before | chain after | oracle | `multi_hop_4` before → after | nodes explored before → after |
|---|---|---|---|---|---|---|
{row("dev (" + str(r['dev']['chain_before']['cases']) + " cases)", r['dev'])}
{row("**holdout** (" + str(r['holdout']['chain_before']['cases']) + " fresh cases)", r['holdout'])}
{row("test, *contaminated*", r['test'])}

The **test** row is not evidence. P1 inspected a case there and saw the
failure this change targets, so the change was designed with that split in
view. It is printed so the reader can see it was not hidden.

**What it does not establish.** The holdout is generated by the same templates
as dev and test, so it is new cases, not a new distribution. Only the chain
families are measured. `reconstruct` remains opt-in either way; `retrieve` is
the default and is unchanged.
"""


def main() -> int:
    n = build_holdout()
    print(f"holdout: {n} cases built")
    r = {s: measure(s) for s in ("dev", HOLDOUT, "test")}
    r["holdout"] = r.pop(HOLDOUT)
    r["verdict"] = verdict(r["dev"], r["holdout"])
    r["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                 text=True, cwd=HERE).stdout.strip()
    print(json.dumps(r["verdict"], indent=2))
    out = HERE / "research" / "results"
    (out / "p1b-links.json").write_text(json.dumps(r, indent=2) + "\n")
    (out / "p1b-links.md").write_text(to_markdown(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
