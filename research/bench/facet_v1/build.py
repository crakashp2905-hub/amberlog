"""facet_v1 — discrimination when the deciding facet is *implied*.

## Why

relevance_v2's `facet_trap` was the family built to be hardest: every statement
of the asked predicate one facet from the answer, same register, one
discriminating token in twelve. `lexical` scores **1.000** on it.

The reason is simple in hindsight and was written into the README as a caveat
before the run: **the query names every facet**, so the discriminating token is
present in both the query and the answer, and IDF separates them cleanly. One
facet apart in *form* is not one facet apart in *difficulty*.

So the deciding facet has to be **absent from the answer-bearing memory**, and
present in the wrong ones. That inverts the signal a token-overlap retriever
relies on: the memory that answers the question lacks the query's most
discriminating word, and every memory that has it is wrong.

## The control is the point

`stated_control` asks the **same questions** about the **same facts** with the
facet stated plainly. It is a quarter of the fixture and it is what
`facet_trap` lacked: if `lexical` scores high on the control and low on the
three implied families, the implication is what is hard, and that is measured
rather than claimed. If it scores high on both, this fixture has repeated
`facet_trap`'s mistake and should say so.

## Families

| family | how the facet is implied | the trap |
|---|---|---|
| `implied_by_exclusion` | the answer names the seasons it does *not* apply to | every memory containing the asked season is wrong |
| `implied_by_default` | a general rule with an exception list the asked case is not on | the answer names neither the unit nor the site |
| `implied_by_paraphrase` | the site and unit appear only under other names | no token the query uses appears in the answer |
| `stated_control` | not implied — stated | none. The baseline for the other three |

## Scope

A **focused fixture, not a benchmark**: four families, four cases each, one
question, ~205 memories a case. relevance_v2 stays byte-for-byte as committed,
because [its ceiling](../../results/relevance-v2-ceiling.md) was measured
against those digests. Padding and every label guard come from relevance_v2's
own `case()` — the answer-key leak assertion in particular, which matters more
here than anywhere: three of these four families work by *withholding* the
query's tokens from the answer, so a value appearing in a near-miss would make
the whole design measure the opposite of what it claims.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent.parent))

from research.bench.relevance_v2.build import (  # noqa: E402
    case, fillers, mem,
)

PAD = 200
PER_FAMILY = 4

# A value domain of its own, disjoint from every relevance_v2 topic, so a
# padding memory can never state an answer here.
PRESSURES = ("2.3 bar", "2.7 bar", "3.1 bar", "3.9 bar", "4.3 bar", "4.7 bar",
             "5.1 bar", "5.9 bar")
SITES = ("coastal", "inland", "northern", "harbour", "quarry", "estuary")
UNITS = ("tug-1", "tug-3", "crane-2", "crane-5", "forklift-9", "hoist-6")
SEASONS = ("winter", "summer", "monsoon")
# The two sites a default rule excepts. Fixed, so no asked site is ever on it.
EXCEPTED = ("harbour", "quarry")
PARAPHRASE_SITE = {"coastal": "seaward", "inland": "landward",
                   "northern": "upper", "estuary": "tidal"}
PARAPHRASE_UNIT = {"tug-1": "the number one tug", "tug-3": "the number three tug",
                   "crane-2": "the number two crane", "crane-5": "the number five crane",
                   "forklift-9": "the number nine lift truck",
                   "hoist-6": "the number six hoist"}


def _digest(*parts: str) -> int:
    return int.from_bytes(
        hashlib.blake2b("\x1f".join(parts).encode("utf-8"), digest_size=8).digest(),
        "big")


def _pick(case_id: str, *, paraphrasable: bool = False,
          exceptable: bool = True) -> dict:
    d = _digest("facet_v1", case_id)
    sites = tuple(PARAPHRASE_SITE) if paraphrasable else SITES
    if not exceptable:
        sites = tuple(s for s in sites if s not in EXCEPTED)
    return {
        "site": sites[(d >> 3) % len(sites)],
        "unit": UNITS[(d >> 11) % len(UNITS)],
        "season": SEASONS[(d >> 19) % len(SEASONS)],
    }


def _values(case_id: str, count: int) -> list[str]:
    """Distinct values, so a near-miss can never carry the answer."""
    rng = random.Random(f"facet_v1/values/{case_id}")
    pool = list(PRESSURES)
    rng.shuffle(pool)
    assert count <= len(pool), count
    return pool[:count]


def _pad(case_id: str) -> list[dict]:
    # tyre_pressure excluded: it is the predicate under test, and a padding
    # memory stating it for any facet tuple would be a near-miss nobody wrote.
    return fillers("tyre_pressure", random.Random(f"facet_v1/{case_id}"), PAD)


def _question(unit: str, site: str, season: str) -> str:
    return (f"What is the {season} tyre pressure for {unit} at the "
            f"{site} site?")


# --- family: implied_by_exclusion -------------------------------------------


def build_implied_by_exclusion(i: int) -> dict:
    """The answer names the seasons it does *not* cover.

    Every memory containing the asked season is wrong, and the one that answers
    does not contain it. A token-overlap retriever is actively misled rather
    than merely unhelped.
    """
    cid = f"implied_by_exclusion-{i + 1:02d}"
    p = _pick(cid)
    unit, site, season = p["unit"], p["site"], p["season"]
    others = [s for s in SEASONS if s != season]
    v = _values(cid, 5)
    corpus = [
        mem("a1", f"{unit} at the {site} site runs {v[0]} outside the "
                  f"{others[0]} and {others[1]} months.", entities=[unit, site]),
        # Same unit, same site, the seasons that are excluded -- and these do
        # name the asked season's siblings, so the corpus is self-consistent.
        mem("n1", f"{unit} at the {site} site runs {v[1]} in {others[0]}.",
            entities=[unit, site]),
        mem("n2", f"{unit} at the {site} site runs {v[2]} in {others[1]}.",
            entities=[unit, site]),
        # Memories that DO contain the asked season, and are all wrong.
        mem("n3", f"{unit} at the {SITES[(SITES.index(site) + 1) % len(SITES)]} "
                  f"site runs {v[3]} in {season}.", entities=[unit]),
        mem("n4", f"{UNITS[(UNITS.index(unit) + 1) % len(UNITS)]} at the {site} "
                  f"site runs {v[4]} in {season}.", entities=[site]),
    ]
    pad = _pad(cid)
    return case(
        cid, "implied_by_exclusion",
        _question(unit, site, season),
        corpus + pad,
        {
            "relevant": ["a1"], "critical": ["a1"],
            "irrelevant": ["n1", "n2", "n3", "n4"] + [m["id"] for m in pad],
            "roles": {"a1": "necessary"},
            "requirements": [{
                "req_id": "q1",
                "description": f"a figure applying to {unit} at {site} in {season}",
                "satisfied_by": ["a1"], "critical": True,
            }],
            "answer_contains": [v[0], v[0].replace(" ", "")],
        },
        f"The answer covers {season} by excluding the other two seasons and "
        f"never names it. Both memories that do name {season} are about a "
        f"different site or a different unit, so the query's most "
        f"discriminating token appears only in wrong answers.",
        entities=[unit, site],
    )


# --- family: implied_by_default ---------------------------------------------


def build_implied_by_default(i: int) -> dict:
    """A general rule with an exception list the asked case is not on.

    The answer names neither the unit nor the site, so it shares almost nothing
    with the query, while the near-misses name both.
    """
    cid = f"implied_by_default-{i + 1:02d}"
    p = _pick(cid, exceptable=False)
    unit, site, season = p["unit"], p["site"], p["season"]
    assert site not in EXCEPTED, (cid, site)
    v = _values(cid, 4)
    corpus = [
        mem("a1", f"All yard vehicles run {v[0]} in {season}, except at the "
                  f"{EXCEPTED[0]} and {EXCEPTED[1]} sites.", entities=[]),
        mem("n1", f"{unit} at the {EXCEPTED[0]} site runs {v[1]} in {season}.",
            entities=[unit, EXCEPTED[0]]),
        mem("n2", f"{unit} at the {EXCEPTED[1]} site runs {v[2]} in {season}.",
            entities=[unit, EXCEPTED[1]]),
        mem("n3", f"{unit} at the {site} site was last re-tyred in March.",
            entities=[unit, site]),
        mem("n4", f"Tyre pressures at the {site} site are logged weekly by the "
                  f"{unit} operator.", entities=[unit, site]),
    ]
    pad = _pad(cid)
    return case(
        cid, "implied_by_default",
        _question(unit, site, season),
        corpus + pad,
        {
            "relevant": ["a1"], "critical": ["a1"],
            "irrelevant": ["n1", "n2", "n3", "n4"] + [m["id"] for m in pad],
            "roles": {"a1": "necessary"},
            "requirements": [{
                "req_id": "q1",
                "description": f"a figure that applies to {unit} at {site}, by "
                               f"rule or by statement",
                "satisfied_by": ["a1"], "critical": True,
            }],
            "answer_contains": [v[0], v[0].replace(" ", "")],
        },
        f"The default rule covers {site} because {site} is not on its exception "
        f"list, and it names neither the unit nor the site. Two memories name "
        f"both and give the figures for the excepted sites; two more name both "
        f"and answer a different question.",
        entities=[unit, site],
    )


# --- family: implied_by_paraphrase ------------------------------------------


def build_implied_by_paraphrase(i: int) -> dict:
    """The facet values appear only under other names, with no glossary.

    Deliberately the one family a lexical retriever cannot solve even in
    principle: no token the query uses appears in the answer. It is here as the
    separation between vocabulary and reasoning -- a trained embedder should
    close this one and not the other two.
    """
    cid = f"implied_by_paraphrase-{i + 1:02d}"
    p = _pick(cid, paraphrasable=True)
    unit, site, season = p["unit"], p["site"], p["season"]
    v = _values(cid, 4)
    other_site = next(s for s in PARAPHRASE_SITE if s != site)
    other_unit = next(u for u in UNITS if u != unit)
    corpus = [
        mem("a1", f"{PARAPHRASE_UNIT[unit]} on the {PARAPHRASE_SITE[site]} berth "
                  f"takes {v[0]} in the cold season.", entities=[]),
        mem("n1", f"{PARAPHRASE_UNIT[other_unit]} on the {PARAPHRASE_SITE[site]} "
                  f"berth takes {v[1]} in the cold season.", entities=[]),
        mem("n2", f"{PARAPHRASE_UNIT[unit]} on the {PARAPHRASE_SITE[other_site]} "
                  f"berth takes {v[2]} in the cold season.", entities=[]),
        mem("n3", f"{unit} at the {site} site is due for inspection in {season}.",
            entities=[unit, site]),
    ]
    pad = _pad(cid)
    return case(
        cid, "implied_by_paraphrase",
        _question(unit, site, season) if season == "winter" else
        f"What is the winter tyre pressure for {unit} at the {site} site?",
        corpus + pad,
        {
            "relevant": ["a1"], "critical": ["a1"],
            "irrelevant": ["n1", "n2", "n3"] + [m["id"] for m in pad],
            "roles": {"a1": "necessary"},
            "requirements": [{
                "req_id": "q1",
                "description": "the figure for this unit and site, under any name",
                "satisfied_by": ["a1"], "critical": True,
            }],
            "answer_contains": [v[0], v[0].replace(" ", "")],
        },
        "Unit, site and season all appear under other names, and no glossary "
        "memory links them. The only memory using the query's own vocabulary "
        "answers a different question. Unsolvable by token overlap in "
        "principle, which is what separates a vocabulary gap from a reasoning "
        "one.",
        entities=[unit, site],
    )


# --- family: stated_control -------------------------------------------------


def build_stated_control(i: int) -> dict:
    """The same question and the same fact, stated plainly.

    The comparison `facet_trap` lacked. Any difficulty the three implied
    families show is only attributable to the implication if this one is easy.
    """
    cid = f"stated_control-{i + 1:02d}"
    # The same draw as the exclusion family's matching case, so the control is
    # over the same unit, site and season rather than a fresh sample.
    p = _pick(f"implied_by_exclusion-{i + 1:02d}")
    unit, site, season = p["unit"], p["site"], p["season"]
    others = [s for s in SEASONS if s != season]
    v = _values(f"implied_by_exclusion-{i + 1:02d}", 5)
    corpus = [
        mem("a1", f"{unit} at the {site} site runs {v[0]} in {season}.",
            entities=[unit, site]),
        mem("n1", f"{unit} at the {site} site runs {v[1]} in {others[0]}.",
            entities=[unit, site]),
        mem("n2", f"{unit} at the {site} site runs {v[2]} in {others[1]}.",
            entities=[unit, site]),
        mem("n3", f"{unit} at the {SITES[(SITES.index(site) + 1) % len(SITES)]} "
                  f"site runs {v[3]} in {season}.", entities=[unit]),
        mem("n4", f"{UNITS[(UNITS.index(unit) + 1) % len(UNITS)]} at the {site} "
                  f"site runs {v[4]} in {season}.", entities=[site]),
    ]
    pad = _pad(cid)
    return case(
        cid, "stated_control",
        _question(unit, site, season),
        corpus + pad,
        {
            "relevant": ["a1"], "critical": ["a1"],
            "irrelevant": ["n1", "n2", "n3", "n4"] + [m["id"] for m in pad],
            "roles": {"a1": "necessary"},
            "requirements": [{
                "req_id": "q1", "description": "the asked tuple, stated",
                "satisfied_by": ["a1"], "critical": True,
            }],
            "answer_contains": [v[0], v[0].replace(" ", "")],
        },
        "Identical to the matching `implied_by_exclusion` case in unit, site, "
        "season, value and distractors -- except that the answer states the "
        "season instead of excluding the other two.",
        entities=[unit, site],
    )


BUILDERS = {
    "implied_by_exclusion": build_implied_by_exclusion,
    "implied_by_default": build_implied_by_default,
    "implied_by_paraphrase": build_implied_by_paraphrase,
    "stated_control": build_stated_control,
}


def build_all() -> list[dict]:
    return [BUILDERS[f](i) for f in BUILDERS for i in range(PER_FAMILY)]


def write(out: pathlib.Path | None = None) -> dict:
    out = out or HERE
    cases = build_all()
    for c in cases:
        random.Random(f"facet_v1/shuffle/{c['case_id']}").shuffle(c["corpus"])
    dev, test, seen = [], [], {}
    for c in cases:
        seen[c["family"]] = seen.get(c["family"], 0) + 1
        (test if seen[c["family"]] % 2 == 0 else dev).append(c)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "benchmark": "facet_v1",
        "built_at": "2026-10-12",
        "note": ("A focused fixture for one question, not a benchmark. "
                 "Generated; these digests are the reproducibility claim."),
        "per_family": PER_FAMILY,
        "families": sorted(BUILDERS),
        "splits": {},
    }
    for name, chunk in (("dev", dev), ("test", test)):
        text = json.dumps({
            "benchmark": "facet_v1", "split": name,
            "built_at": manifest["built_at"], "cases": chunk,
        }, indent=2) + "\n"
        (out / f"{name}.json").write_text(text, encoding="utf-8")
        manifest["splits"][name] = {
            "cases": len(chunk),
            "memories": sum(c["corpus_size"] for c in chunk),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "bytes": len(text.encode("utf-8")),
        }
    (out / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    m = write()
    for name, info in m["splits"].items():
        print(f"{name}: {info['cases']} cases, {info['memories']} memories, "
              f"{info['bytes'] / 1e6:.2f} MB")
        print(f"  sha256 {info['sha256']}")
    print("families:", ", ".join(m["families"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
