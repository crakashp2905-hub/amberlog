"""propagation_v1 — the cases that actually separate propagation rules.

## Why this exists

P3 was registered against relevance_v2's `shared_root` / `independent_support`
pair, ran, and **abandoned on both splits** — not because the rules are
indistinguishable but because that pair cannot tell them apart:

| arm | stale cited / case | unnecessary invalidation |
|---|---|---|
| `no_propagation` | 3.333 | 0.000 |
| `blanket_invalidation` | **0.000** | **0.000** |
| `graph_traversal` | **0.000** | **0.000** |
| `source_root_grouping` | 1.000 | 0.000 |
| `oracle_propagation` | 0.000 | 0.000 |

Two one-line baselines score exactly the oracle on both primary metrics, so
there is no headroom to divide and the registered clause fires. The matched
pair was supposed to punish blanket invalidation for discarding a standing
source; it does not, because in `independent_support` the standing load-cell
trial has a **different source root** by construction. A rule that withholds by
root identity never touches it.

My prediction 1 said blanket invalidation would win on stale citations and lose
on unnecessary invalidation. It won both. The registration even named the
condition — *"it discards nothing wrongly only because the standing trial has a
different root"* — and I built the pair anyway without the case where that
stops being true.

## What discriminates, and why each family is here

The separating structure is a **retracted non-root**: a memory that is itself
derived, is retracted, and sits under a root that still carries standing
evidence. Then withholding by root identity is wrong and following edges is
right, and the two rules finally disagree.

| family | structure | which rules should fail |
|---|---|---|
| `retracted_intermediate` | standing root → retracted interim analysis → two restatements; plus one conclusion drawn straight from the root | **blanket** discards the standing conclusion. Traversal is correct |
| `deep_chain` | root → A → B → C, retracted at A, with a sibling branch off the root | **blanket** discards the sibling; `no_propagation` cites three stale layers |
| `copied_document` | the same document ingested twice under separate roots, one retracted | **every rule here fails.** Root identity and parent edges both say the copy is independent evidence |
| `independent_reconfirmation` | retracted root with stale derivations, plus a later direct observation of the same fact under its own root | **blanket** is correct by luck; the test is whether a rule cites the new observation *instead of* a stale restatement rather than as well as |

`copied_document` is included knowing nothing solves it, because a comparison
that only contains cases some arm wins is a comparison arranged to have a
winner. The product's own grouping is by source root, so a re-ingested document
is two roots and two votes — the exact failure `_group_by_root` was written to
prevent, surviving because provenance is recorded per ingestion.

## Scope, stated plainly

This is a **focused fixture, not a benchmark**: four families, four cases each,
one question. It does not replace relevance_v2 and carries no ranking claim.
relevance_v2 stays byte-for-byte as committed, because
[relevance-v2-ceiling.md](../../results/relevance-v2-ceiling.md) was measured
against those digests and appending a family would have invalidated them.

Corpora are padded to ~200 memories with relevance_v2's filler machinery so
retrieval is non-trivial, and the guards are v2's own `case()` — the answer-key
leak assertion, the parent-edge shape check, and the every-memory-is-labelled
check all apply here unchanged.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import random

HERE = pathlib.Path(__file__).resolve().parent
_V2 = HERE.parent / "relevance_v2"

import sys  # noqa: E402

sys.path.insert(0, str(HERE.parent.parent.parent))

from research.bench.relevance_v2.build import (  # noqa: E402
    BY_NAME, SITES, T0, case, fillers, mem, value_for,
)

PAD = 200
PER_FAMILY = 4


def _digest(*parts: str) -> int:
    return int.from_bytes(
        hashlib.blake2b("\x1f".join(parts).encode("utf-8"), digest_size=8).digest(),
        "big")


def _pad(case_id: str, exclude_topic: str = "lift_limit") -> list[dict]:
    return fillers(exclude_topic, random.Random(f"propagation_v1/{case_id}"), PAD)


def _site(case_id: str) -> str:
    return SITES[_digest("site", case_id) % len(SITES)]


def _load(case_id: str) -> int:
    # 31..39 so the figures cannot collide with the `lift_limit` value domain
    # used for padding -- the same collision that leaked answers in v2.
    return 31 + (_digest("load", case_id) % 5) * 2


# --- family: retracted_intermediate -----------------------------------------


def build_retracted_intermediate(i: int) -> dict:
    """The case the v2 pair was missing.

    r1 stands. s1 derives from r1, is retracted, and two restatements derive
    from s1. g1 derives from r1 directly and is the correct answer. Everything
    shares root r1, so a rule that withholds by root identity discards g1 and
    answers nothing.
    """
    cid = f"retracted_intermediate-{i + 1:02d}"
    site, load = _site(cid), _load(cid)
    good, bad = load, load - 7
    corpus = [
        mem("r1", f"Survey S-204 measured the {site} quay bearing capacity across "
                  f"eight grid points.", entities=[site]),
        mem("s1", f"Interim analysis of S-204 put the {site} quay at {bad} tonnes "
                  f"per square metre.", entities=[site],
            method="derived", parents=[["r1", 1]], source_root="r1",
            lifecycle_state="quarantined"),
        mem("d1", f"The {site} quay is rated for {bad} tonnes per square metre.",
            entities=[site], method="derived", parents=[["s1", 1]], source_root="r1"),
        mem("d2", f"Lift planning for {site} assumes {bad} tonnes per square metre.",
            entities=[site], method="derived", parents=[["s1", 1]], source_root="r1"),
        mem("g1", f"Final analysis of S-204 gives the {site} quay {good} tonnes per "
                  f"square metre.", entities=[site],
            method="derived", parents=[["r1", 1]], source_root="r1"),
    ]
    pad = _pad(cid)
    return case(
        cid, "retracted_intermediate",
        f"What bearing capacity should the {site} quay lift plan use?",
        corpus + pad,
        {
            "relevant": ["r1", "g1"], "critical": ["g1"],
            "irrelevant": ["s1", "d1", "d2"] + [m["id"] for m in pad],
            "must_not_expose": ["s1"],
            "stale": ["d1", "d2"],
            "roles": {"g1": "necessary", "r1": "background",
                      "s1": "withdrawn", "d1": "stale_derived", "d2": "stale_derived"},
            "requirements": [{
                "req_id": "q1",
                "description": "a figure that does not descend from the withdrawn "
                               "interim analysis",
                "satisfied_by": ["g1"], "critical": True,
            }],
            "answer_contains": [f"{good} tonnes per square metre", f"{good} t/m2"],
        },
        "The retracted memory is an intermediate, not a root. Withholding by "
        "root identity discards the final analysis along with the interim one "
        "and answers nothing; following parent edges withholds exactly the two "
        "restatements.",
        entities=[site],
    )


# --- family: deep_chain -----------------------------------------------------


def build_deep_chain(i: int) -> dict:
    cid = f"deep_chain-{i + 1:02d}"
    site, load = _site(cid), _load(cid)
    bad = load - 6
    corpus = [
        mem("r1", f"Inspection file INS-77 covers the {site} quay and its approach "
                  f"roads.", entities=[site]),
        mem("a1", f"Per INS-77 the {site} quay deck is rated {bad} tonnes per square "
                  f"metre.", entities=[site], method="derived",
            parents=[["r1", 1]], source_root="r1", lifecycle_state="quarantined"),
        mem("b1", f"The {site} quay deck rating is {bad} tonnes per square metre.",
            entities=[site], method="derived", parents=[["a1", 1]], source_root="r1"),
        mem("c1", f"The {site} mobile-crane plan is built on a {bad} t/m2 deck.",
            entities=[site], method="derived", parents=[["b1", 1]], source_root="r1"),
        mem("x1", f"Per INS-77 the {site} approach road is rated {load} tonnes per "
                  f"square metre.", entities=[site], method="derived",
            parents=[["r1", 1]], source_root="r1"),
    ]
    pad = _pad(cid)
    return case(
        cid, "deep_chain",
        f"What is the rated capacity of the {site} approach road?",
        corpus + pad,
        {
            "relevant": ["r1", "x1"], "critical": ["x1"],
            "irrelevant": ["a1", "b1", "c1"] + [m["id"] for m in pad],
            "must_not_expose": ["a1"],
            "stale": ["b1", "c1"],
            "roles": {"x1": "necessary", "r1": "background", "a1": "withdrawn",
                      "b1": "stale_derived", "c1": "stale_derived"},
            "requirements": [{
                "req_id": "q1", "description": "the approach-road figure from INS-77",
                "satisfied_by": ["x1"], "critical": True,
            }],
            "answer_contains": [f"{load} tonnes per square metre", f"{load} t/m2"],
        },
        "Three layers of derivation below the retracted memory, and a sibling "
        "branch off the same root that is unaffected. The asked question is "
        "about the sibling, so withholding by root identity answers nothing "
        "while leaving the deck chain untouched is three stale citations.",
        entities=[site],
    )


# --- family: copied_document ------------------------------------------------


def build_copied_document(i: int) -> dict:
    """Nothing here solves this, and that is the point.

    The same document ingested twice. Provenance records two roots because
    there were two ingestions, so root identity and parent edges both call the
    copy independent evidence. `_group_by_root` sees two roots and keeps both,
    which is the failure it was written to prevent.
    """
    cid = f"copied_document-{i + 1:02d}"
    site, load = _site(cid), _load(cid)
    text = (f"Contractor bulletin CB-9: the {site} quay is limited to {load - 5} "
            f"tonnes per square metre pending re-survey.")
    corpus = [
        mem("r1", text, entities=[site], lifecycle_state="quarantined"),
        # Re-ingested from the shared drive months later, under its own root.
        mem("r2", text + " (copy filed by the site office)", entities=[site],
            source_root="r2"),
        mem("d1", f"The {site} quay limit is {load - 5} tonnes per square metre per "
                  f"CB-9.", entities=[site], method="derived",
            parents=[["r2", 1]], source_root="r2"),
        mem("g1", f"Load-cell trial LC-31 measured the {site} quay at {load} tonnes "
                  f"per square metre.", entities=[site], source_root="g1"),
    ]
    pad = _pad(cid)
    return case(
        cid, "copied_document",
        f"What bearing capacity should the {site} quay lift plan use?",
        corpus + pad,
        {
            "relevant": ["g1"], "critical": ["g1"],
            "irrelevant": ["r1", "r2", "d1"] + [m["id"] for m in pad],
            "must_not_expose": ["r1"],
            # r2 and d1 restate a retracted document under a root nothing marks
            # as retracted. They are stale in substance and standing in
            # provenance, which is why no rule in this experiment catches them.
            "stale": ["r2", "d1"],
            "roles": {"g1": "necessary", "r1": "withdrawn",
                      "r2": "stale_copy", "d1": "stale_derived"},
            "requirements": [{
                "req_id": "q1",
                "description": "a measurement that is not the withdrawn bulletin "
                               "or a copy of it",
                "satisfied_by": ["g1"], "critical": True,
            }],
            "answer_contains": [f"{load} tonnes per square metre", f"{load} t/m2"],
        },
        "The withdrawn bulletin was re-ingested under a separate root, so "
        "provenance calls the copy independent. Every rule under test treats "
        "it as standing evidence, including the product's grouping, which sees "
        "two roots and keeps both votes.",
        entities=[site],
    )


# --- family: independent_reconfirmation -------------------------------------


def build_independent_reconfirmation(i: int) -> dict:
    cid = f"independent_reconfirmation-{i + 1:02d}"
    site, load = _site(cid), _load(cid)
    corpus = [
        mem("r1", f"Survey S-310 measured the {site} quay at {load} tonnes per "
                  f"square metre.", entities=[site], lifecycle_state="quarantined"),
        mem("d1", f"The {site} quay is rated for {load} tonnes per square metre.",
            entities=[site], method="derived", parents=[["r1", 1]], source_root="r1"),
        mem("d2", f"The {site} lift plan assumes {load} t/m2.", entities=[site],
            method="derived", parents=[["r1", 1]], source_root="r1"),
        mem("g1", f"Load-cell trial LC-44 measured the {site} quay at {load} tonnes "
                  f"per square metre, independently of S-310.", entities=[site],
            source_root="g1"),
    ]
    pad = _pad(cid)
    return case(
        cid, "independent_reconfirmation",
        f"Is the {site} quay capacity figure still supported?",
        corpus + pad,
        {
            "relevant": ["g1"], "critical": ["g1"],
            "irrelevant": ["r1", "d1", "d2"] + [m["id"] for m in pad],
            "must_not_expose": ["r1"],
            "stale": ["d1", "d2"],
            "roles": {"g1": "necessary", "r1": "withdrawn",
                      "d1": "stale_derived", "d2": "stale_derived"},
            "requirements": [{
                "req_id": "q1",
                "description": "support that does not descend from the withdrawn survey",
                "satisfied_by": ["g1"], "critical": True,
            }],
            # No answer key. The figure is the *same* number, so a substring
            # grader could not tell an answer citing the standing trial from one
            # citing a withdrawn survey's restatement -- which is the only thing
            # this case is about.
        },
        "The retracted survey and the standing trial agree on the number, so "
        "the answer is unchanged and the citation must change. A rule is "
        "correct here only if it reaches the figure through the trial rather "
        "than through a restatement of the withdrawn survey.",
        entities=[site],
    )


BUILDERS = {
    "retracted_intermediate": build_retracted_intermediate,
    "deep_chain": build_deep_chain,
    "copied_document": build_copied_document,
    "independent_reconfirmation": build_independent_reconfirmation,
}


def build_all() -> list[dict]:
    return [BUILDERS[f](i) for f in BUILDERS for i in range(PER_FAMILY)]


def write(out: pathlib.Path | None = None) -> dict:
    out = out or HERE
    cases = build_all()
    for c in cases:
        random.Random(f"propagation_v1/shuffle/{c['case_id']}").shuffle(c["corpus"])
    dev, test, seen = [], [], {}
    for c in cases:
        seen[c["family"]] = seen.get(c["family"], 0) + 1
        (test if seen[c["family"]] % 2 == 0 else dev).append(c)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "benchmark": "propagation_v1",
        "built_at": "2026-10-11",
        "note": ("A focused fixture for one question, not a benchmark. Generated; "
                 "these digests are the reproducibility claim."),
        "per_family": PER_FAMILY,
        "families": sorted(BUILDERS),
        "splits": {},
    }
    for name, chunk in (("dev", dev), ("test", test)):
        text = json.dumps({
            "benchmark": "propagation_v1", "split": name,
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
