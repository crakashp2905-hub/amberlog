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
    (out / "p1c-strength.json").write_text(json.dumps(r, indent=2) + "\n")
    (out / "p1c-strength.md").write_text(to_markdown(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
