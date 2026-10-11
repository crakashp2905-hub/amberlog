"""Generate relevance_v2 — the benchmark v1 and SciFact both said was needed.

v1 is **frozen and stays frozen**. Every number already measured against it
remains valid for what it measured; this is a new benchmark directory, not an
edit, because a benchmark that changes under its own results is not a
benchmark (principle 10 applied to data).

## Why a v2 at all

Two independent runs said the same thing about v1, and neither was looking for
it:

- **SciFact** showed v1 flattering the hashing embedder by a factor of four in
  the size of the gap: 0.315 against lexical's 0.621 externally, where v1 had
  reported 0.728 against 0.790. The three causes were all properties I had
  built in — 18 memories per case, distractors written to be *clearly* wrong,
  and memories short enough that token overlap nearly always works.
- **R6** on its frozen split measured perfect selection as worth **+0.000**
  downstream, and the registered abandonment clause fired. A model handed 19
  memories answered as well as one handed the correct 3. That is not a verdict
  on retrieval; it is a verdict on a corpus a model can simply read.

So the deficiency is specific and so is the fix. v2 changes four things and
nothing else:

1. **Corpora a model cannot read as a strategy.** ~480 memories per case
   against v1's 18, and `budget_pressure` cases well beyond that. Stuffing the
   context stops being a free baseline and starts being a cost.
2. **Near-misses by construction.** Every distractor on the asked topic is the
   answer-bearing sentence with **exactly one facet changed** — same predicate,
   same register, one discriminating token out of twelve. v1's distractors were
   depot facts against equipment questions, which is why a competent model
   ignored them.
3. **Chains that are genuinely multi-hop.** 3- and 4-hop cases where no single
   memory answers the question and the intermediate steps are load-bearing, so
   the asked topic has *no direct form* in the corpus. v1's `indirect` family
   was two hops and the premise was usually already in the pool.
4. **Labels that can measure sufficiency, not only ranking.** Each case
   carries `requirements`: evidence slots, each satisfiable by any of a set of
   memories, each marked critical or not. "Did the assembled context contain
   enough to decide?" is then a property of the returned set rather than a
   proxy read off a ranking.

## The two families that exist for a different question

`shared_root` and `independent_support` are not here to make retrieval harder.
They are the controlled form of a question the provenance machinery was built
for and has never been measured on: a conclusion with four apparent supports,
where all four derive from one survey that is later retracted, against one
where three derive from it and a fourth does not. Blanket invalidation and
plain graph traversal get these wrong in opposite directions, and the labels
say which answer is correct.

## Generated, not committed

v1 committed its JSON for reproducibility. At v2's corpus size that is ~10 MB
per split, and this repository already committed 7.8 MB of SciFact while its
own documentation said it had not. So the bytes are gitignored and
`MANIFEST.json` — committed — carries the SHA-256 of each split plus its case
and memory counts. `tests/test_relevance_v2_manifest.py` rebuilds and compares.
That is a *stronger* reproducibility claim than committing the output: it
asserts the generator still produces those exact bytes, which committing the
bytes does not.

Determinism: every choice goes through a `random.Random` seeded from a string,
and every value is a stable BLAKE2b digest of its facet tuple. No global
`random`, no wall-clock, no dict-ordering dependence. Two builds on two
machines produce byte-identical files.

## What this does not establish

- **The labels are still mine.** v2 is harder, not independent. SciFact remains
  the only external check in this project and nothing here replaces it.
- **The text is generated from templates.** That buys controlled near-misses
  and costs surface diversity: a method could in principle exploit the template
  grammar rather than the semantics. `arm_broken_*` in the harness is the check
  that matters, and the template count is deliberately >1 per topic.
- **Generated near-misses are near-misses by construction, which is an
  assumption.** One facet apart in *form* is not proof of one facet apart in
  *difficulty*. The evidence that it worked is the measured gap between a
  no-signal arm and a real one, and that is the harness's job to report.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import random
import re
from dataclasses import dataclass

HERE = pathlib.Path(__file__).resolve().parent
T0 = 1_700_000_000
DAY = 86_400

# --- facet vocabularies -----------------------------------------------------
#
# Deliberately small and heavily reused. A site or unit token that appears in
# four hundred memories carries almost no IDF, which is the point: the
# discriminating token in a near-miss must not also be the rare one, or lexical
# retrieval wins for the wrong reason.

SITES = (
    "coastal", "inland", "northern", "southern", "harbour", "quarry",
    "depot-7", "depot-12", "estuary", "upland", "riverside", "airfield",
)
UNITS = (
    "pump-4", "pump-2", "pump-11", "pump-17", "tug-1", "tug-3", "tug-8",
    "crane-2", "crane-5", "crane-9", "forklift-9", "forklift-14", "forklift-21",
    "compressor-3", "compressor-7", "chiller-1", "chiller-6", "hoist-6",
    "hoist-12", "winch-2", "winch-5", "genset-4", "genset-10", "loader-3",
)
SEASONS = ("winter", "summer", "monsoon")
REVISIONS = ("rev-A", "rev-B", "rev-C")
AXLES = ("heavy", "standard", "light")
FACET_VALUES = {
    "site": SITES,
    "unit": UNITS,
    "season": SEASONS,
    "revision": REVISIONS,
}


@dataclass(frozen=True)
class Topic:
    """A predicate with a fixed facet signature and a value domain.

    `text` has one phrasing per entry so that a case's answer-bearing memory
    and its near-misses do not all share a single sentence skeleton; the
    phrasing is chosen from the facet tuple, not from the role the memory plays,
    so phrasing never signals the answer.
    """

    name: str
    facets: tuple[str, ...]
    values: tuple[str, ...]
    texts: tuple[str, ...]
    question: str


TOPICS = (
    Topic(
        "tyre_pressure", ("unit", "site", "season"),
        ("3.1 bar", "3.5 bar", "3.8 bar", "4.2 bar", "4.6 bar", "5.0 bar"),
        (
            "{unit} tyre pressure at the {site} site is {value} in {season}.",
            "In {season}, run {unit} at {value} on the {site} site.",
            "{site} site: {unit} tyres are inflated to {value} for {season}.",
        ),
        "What is the {season} tyre pressure for {unit} at the {site} site?",
    ),
    Topic(
        "cable_swap", ("unit", "site"),
        ("30 days", "60 days", "90 days", "180 days", "2 years"),
        (
            "At the {site} site, swap the {unit} signal cable every {value}.",
            "{unit} signal cable replacement interval at {site} is {value}.",
        ),
        "How often is the {unit} signal cable swapped at the {site} site?",
    ),
    Topic(
        "torque", ("unit", "revision"),
        ("80 Nm", "95 Nm", "110 Nm", "140 Nm", "175 Nm"),
        (
            "Under {revision}, {unit} wheel nuts are torqued to {value}.",
            "{unit} wheel nut torque is {value} in procedure {revision}.",
        ),
        "What torque applies to {unit} wheel nuts under {revision}?",
    ),
    Topic(
        "oil_grade", ("unit", "site"),
        ("ISO 32", "ISO 46", "ISO 68", "ISO 100"),
        (
            "{unit} at the {site} site takes {value} hydraulic oil.",
            "Hydraulic fill for {unit} ({site} site) is {value}.",
        ),
        "Which hydraulic oil grade does {unit} take at the {site} site?",
    ),
    Topic(
        "inspection", ("unit", "site"),
        ("3 months", "6 months", "12 months", "24 months"),
        (
            "{unit} at the {site} site is inspected every {value}.",
            "{site} site inspection interval for {unit}: {value}.",
        ),
        "How often is {unit} inspected at the {site} site?",
    ),
    Topic(
        "lift_limit", ("unit", "site"),
        ("4 tonnes", "6 tonnes", "10 tonnes", "14 tonnes", "22 tonnes"),
        (
            "The {unit} rated lift at the {site} site is {value}.",
            "At {site}, {unit} must not lift more than {value}.",
        ),
        "What is the rated lift for {unit} at the {site} site?",
    ),
    Topic(
        "trip_temp", ("unit", "season"),
        ("82 °C", "91 °C", "104 °C", "118 °C"),
        (
            "{unit} trips on oil temperature above {value} in {season}.",
            "In {season} the {unit} oil-temperature trip is set at {value}.",
        ),
        "At what oil temperature does {unit} trip in {season}?",
    ),
    Topic(
        "clearance", ("unit", "site"),
        ("1.2 m", "1.8 m", "2.4 m", "3.0 m"),
        (
            "{unit} requires {value} of clearance at the {site} site.",
            "Keep {value} clear around {unit} on the {site} site.",
        ),
        "How much clearance does {unit} require at the {site} site?",
    ),
    Topic(
        "permit", ("unit", "site"),
        ("hot-work", "confined-space", "electrical-isolation", "working-at-height"),
        (
            "Work on {unit} at the {site} site requires a {value} permit.",
            "{site} site: a {value} permit is needed before {unit} work.",
        ),
        "Which permit is required for work on {unit} at the {site} site?",
    ),
    Topic(
        "fuel_spec", ("unit", "site"),
        ("B7 diesel", "B20 diesel", "GTL", "HVO"),
        (
            "{unit} runs on {value} at the {site} site.",
            "Fuel for {unit} ({site} site) is {value}.",
        ),
        "Which fuel does {unit} run on at the {site} site?",
    ),
)
BY_NAME = {t.name: t for t in TOPICS}


# --- stable value assignment ------------------------------------------------


def _digest(*parts: str) -> int:
    key = "\x1f".join(parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")


def value_for(topic: Topic, assignment: dict[str, str], *, avoid: str | None = None) -> str:
    """The value this topic takes at this facet tuple.

    A *function* of the facets, so the corpus is internally consistent: the
    same tuple always carries the same value, and a near-miss's value is not a
    free choice that could accidentally agree with the answer.

    `avoid` is the guard that makes a near-miss actually wrong. Without it a
    one-facet-away memory could carry the asked value by digest collision, and
    returning it would yield the correct answer while being no evidence for the
    asked tuple — the benchmark would be paying for a coincidence.
    """
    key = [topic.name] + [f"{f}={assignment[f]}" for f in topic.facets]
    idx = _digest(*key) % len(topic.values)
    chosen = topic.values[idx]
    if avoid is not None and chosen == avoid:
        chosen = topic.values[(idx + 1) % len(topic.values)]
        assert chosen != avoid, (topic.name, assignment, avoid)
    return chosen


def phrasing(topic: Topic, assignment: dict[str, str]) -> str:
    idx = _digest("phrasing", topic.name, *(assignment[f] for f in topic.facets))
    return topic.texts[idx % len(topic.texts)]


def render(topic: Topic, assignment: dict[str, str], value: str) -> str:
    return phrasing(topic, assignment).format(value=value, **assignment)


# --- memory and case construction -------------------------------------------


def mem(mid: str, content: str, **kw) -> dict:
    base = {
        "id": mid,
        "content": content,
        "type": "semantic",
        "lifecycle_state": "active",
        "scope": "private",
        "tenant_id": "tn_default",
        "capabilities": [],
        "method": "observed",
        "parents": [],
        "recorded_at": T0,
        "valid_from": None,
        "valid_to": None,
        "version": 1,
        "entities": [],
        "source_root": mid,
    }
    base.update(kw)
    return base


def fact(mid: str, topic: Topic, assignment: dict[str, str], *,
         avoid: str | None = None, **kw) -> tuple[dict, str]:
    value = value_for(topic, assignment, avoid=avoid)
    entities = [assignment[f] for f in topic.facets if f in ("unit", "site")]
    return mem(mid, render(topic, assignment, value), entities=entities, **kw), value


_ALNUM = re.compile(r"[0-9a-z]")


def key_matches(key: str, text: str) -> bool:
    """Boundary-aware substring match. The grading rule, defined once.

    R6 graded by plain substring, and on v2 that is not merely crude but wrong:
    the answer key "4 tonnes" is a substring of "14 tonnes", so a near-miss
    would have graded a correct answer. Flanking alphanumerics disqualify a
    match, which separates those two and still accepts "3.5bar" for "3.5 bar"
    via the no-space alternative key.

    Exported so the downstream harness grades with exactly the rule the
    generator used to prove the corpus contains no other match. A grader that
    disagreed with the guard would reintroduce the leak the guard rules out.
    """
    low_key, low_text = key.lower(), text.lower()
    start = 0
    while True:
        at = low_text.find(low_key, start)
        if at < 0:
            return False
        before = low_text[at - 1] if at else ""
        after = low_text[at + len(low_key)] if at + len(low_key) < len(low_text) else ""
        if not _ALNUM.match(before or " ") and not _ALNUM.match(after or " "):
            return True
        start = at + 1


def approx_tokens(text: str) -> int:
    """Words times 1.3. Crude, stated as crude, and consistent across arms.

    A real tokeniser would tie the committed benchmark to one model's
    vocabulary. The harness reports measured prompt tokens from the model that
    actually ran; this field exists so a case can be *selected* by size without
    loading a tokeniser.
    """
    return int(len(text.split()) * 1.3) + 1


def case(case_id: str, family: str, task_text: str, corpus: list[dict],
         labels: dict, rationale: str, **task_kw) -> dict:
    task = {
        "task_text": task_text,
        "goal": task_kw.pop("goal", ""),
        "constraints": task_kw.pop("constraints", []),
        "entities": task_kw.pop("entities", []),
        "event_time": task_kw.pop("event_time", T0),
        "token_budget": task_kw.pop("token_budget", 400),
        "agent_id": task_kw.pop("agent_id", "ag-bench"),
        "agent_role": task_kw.pop("agent_role", "engineer"),
        "tenant_id": task_kw.pop("tenant_id", "tn_default"),
        "granted_capabilities": task_kw.pop("granted_capabilities", []),
    }
    assert not task_kw, task_kw
    full = {
        "relevant": [], "critical": [], "irrelevant": [], "must_not_expose": [],
        "expect_abstain": False, "roles": {}, "requirements": [],
        # Memories whose own lifecycle is active but whose source root has been
        # retracted. Reachable, and citing one is the failure mode the
        # provenance machinery exists to prevent, so they are labelled
        # separately from `irrelevant`: an arm that ranks them highly is not
        # imprecise, it is wrong in a way precision does not name.
        "stale": [],
    }
    full.update(labels)

    ids = [m["id"] for m in corpus]
    assert len(ids) == len(set(ids)), (case_id, "duplicate memory id")
    idset = set(ids)
    for key in ("relevant", "critical", "irrelevant", "must_not_expose", "stale"):
        unknown = set(full[key]) - idset
        assert not unknown, (case_id, key, sorted(unknown)[:5])
    overlap = set(full["relevant"]) & set(full["irrelevant"])
    assert not overlap, (case_id, "relevant & irrelevant", sorted(overlap))
    assert set(full["critical"]) <= set(full["relevant"]), (case_id, "critical not subset of relevant")

    # Every memory is labelled. v1 allowed silence, which let a memory be
    # neither credited nor penalised and quietly removed it from the metric.
    unlabelled = idset - set(full["relevant"]) - set(full["irrelevant"])
    assert not unlabelled, (case_id, "unlabelled", sorted(unlabelled)[:5])

    # Requirement integrity: a requirement nothing can satisfy is a label bug,
    # and a critical requirement must be satisfiable by something relevant.
    for req in full["requirements"]:
        sat = set(req["satisfied_by"])
        assert sat, (case_id, req["req_id"], "no satisfier")
        assert sat <= idset, (case_id, req["req_id"], sorted(sat - idset))
        if req.get("critical"):
            assert sat <= set(full["relevant"]), (case_id, req["req_id"], "critical satisfier not relevant")

    # Parent edges must be [id, weight] pairs naming a memory in this corpus.
    #
    # The first build wrote them as bare strings. The harness reads `p[0]` for
    # the id, so every parent resolved to a single character, matched nothing,
    # and the store recorded each derived memory as its own source root. The
    # two families built to exercise correction propagation therefore had no
    # derivation structure at all, and `store_roots` was identical to
    # `store_plain` on all twelve of them -- which looked like a finding about
    # the mechanism and was a defect in the fixture.
    for m in corpus:
        for parent in m.get("parents") or ():
            assert isinstance(parent, (list, tuple)) and len(parent) == 2, (
                case_id, m["id"], "parent must be [id, weight]", parent)
            assert parent[0] in idset, (case_id, m["id"], "unknown parent", parent[0])
            assert parent[0] != m["id"], (case_id, m["id"], "self-parent")

    # No answer key may match a memory outside the relevant set.
    #
    # The first build leaked 185 times across the two splits, in three
    # different ways: an axle-pressure rule that repeated a value at a
    # different (axle, season); the key "4 tonnes" inside "14 tonnes"; and a
    # bare "14" matching "forklift-14". Each would have graded a wrong
    # retrieval as a correct answer, which is the failure that makes a
    # downstream number meaningless -- and v1 shipped two cousins of it.
    #
    # So this is an assertion rather than three repairs: a case that can be
    # answered from something it labels irrelevant does not get built.
    keys = full.get("answer_contains") or []
    relevant = set(full["relevant"])
    for m in corpus:
        if m["id"] in relevant:
            continue
        for k in keys:
            assert not key_matches(k, m["content"]), (
                case_id, "answer key leaks into", m["id"], k, m["content"])

    body = " ".join(m["content"] for m in corpus)
    return {
        "case_id": case_id,
        "family": family,
        "task": task,
        "corpus": corpus,
        "labels": full,
        "rationale": rationale,
        "corpus_size": len(corpus),
        "corpus_tokens": approx_tokens(body),
    }


# --- the filler and near-miss machinery -------------------------------------


def near_misses(topic: Topic, answer_assignment: dict[str, str], answer_value: str,
                rng: random.Random, *, start: int = 0) -> list[dict]:
    """Every one-facet-away variant of the answer-bearing sentence.

    This is the mechanism the whole benchmark turns on. For each facet in the
    topic's signature and each alternative value of that facet, emit the same
    predicate with that one facet changed. The result differs from the answer
    by one token in twelve, shares every other token, and is *wrong* — which is
    what v1's distractors were not.
    """
    out = []
    n = start
    for facet in topic.facets:
        for alt in FACET_VALUES[facet]:
            if alt == answer_assignment[facet]:
                continue
            variant = dict(answer_assignment)
            variant[facet] = alt
            m, _ = fact(f"n{n:04d}", topic, variant, avoid=answer_value)
            out.append(m)
            n += 1
    rng.shuffle(out)
    return out


def assignments_of(topic: Topic) -> list[dict[str, str]]:
    """Every facet tuple this topic admits, and no others.

    The first version of this iterated unit x site x season for *every* topic
    and then filtered. For a topic naming neither site nor season that produced
    36 distinct sentences under 288 ids: duplicate content, which pads a corpus
    without adding a distractor, and which would have made `budget_pressure`
    look an order of magnitude harder than it was.
    """
    out: list[dict[str, str]] = [{}]
    for facet in topic.facets:
        out = [{**a, facet: v} for a in out for v in FACET_VALUES[facet]]
    return out


def fillers(exclude_topic: str, rng: random.Random, count: int, *,
            start: int = 0) -> list[dict]:
    """Other topics, same vocabulary, drawn without replacement.

    `exclude_topic` is load-bearing for the chain families: if a direct
    statement of the asked topic exists anywhere in the corpus then the chain is
    decoration and the case measures nothing it claims to.
    """
    pool: list[tuple[Topic, dict[str, str]]] = []
    for topic in TOPICS:
        if topic.name == exclude_topic:
            continue
        pool.extend((topic, a) for a in assignments_of(topic))
    rng.shuffle(pool)
    assert len(pool) >= count, (
        f"filler pool holds {len(pool)}, need {count}: widen a facet vocabulary "
        f"or add a topic rather than quietly shrinking the corpus")
    out = []
    for n, (topic, assignment) in enumerate(pool[:count], start=start):
        m, _ = fact(f"f{n:04d}", topic, assignment)
        out.append(m)
    return out


def same_topic_others(topic: Topic, answer_assignment: dict[str, str],
                      answer_value: str, rng: random.Random, count: int, *,
                      start: int = 0) -> list[dict]:
    """The asked predicate at facet tuples two or more steps away.

    Without these, every memory stating the asked predicate is either the
    answer or exactly one facet from it, and "how many facets differ" becomes a
    signal no real corpus would provide. A topic with one facet admits no tuple
    two steps away, so this can legitimately return fewer than `count`.
    """
    pool = [
        a for a in assignments_of(topic)
        if sum(1 for f in topic.facets if a[f] != answer_assignment[f]) >= 2
    ]
    rng.shuffle(pool)
    out = []
    for n, assignment in enumerate(pool[:count], start=start):
        m, _ = fact(f"s{n:04d}", topic, assignment, avoid=answer_value)
        out.append(m)
    return out


# --- sizes ------------------------------------------------------------------
#
# ~480 memories against v1's 18. Chosen so that `all_memory` costs roughly
# 6,000 prompt tokens: expensive enough that stuffing the context is a cost
# rather than a free baseline, cheap enough that it still *runs* and can be
# compared. `budget_pressure` goes to ~1,900 so that stuffing is not an option
# at all, which is the condition R6 could never create.
FILLERS = 400
SAME_TOPIC = 60
FILLERS_BUDGET = 1_800

BAYS = tuple(range(1, 21))


def axle_pressure(axle: str, season: str) -> float:
    """Distinct across every (axle, season) pair by construction.

    Two reasons, and the first version satisfied only one of them. If two axle
    sets shared a pressure *within* a season, hop 2 of a chain case would be
    unnecessary and the case would silently become 2-hop. And if any two pairs
    anywhere shared a value, the answer would also be stated by a rule for the
    wrong axle in the wrong season -- which is exactly what happened: every
    `multi_hop_3` case leaked its answer into a memory it labelled irrelevant.

    Nine pairs, nine distinct values, rotated by a digest so the mapping is not
    the obvious one.
    """
    idx = AXLES.index(axle) * len(SEASONS) + SEASONS.index(season)
    rot = _digest("axle_pressure_rotation") % 9
    return round(2.6 + ((idx + rot) % 9) * 0.2, 1)


def bay_unit(site: str, bay: int) -> str:
    return UNITS[_digest("bay_unit", site, str(bay)) % len(UNITS)]


def unit_axle(unit: str) -> str:
    return AXLES[_digest("unit_axle", unit) % len(AXLES)]


def site_margin(site: str) -> float:
    """Deliberately off the 0.2 grid the axle pressures sit on.

    A margin of 0.2 or 0.4 would put a 4-hop answer exactly on another axle
    rule's value, so the corpus would state the answer for the wrong reason.
    0.25 / 0.35 / 0.45 cannot land on a multiple of 0.2, which makes the 4-hop
    answers unreachable except by doing the arithmetic.
    """
    return round(0.25 + (_digest("site_margin", site) % 3) * 0.10, 2)


def _pick(case_id: str) -> dict:
    """Facet draw for a case. A digest of the case id, so it never moves."""
    d = _digest("pick", case_id)
    return {
        "topic": TOPICS[d % len(TOPICS)],
        "site": SITES[(d >> 7) % len(SITES)],
        "unit": UNITS[(d >> 14) % len(UNITS)],
        "season": SEASONS[(d >> 21) % len(SEASONS)],
        "revision": REVISIONS[(d >> 28) % len(REVISIONS)],
        "bay": BAYS[(d >> 35) % len(BAYS)],
    }


def _assignment(topic: Topic, p: dict) -> dict:
    return {f: p[f] for f in topic.facets}


def _standard_padding(topic: Topic, assignment: dict, answer_value: str,
                      rng: random.Random, *, n_fillers: int = FILLERS,
                      exclude_topic: str | None = None) -> list[dict]:
    pad = near_misses(topic, assignment, answer_value, rng)
    pad += same_topic_others(topic, assignment, answer_value, rng, SAME_TOPIC)
    pad += fillers(exclude_topic or topic.name, rng, n_fillers)
    return pad


# --- family: direct ---------------------------------------------------------


def build_direct(i: int) -> dict:
    cid = f"direct-{i + 1:02d}"
    rng = random.Random(f"relevance_v2/{cid}")
    p = _pick(cid)
    topic = p["topic"]
    assignment = _assignment(topic, p)
    answer, value = fact("a1", topic, assignment)
    pad = _standard_padding(topic, assignment, value, rng)
    corpus = [answer] + pad
    tuple_desc = ", ".join(f"{f}={assignment[f]}" for f in topic.facets)
    return case(
        cid, "direct",
        topic.question.format(**assignment),
        corpus,
        {
            "relevant": ["a1"], "critical": ["a1"],
            "irrelevant": [m["id"] for m in pad],
            "roles": {"a1": "necessary"},
            "requirements": [{
                "req_id": "q1",
                "description": f"a statement of {topic.name} for exactly {tuple_desc}",
                "satisfied_by": ["a1"], "critical": True,
            }],
            "answer_contains": [value, value.replace(" ", "")],
        },
        f"One memory states {topic.name} at the asked facet tuple. Every other "
        f"statement of the same predicate differs in at least one facet and "
        f"carries a different value, so returning it answers the wrong question.",
        entities=[assignment[f] for f in topic.facets if f in ("unit", "site")],
    )


# --- family: facet_trap -----------------------------------------------------


def build_facet_trap(i: int) -> dict:
    """Same as `direct`, except the near-misses are *all* of them.

    No two-or-more-steps-away padding on the asked topic: every statement of
    the asked predicate is exactly one facet from the answer. The question
    cannot be answered by narrowing on vocabulary, only by matching the whole
    tuple, which is the failure mode a hashed bag of words has no defence
    against.
    """
    cid = f"facet_trap-{i + 1:02d}"
    rng = random.Random(f"relevance_v2/{cid}")
    p = _pick(cid)
    topic = p["topic"]
    assignment = _assignment(topic, p)
    answer, value = fact("a1", topic, assignment)
    pad = near_misses(topic, assignment, value, rng)
    pad += fillers(topic.name, rng, FILLERS + SAME_TOPIC)
    corpus = [answer] + pad
    return case(
        cid, "facet_trap",
        topic.question.format(**assignment),
        corpus,
        {
            "relevant": ["a1"], "critical": ["a1"],
            "irrelevant": [m["id"] for m in pad],
            "roles": {"a1": "necessary"},
            "requirements": [{
                "req_id": "q1",
                "description": "the asked facet tuple, not a neighbour of it",
                "satisfied_by": ["a1"], "critical": True,
            }],
            "answer_contains": [value, value.replace(" ", "")],
        },
        "Every statement of the asked predicate is exactly one facet away from "
        "the answer. Token overlap cannot separate them.",
        entities=[assignment[f] for f in topic.facets if f in ("unit", "site")],
    )


# --- families: multi_hop_3 and multi_hop_4 ----------------------------------


def build_chain(i: int, hops: int) -> dict:
    fam = f"multi_hop_{hops}"
    cid = f"{fam}-{i + 1:02d}"
    rng = random.Random(f"relevance_v2/{cid}")
    p = _pick(cid)
    site, season, bay = p["site"], p["season"], p["bay"]
    unit = bay_unit(site, bay)
    axle = unit_axle(unit)
    pressure = axle_pressure(axle, season)
    margin = site_margin(site) if hops == 4 else 0.0
    answer_value = round(pressure + margin, 2)
    answer_fmt = f"{answer_value:.1f}" if hops == 3 else f"{answer_value:.2f}"

    chain = [
        mem("h1", f"Bay {bay} at the {site} site is assigned to {unit}.",
            entities=[site, unit]),
        mem("h2", f"{unit} was re-fitted with the {axle} axle set in March.",
            entities=[unit]),
        mem("h3", f"Vehicles with the {axle} axle set run {pressure:.1f} bar in {season}.",
            entities=[]),
    ]
    reqs = [
        {"req_id": "q1", "description": f"which vehicle occupies bay {bay} at {site}",
         "satisfied_by": ["h1"], "critical": True},
        {"req_id": "q2", "description": f"which axle set {unit} carries",
         "satisfied_by": ["h2"], "critical": True},
        {"req_id": "q3", "description": f"the {season} pressure rule for that axle set",
         "satisfied_by": ["h3"], "critical": True},
    ]
    if hops == 4:
        chain.append(mem(
            "h4",
            f"At the {site} site, add {margin:.2f} bar to the axle-set figure "
            f"as a salt-corrosion margin.",
            entities=[site]))
        reqs.append({"req_id": "q4",
                     "description": f"the {site} site margin applied on top",
                     "satisfied_by": ["h4"], "critical": True})

    # Near-misses for each hop, in the same register as the hop they shadow.
    pad = []
    n = 0
    for b in BAYS:
        if b == bay:
            continue
        u = bay_unit(site, b)
        if u == unit:
            continue  # two bays holding the answer's unit muddies hop 1
        pad.append(mem(f"c{n:04d}", f"Bay {b} at the {site} site is assigned to {u}.",
                       entities=[site, u]))
        n += 1
    for other_site in SITES:
        if other_site == site:
            continue
        for b in (bay, (bay % 20) + 1):
            u = bay_unit(other_site, b)
            pad.append(mem(f"c{n:04d}",
                           f"Bay {b} at the {other_site} site is assigned to {u}.",
                           entities=[other_site, u]))
            n += 1
    for u in UNITS:
        if u == unit:
            continue
        pad.append(mem(f"c{n:04d}",
                       f"{u} was re-fitted with the {unit_axle(u)} axle set in March.",
                       entities=[u]))
        n += 1
    for a in AXLES:
        for s in SEASONS:
            if a == axle and s == season:
                continue
            pad.append(mem(f"c{n:04d}",
                           f"Vehicles with the {a} axle set run "
                           f"{axle_pressure(a, s):.1f} bar in {s}.", entities=[]))
            n += 1
    for other_site in SITES:
        if other_site == site:
            continue
        pad.append(mem(f"c{n:04d}",
                       f"At the {other_site} site, add {site_margin(other_site):.2f} bar "
                       f"to the axle-set figure as a salt-corrosion margin.",
                       entities=[other_site]))
        n += 1
    # No direct tyre_pressure statement for anything, anywhere: if one existed
    # for this unit the chain would be decoration, and excluding only that unit
    # would make the *absence* of a direct fact a signal pointing at it.
    pad += fillers("tyre_pressure", rng, FILLERS)
    rng.shuffle(pad)

    corpus = chain + pad
    return case(
        cid, fam,
        f"What tyre pressure should the vehicle in bay {bay} at the {site} site "
        f"run in {season}?",
        corpus,
        {
            "relevant": [m["id"] for m in chain],
            "critical": [m["id"] for m in chain],
            "irrelevant": [m["id"] for m in pad],
            "roles": {m["id"]: "necessary" for m in chain},
            "requirements": reqs,
            "answer_contains": [f"{answer_fmt} bar", f"{answer_fmt}bar"],
        },
        f"No memory states the asked quantity. It requires {hops} hops, each "
        f"shadowed by near-misses in its own register, and the corpus contains "
        f"no direct tyre-pressure statement for any unit.",
        entities=[site],
    )


# --- family: superseded_rev -------------------------------------------------


def build_superseded(i: int) -> dict:
    cid = f"superseded_rev-{i + 1:02d}"
    rng = random.Random(f"relevance_v2/{cid}")
    p = _pick(cid)
    topic = p["topic"]
    assignment = _assignment(topic, p)
    current, value = fact("a1", topic, assignment,
                          valid_from=T0 - 10 * DAY, valid_to=None)
    alternatives = [v for v in topic.values if v != value]
    old_value = alternatives[_digest("old", cid) % len(alternatives)]
    old = mem("a0", render(topic, assignment, old_value),
              entities=current["entities"],
              valid_from=T0 - 400 * DAY, valid_to=T0 - 10 * DAY)
    pad = _standard_padding(topic, assignment, value, rng)
    corpus = [current, old] + pad
    return case(
        cid, "superseded_rev",
        topic.question.format(**assignment),
        corpus,
        {
            "relevant": ["a1"], "critical": ["a1"],
            "irrelevant": ["a0"] + [m["id"] for m in pad],
            "roles": {"a1": "necessary", "a0": "superseded"},
            "requirements": [{
                "req_id": "q1", "description": "the figure in force at the event time",
                "satisfied_by": ["a1"], "critical": True,
            }],
            "answer_contains": [value, value.replace(" ", "")],
        },
        "Two statements of the asked tuple, distinguished only by validity "
        "interval. The superseded one is the single highest-overlap memory in "
        "the corpus, so any arm without temporal filtering ranks it first.",
        entities=[assignment[f] for f in topic.facets if f in ("unit", "site")],
        event_time=T0,
    )


# --- family: unanswerable ---------------------------------------------------


def build_unanswerable(i: int) -> dict:
    """The asked tuple is genuinely absent, surrounded by its neighbours.

    v1 had three unanswerable cases in total and R6 could only call a
    *direction* from them. Six here, and the absence is dense: every
    one-facet-away variant is present, so a model that pattern-matches on
    vocabulary will find something that looks like an answer.
    """
    cid = f"unanswerable-{i + 1:02d}"
    rng = random.Random(f"relevance_v2/{cid}")
    p = _pick(cid)
    topic = p["topic"]
    assignment = _assignment(topic, p)
    # The value the asked tuple *would* have, so neighbours can be made to
    # avoid it. Nothing in the corpus states it.
    phantom = value_for(topic, assignment)
    pad = near_misses(topic, assignment, phantom, rng)
    pad += same_topic_others(topic, assignment, phantom, rng, SAME_TOPIC)
    pad += fillers(topic.name, rng, FILLERS)
    return case(
        cid, "unanswerable",
        topic.question.format(**assignment),
        pad,
        {
            "relevant": [], "critical": [],
            "irrelevant": [m["id"] for m in pad],
            "expect_abstain": True,
            "requirements": [],
        },
        "Every neighbour of the asked tuple is present and the tuple itself is "
        "not. The correct answer is that the corpus does not say.",
        entities=[assignment[f] for f in topic.facets if f in ("unit", "site")],
    )


# --- family: conflicting ----------------------------------------------------


def build_conflicting(i: int) -> dict:
    cid = f"conflicting-{i + 1:02d}"
    rng = random.Random(f"relevance_v2/{cid}")
    p = _pick(cid)
    topic = p["topic"]
    assignment = _assignment(topic, p)
    value = value_for(topic, assignment)
    alternatives = [v for v in topic.values if v != value]
    other = alternatives[_digest("conflict", cid) % len(alternatives)]
    entities = [assignment[f] for f in topic.facets if f in ("unit", "site")]
    a1 = mem("a1", render(topic, assignment, value) + " (site log)", entities=entities)
    a2 = mem("a2", render(topic, assignment, other) + " (manufacturer sheet)",
             entities=entities)
    pad = _standard_padding(topic, assignment, value, rng)
    corpus = [a1, a2] + pad
    return case(
        cid, "conflicting",
        topic.question.format(**assignment),
        corpus,
        {
            "relevant": ["a1", "a2"], "critical": ["a1", "a2"],
            "irrelevant": [m["id"] for m in pad],
            "roles": {"a1": "necessary", "a2": "necessary"},
            # Two requirements, not one satisfiable by either: the defensible
            # answer is "these two sources disagree", which needs both sides
            # present. A context holding one side is confidently wrong.
            "requirements": [
                {"req_id": "q1", "description": "the site log's figure",
                 "satisfied_by": ["a1"], "critical": True},
                {"req_id": "q2", "description": "the manufacturer sheet's figure",
                 "satisfied_by": ["a2"], "critical": True},
            ],
        },
        "Two standing, equally valid statements of the same tuple disagree. No "
        "answer key: the correct response is to surface the conflict, and "
        "scoring that by substring would reward emitting a number.",
        entities=entities,
    )


# --- family: gated ----------------------------------------------------------


def build_gated(i: int) -> dict:
    cid = f"gated-{i + 1:02d}"
    rng = random.Random(f"relevance_v2/{cid}")
    p = _pick(cid)
    topic = p["topic"]
    assignment = _assignment(topic, p)
    answer, value = fact("a1", topic, assignment, capabilities=["cap-restricted"])
    pad = _standard_padding(topic, assignment, value, rng)
    corpus = [answer] + pad
    return case(
        cid, "gated",
        topic.question.format(**assignment),
        corpus,
        {
            "relevant": ["a1"], "critical": ["a1"],
            "must_not_expose": ["a1"],
            "irrelevant": [m["id"] for m in pad],
            "roles": {"a1": "necessary"},
            "expect_abstain": True,
            "requirements": [{
                "req_id": "q1",
                "description": "the asked tuple, which is capability-gated",
                "satisfied_by": ["a1"], "critical": True,
            }],
        },
        "The only memory that answers requires a capability the agent was not "
        "granted. The reachable relevant set is empty, so the correct outcome "
        "is abstention and a sufficiency report of zero - an arm claiming "
        "sufficiency here satisfied a requirement with something it may not expose.",
        entities=[assignment[f] for f in topic.facets if f in ("unit", "site")],
    )


# --- families: shared_root and independent_support --------------------------
#
# These two exist for the correction-propagation question, and they are a
# matched pair: identical surface, opposite correct answers. Blanket
# invalidation gets `independent_support` wrong by discarding a standing
# source; plain graph traversal gets `shared_root` wrong by counting three
# derived restatements as three supports.


def _survey_block(cid: str, site: str, *, independent: bool):
    # 31..39, so neither the survey figure nor the load-cell figure (load - 4,
    # i.e. 27..35) can coincide with any `lift_limit` value -- that topic is
    # this family's padding, and at 14..22 the two domains overlapped.
    load = 31 + (_digest("load", cid) % 5) * 2
    r1 = mem("r1", f"Survey S-114 measured the {site} quay bearing capacity at "
                   f"{load} tonnes per square metre.",
             entities=[site], lifecycle_state="quarantined")
    derived = [
        mem("d1", f"The {site} quay is rated for {load} tonnes per square metre.",
            entities=[site], method="derived", parents=[["r1", 1]], source_root="r1"),
        mem("d2", f"Crane staging on the {site} quay is permitted up to "
                  f"{load} tonnes per square metre.",
            entities=[site], method="derived", parents=[["r1", 1]], source_root="r1"),
        mem("d3", f"The {site} lift plan assumes a {load} t/m2 quay capacity.",
            entities=[site], method="derived", parents=[["r1", 1]], source_root="r1"),
    ]
    if not independent:
        derived.append(mem(
            "d4", f"Operations guidance for {site} cites a {load} t/m2 quay limit.",
            entities=[site], method="derived", parents=[["r1", 1]], source_root="r1"))
        return r1, derived, None, load
    r2 = mem("r2", f"Load-cell trial LC-22 independently measured the {site} quay at "
                   f"{load - 4} tonnes per square metre.",
             entities=[site], source_root="r2")
    d4 = mem("d4", f"The {site} quay is rated for {load - 4} tonnes per square metre "
                   f"on the load-cell trial.",
             entities=[site], method="derived", parents=[["r2", 1]], source_root="r2")
    return r1, derived, (r2, d4), load


def build_shared_root(i: int) -> dict:
    cid = f"shared_root-{i + 1:02d}"
    rng = random.Random(f"relevance_v2/{cid}")
    p = _pick(cid)
    site = p["site"]
    r1, derived, _, load = _survey_block(cid, site, independent=False)
    topic = BY_NAME["lift_limit"]
    assignment = {"unit": p["unit"], "site": site}
    pad = _standard_padding(topic, assignment, value_for(topic, assignment), rng)
    corpus = [r1] + derived + pad
    stale = [m["id"] for m in derived]
    return case(
        cid, "shared_root",
        f"Can we stage a 22-tonne crane on the {site} quay?",
        corpus,
        {
            "relevant": ["r1"], "critical": ["r1"],
            "must_not_expose": ["r1"],
            "irrelevant": stale + [m["id"] for m in pad],
            "stale": stale,
            "roles": {"r1": "necessary", **{s: "stale_derived" for s in stale}},
            "expect_abstain": True,
            "requirements": [{
                "req_id": "q1",
                "description": "a standing measurement of the quay's bearing capacity",
                "satisfied_by": ["r1"], "critical": True,
            }],
        },
        "Four memories appear to support the capacity figure and all four "
        "derive from one retracted survey. Counting supports gives four; "
        "counting distinct source roots gives zero standing ones. The correct "
        "answer is that there is no longer evidence, and citing any derived "
        "restatement is use of stale evidence.",
        entities=[site],
    )


def build_independent_support(i: int) -> dict:
    cid = f"independent_support-{i + 1:02d}"
    rng = random.Random(f"relevance_v2/{cid}")
    p = _pick(cid)
    site = p["site"]
    r1, derived, extra, load = _survey_block(cid, site, independent=True)
    r2, d4 = extra
    topic = BY_NAME["lift_limit"]
    assignment = {"unit": p["unit"], "site": site}
    pad = _standard_padding(topic, assignment, value_for(topic, assignment), rng)
    corpus = [r1] + derived + [r2, d4] + pad
    stale = [m["id"] for m in derived]
    return case(
        cid, "independent_support",
        f"What bearing capacity should the {site} quay lift plan use?",
        corpus,
        {
            "relevant": ["r1", "r2", "d4"], "critical": ["r2"],
            "must_not_expose": ["r1"],
            "irrelevant": stale + [m["id"] for m in pad],
            "stale": stale,
            "roles": {"r2": "necessary", "d4": "supporting", "r1": "withdrawn",
                      **{s: "stale_derived" for s in stale}},
            "expect_abstain": False,
            "requirements": [{
                "req_id": "q1",
                "description": "a measurement that does not derive from the retracted survey",
                "satisfied_by": ["r2", "d4"], "critical": True,
            }],
            # No bare number. `str(load - 4)` matched "forklift-14" and every
            # other id carrying the digits, so a model naming a unit would have
            # graded correct.
            "answer_contains": [f"{load - 4} tonnes per square metre",
                                f"{load - 4} t/m2"],
        },
        "The same retracted survey and the same three derived restatements as "
        "`shared_root`, plus one measurement that does not descend from it. "
        "Blanket invalidation discards the standing trial and abstains, which "
        "is the error this family exists to catch; the correct answer is the "
        "load-cell figure, citing neither the survey nor anything derived from it.",
        entities=[site],
    )


# --- family: budget_pressure ------------------------------------------------


def build_budget_pressure(i: int) -> dict:
    """A corpus no model reads as a strategy.

    R6's frozen split abandoned its comparison because perfect selection was
    worth +0.000 against handing the model all 19 memories. At ~1,900 memories
    that baseline costs roughly 24,000 prompt tokens, so the comparison is
    between selection and *paying*, which is the regime retrieval exists for
    and the one v1 could not construct.
    """
    cid = f"budget_pressure-{i + 1:02d}"
    rng = random.Random(f"relevance_v2/{cid}")
    p = _pick(cid)
    topic = p["topic"]
    assignment = _assignment(topic, p)
    answer, value = fact("a1", topic, assignment)
    pad = near_misses(topic, assignment, value, rng)
    pad += same_topic_others(topic, assignment, value, rng, SAME_TOPIC)
    pad += fillers(topic.name, rng, FILLERS_BUDGET)
    corpus = [answer] + pad
    return case(
        cid, "budget_pressure",
        topic.question.format(**assignment),
        corpus,
        {
            "relevant": ["a1"], "critical": ["a1"],
            "irrelevant": [m["id"] for m in pad],
            "roles": {"a1": "necessary"},
            "requirements": [{
                "req_id": "q1", "description": "the asked facet tuple",
                "satisfied_by": ["a1"], "critical": True,
            }],
            "answer_contains": [value, value.replace(" ", "")],
        },
        "Structurally a `direct` case at ten times the corpus size, so that "
        "the full-context baseline has a price attached.",
        entities=[assignment[f] for f in topic.facets if f in ("unit", "site")],
    )


# --- assembly ---------------------------------------------------------------

PER_FAMILY = 6

BUILDERS = {
    "direct": build_direct,
    "facet_trap": build_facet_trap,
    "multi_hop_3": lambda i: build_chain(i, 3),
    "multi_hop_4": lambda i: build_chain(i, 4),
    "superseded_rev": build_superseded,
    "unanswerable": build_unanswerable,
    "conflicting": build_conflicting,
    "gated": build_gated,
    "shared_root": build_shared_root,
    "independent_support": build_independent_support,
    "budget_pressure": build_budget_pressure,
}


def build_all() -> list[dict]:
    cases = []
    for family in BUILDERS:          # insertion order, fixed above
        for i in range(PER_FAMILY):
            cases.append(BUILDERS[family](i))
    return cases


def shuffle_corpora(cases: list[dict]) -> None:
    """Remove the positional signal, in the generator.

    v1 learned this the expensive way: written with the relevant memory first,
    a deliberately broken arm returning storage order scored 0.869 nDCG against
    the hybrid baseline's 0.832. The benchmark was leaking its own answers.
    Seeded from the case id, so two builds are byte-identical.
    """
    for c in cases:
        random.Random(f"relevance_v2/shuffle/{c['case_id']}").shuffle(c["corpus"])


def split(cases: list[dict]) -> tuple[list[dict], list[dict]]:
    """Cases 2, 4, 6 of each family to test; 1, 3, 5 to dev.

    Declared here and frozen on first build. The same rule as v1, so the two
    benchmarks' splits are constructed the same way and a dev/test disagreement
    on one cannot be blamed on a different split procedure.
    """
    dev, test = [], []
    seen: dict[str, int] = {}
    for c in cases:
        seen[c["family"]] = seen.get(c["family"], 0) + 1
        (test if seen[c["family"]] % 2 == 0 else dev).append(c)
    return dev, test


def write(out: pathlib.Path | None = None) -> dict:
    out = out or HERE
    cases = build_all()
    shuffle_corpora(cases)
    dev, test = split(cases)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "benchmark": "relevance_v2",
        "built_at": "2026-10-11",
        "note": ("Frozen. A change means a new benchmark directory, not an edit. "
                 "The split JSON is generated, not committed; these digests are "
                 "the reproducibility claim."),
        "per_family": PER_FAMILY,
        "families": sorted(BUILDERS),
        "splits": {},
    }
    for name, chunk in (("dev", dev), ("test", test)):
        payload = {
            "benchmark": "relevance_v2",
            "split": name,
            "built_at": manifest["built_at"],
            "cases": chunk,
        }
        text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
        (out / f"{name}.json").write_text(text, encoding="utf-8")
        manifest["splits"][name] = {
            "cases": len(chunk),
            "memories": sum(c["corpus_size"] for c in chunk),
            "approx_tokens": sum(c["corpus_tokens"] for c in chunk),
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
              f"~{info['approx_tokens']} tokens, {info['bytes'] / 1e6:.1f} MB")
        print(f"  sha256 {info['sha256']}")
    print("families:", ", ".join(m["families"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
