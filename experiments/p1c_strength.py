"""P1c — prefer the chain whose weakest link is strongest.

Registered in `research/prereg/p1c-link-strength.md` before the change and
before holdout 2 existed. Uses the P1b harness with a different switch
(`chains.LINK_STRENGTH_SELECTION`) and a fresh holdout (indices 200–211).
Holdout 1 and the frozen test split are contaminated for this change and are
reported, not used.

    python -m experiments.p1c_strength
"""

from __future__ import annotations

import json
import subprocess
import sys

from experiments import p1b_links as base

HOLDOUT2 = "holdout_p1c"
SWITCH = "LINK_STRENGTH_SELECTION"


def to_markdown(r: dict) -> str:
    text = base.to_markdown(r)
    text = text.replace("# P1b — discriminating links for covering candidates",
                        "# P1c — prefer the chain whose weakest link is strongest")
    text = text.replace("[p1b-discriminating-links.md](../prereg/p1b-discriminating-links.md)",
                        "[p1c-link-strength.md](../prereg/p1c-link-strength.md)")
    text = text.replace("`python -m experiments.p1b_links`", "`python -m experiments.p1c_strength`")
    text = text.replace("[p1b-links.json](p1b-links.json)", "[p1c-strength.json](p1c-strength.json)")
    text = text.replace("fresh cases)", "fresh cases, holdout 2)")
    h1 = r["holdout1"]
    text += (f"\n**Holdout 1 (contaminated: P1c was diagnosed on it).** Before "
             f"{h1['chain_before']['sufficiency']:.3f}, after {h1['chain_after']['sufficiency']:.3f}.\n")
    return text


def main() -> int:
    print("holdout 2:", base.build_holdout(HOLDOUT2, range(200, 212)), "cases")
    r = {"dev": base.measure("dev", SWITCH), "holdout": base.measure(HOLDOUT2, SWITCH),
         "test": base.measure("test", SWITCH), "holdout1": base.measure(base.HOLDOUT, SWITCH)}
    r["verdict"] = base.verdict(r["dev"], r["holdout"])
    r["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                 text=True, cwd=base.HERE).stdout.strip()
    print(json.dumps(r["verdict"], indent=2))
    out = base.HERE / "research" / "results"
    (out / "p1c-strength.json").write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    (out / "p1c-strength.md").write_text(to_markdown(r), encoding="utf-8")
    return 0




def main_p1d() -> int:
    """P1d: holdout 3, multi_hop_3 primary (research/prereg/p1d-link-strength-mh3.md)."""
    from experiments import p1_chains as p1
    from research.bench.relevance_v2 import build as B

    name = "holdout_p1d"
    cases = [B.BUILDERS["multi_hop_3"](i) for i in range(300, 324)]
    B.shuffle_corpora(cases)
    (base.HERE / "research" / "bench" / "relevance_v2" / f"{name}.json").write_text(
        json.dumps({"benchmark": "relevance_v2", "split": name, "cases": cases}) + "\n", encoding="utf-8")
    h3 = base.measure(name, SWITCH)
    dev = base.measure("dev", SWITCH)
    b = h3["chain_before"]["by_family"]["multi_hop_3"]
    s = h3["chain_after"]["by_family"]["multi_hop_3"]
    c = h3["oracle"]
    mh4_ok = dev["chain_after"]["by_family"]["multi_hop_4"] >= dev["chain_before"]["by_family"]["multi_hop_4"]
    threshold = b + 0.4 * (c - b)
    verdict = ("INCONCLUSIVE (headroom too small)" if b >= 0.9
               else "SUPPORTED" if s >= threshold and mh4_ok else "NOT SUPPORTED")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=base.HERE).stdout.strip()
    r = {"holdout3": h3, "dev": dev, "B": b, "S": s, "C": c, "threshold": threshold,
         "dev_mh4_not_worse": mh4_ok, "verdict": verdict, "commit": commit,
         "cases": len(cases)}
    out = base.HERE / "research" / "results"
    (out / "p1d-strength-mh3.json").write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    (out / "p1d-strength-mh3.md").write_text(f"""# P1d — link-strength selection on three-hop chains

Registered in [p1d-link-strength-mh3.md](../prereg/p1d-link-strength-mh3.md)
before holdout 3 existed. Produced by `python -m experiments.p1c_strength --p1d`
at commit `{commit}`; raw numbers in [p1d-strength-mh3.json](p1d-strength-mh3.json).

**{verdict}.** On {len(cases)} fresh `multi_hop_3` cases (holdout 3), chain
sufficiency goes from **{b:.3f}** to **{s:.3f}** against an oracle of {c:.3f}
(threshold {threshold:.3f}). `multi_hop_4` on dev not worse: {mh4_ok}.

Cost: nodes explored {h3['chain_before']['nodes_explored']} → {h3['chain_after']['nodes_explored']}.

**What it does not establish.** Same templates as every other split: new
cases, not a new distribution. `reconstruct` is opt-in either way.
""", encoding="utf-8")
    print(json.dumps({k: v for k, v in r.items() if k not in ("holdout3", "dev")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main_p1d() if "--p1d" in sys.argv else main())
