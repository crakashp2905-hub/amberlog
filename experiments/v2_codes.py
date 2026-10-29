"""V2 — claim checks on equipment codes written with separators.

Registered in `research/prereg/v2-separated-codes.md` before this world
existed. Deterministic, no model. For each case, a fresh store is built with
background memories, an established author and an established fact. One
later write is then assessed with `validation.assess`. The baseline is the
same world scored with the parser as it was before the fix.

    python -m experiments.v2_codes
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from amberlog import Amberlog, conflicts
from amberlog.validation import assess

ROOT = Path(__file__).resolve().parent.parent
SEEDS = range(600, 605)
PER_FAMILY = 20
FAMILIES = ("poison_new_author", "poison_established_author", "honest_same_author",
            "honest_new_equipment", "honest_other_parameter", "risk_two_codes")
KINDS = ("hoist", "pump", "compressor", "generator", "conveyor", "chiller")
PARAMS = (("relief pressure", "bar", 6, 48), ("torque setting", "Nm", 20, 98),
          ("coolant flow", "l/min", 10, 90), ("trip current", "A", 11, 95))
LATER = (
    "Correction from the site survey: {kind} {code} {param} is now {value} {unit}.",
    "Per today's inspection the {param} on {kind} {code} should be {value} {unit}.",
    "{kind} {code}: revised {param} = {value} {unit}.",
    "Field note, {kind} {code}. Set the {param} to {value} {unit} going forward.",
    "New spec received for {kind} {code}; {param} {value} {unit}.",
)


def code_for(rng: random.Random, used: set[str]) -> str:
    while True:
        n = rng.randrange(10, 99)
        letters = "".join(rng.choice("BCDFGHKLMPRSTV") for _ in range(rng.choice((1, 2, 3))))
        fmt = rng.choice(("{L}-{n}", "{L}_00{n}", "{L}/{n}", "{L}-{n}B", "{l}-{n}"))
        code = fmt.format(L=letters, l=letters.lower(), n=n)
        if code.lower() not in used:
            used.add(code.lower())
            return code


def one_case(family: str, rng: random.Random) -> bool:
    """True if the later write is assessed suspicious."""
    fabric = Amberlog(auto_activate=True, hold_suspicious=False, encrypt_content=False)
    try:
        used: set[str] = set()
        established, other = "ag_tech_a", "ag_tech_b"
        for who in (established, other):
            for _ in range(3):
                kind, (param, unit, lo, hi) = rng.choice(KINDS), rng.choice(PARAMS)
                m = fabric.remember(who, f"{kind.title()} {code_for(rng, used)}: the {param} is "
                                         f"{rng.randrange(lo, hi)} {unit}.")
                fabric.validate(m, actor="reviewer")
        for _ in range(30):
            kind, (param, unit, lo, hi) = rng.choice(KINDS), rng.choice(PARAMS)
            fabric.remember(rng.choice((established, other)),
                            f"{kind.title()} {code_for(rng, used)}: the {param} is "
                            f"{rng.randrange(lo, hi)} {unit}.")
        kind = rng.choice(KINDS)
        (param, unit, lo, hi) = rng.choice(PARAMS)
        code = code_for(rng, used)
        true, wrong = rng.sample(range(lo, hi), 2)
        fact = fabric.remember(established, f"{kind.title()} {code}: the {param} is {true} {unit}.")
        fabric.validate(fact, actor="reviewer")
        template = rng.choice(LATER)
        if family == "poison_new_author":
            who, text = "ag_new_contractor", template.format(kind=kind, code=code, param=param,
                                                              value=wrong, unit=unit)
        elif family == "poison_established_author":
            who, text = other, template.format(kind=kind, code=code, param=param,
                                                value=wrong, unit=unit)
        elif family == "honest_same_author":
            who, text = established, template.format(kind=kind, code=code, param=param,
                                                      value=wrong, unit=unit)
        elif family == "honest_new_equipment":
            who, text = other, template.format(kind=kind, code=code_for(rng, used), param=param,
                                                value=wrong, unit=unit)
        elif family == "honest_other_parameter":
            p2, u2, lo2, hi2 = rng.choice([p for p in PARAMS if p[0] != param])
            who, text = other, template.format(kind=kind, code=code, param=p2,
                                                value=rng.randrange(lo2, hi2), unit=u2)
        else:  # risk_two_codes: a different valve on the first code's loop
            valve = code_for(rng, used)
            who, text = other, (f"On {kind} {code}'s loop, valve {valve}: the {param} is "
                                f"{wrong} {unit}.")
        later = fabric.remember(who, text)
        return assess(fabric, later).suspicious
    finally:
        fabric.close()


def run(parser: Callable[..., Any] | None = None) -> dict[str, Any]:
    import contextlib

    import amberlog.validation as validation

    out: dict[str, Any] = {}
    with contextlib.ExitStack() as stack:
        if parser is not None:
            stack.enter_context(mock.patch.object(conflicts, "claim", parser))
            stack.enter_context(mock.patch.object(validation, "claim", parser))
        for family in FAMILIES:
            per_seed = []
            for seed in SEEDS:
                rng = random.Random(f"v2/{family}/{seed}")
                per_seed.append(sum(one_case(family, rng) for _ in range(PER_FAMILY)) / PER_FAMILY)
            out[family] = {"suspicious": sum(per_seed) / len(per_seed), "by_seed": per_seed}
    return out


_OLD_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def old_claim(content: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """The parser before the fix, verbatim, as the baseline."""
    from amberlog.vectors import _STOPWORDS

    identifiers, words, values = set(), set(), set()
    for token in _OLD_TOKEN.findall(content.lower()):
        has_digit = any(ch.isdigit() for ch in token)
        has_alpha = any(ch.isalpha() for ch in token)
        if has_digit and has_alpha:
            identifiers.add(token)
        elif has_digit:
            values.add(token)
        elif token not in _STOPWORDS and len(token) > 1:
            words.add(token)
    return frozenset(identifiers), frozenset(words), frozenset(values)


def verdict(r: dict[str, Any]) -> dict[str, Any]:
    detect = {f: r[f]["suspicious"] for f in FAMILIES if f.startswith("poison")}
    honest = [r[f]["suspicious"] for f in FAMILIES if f.startswith("honest")]
    false_rate = sum(honest) / len(honest)
    return {"V2-D": "SUPPORTED" if all(v >= 0.90 for v in detect.values()) else "NOT SUPPORTED",
            "V2-F": "SUPPORTED" if false_rate <= 0.05 else "NOT SUPPORTED",
            "detection": detect, "honest_false_suspicious": false_rate,
            "risk_two_codes": r["risk_two_codes"]["suspicious"]}


def main() -> int:
    global SEEDS
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs=2, default=(600, 605))
    ap.add_argument("--out", default="v2-codes")
    a = ap.parse_args()
    SEEDS = range(*a.seeds)
    fixed, before = run(), run(old_claim)
    v = verdict(fixed)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    rows = "\n".join(f"| `{f}` | {before[f]['suspicious']:.3f} | **{fixed[f]['suspicious']:.3f}** |"
                     for f in FAMILIES)
    (ROOT / "research" / "results" / f"{a.out}.json").write_text(json.dumps(
        {"commit": commit, "fixed": fixed, "before_fix": before, "verdict": v}, indent=2) + "\n")
    (ROOT / "research" / "results" / f"{a.out}.md").write_text(f"""# V2 — claim checks on separated equipment codes

Registered in [v2-separated-codes.md](../prereg/v2-separated-codes.md) before this
world existed. Produced by `python -m experiments.v2_codes --seeds {SEEDS.start} {SEEDS.stop}` at commit `{commit}`;
raw numbers in [{a.out}.json]({a.out}.json). Seeds {SEEDS.start}–{SEEDS.stop - 1}, {PER_FAMILY} cases per
family per seed, deterministic, no model.

**V2-D {v['V2-D']}. V2-F {v['V2-F']}.** False-alarm rate on honest writes:
{v['honest_false_suspicious']:.3f}.

Rate at which the later write is assessed **suspicious** (held for review):

| family | parser before the fix | parser now |
|---|---|---|
{rows}

`risk_two_codes` decides nothing. It measures the registered risk of taking the
first code in a sentence as its subject.
""")
    print(json.dumps(v, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
