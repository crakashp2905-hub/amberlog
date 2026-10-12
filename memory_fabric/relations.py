"""Typed relations between memories that are not derivations.

## The gap these are for

Two families score **0.000 for every arm measured**, including a trained
embedder, and both diagnoses say the same thing:

- **`implied_by_default`** ([facet_v1](../research/results/facet-v1-implied.md)) — the answer is *"all yard vehicles run 3.9 bar in winter, except at the harbour and quarry sites"*. It names neither the unit nor the site asked about, so it is **not similar to the query** and no similarity measure can rank it. Reaching it means knowing a default applies unless an exception says otherwise.
- **`multi_hop_4`** ([P1](../research/results/p1-evidence-chain-reconstruction.md)) — the missing memory is *"at the depot-12 site, add 0.35 bar as a salt-corrosion margin"*. It supplies no query term and links nothing, so a chain that is already complete and connected has no reason to want it. It **modifies** the answer.

P1's own conclusion was that similarity is the wrong instrument. A typed
relation is a declared fact about how two memories stand to each other, which
is the alternative.

## Why these are not parent edges

The same reason a copy is not
(`memory_fabric/duplicates.py`): `_group_by_root` **spares** a memory that is
derivation-related to something already kept, because a premise and its
conclusion are not duplicates. Anything recorded as a parent inherits that
exemption and whatever else derivation means. A qualification is not a
derivation — the margin memory was not *derived from* the pressure rule, it
*modifies* it — so it gets its own relation, its own index and its own
retrieval step.

## What this module does not do

It does not **discover** relations. Something has to declare that A qualifies
B, and that is either a caller or an extraction step at ingest. Nothing here
extracts, and the reason is a measurement-integrity one rather than a
scheduling one: the two failing families are text this project's own generators
wrote, so a pattern matching *"except at the … and … sites"* would pass by
construction and measure the pattern's fit to my own phrasing.

So the first measurement is deliberately a **ceiling**: what declared
relations would be worth, given perfect declarations, which is what principle
8a asks for before the expensive part is built. See
`research/results/relations-ceiling.md`.
"""

from __future__ import annotations

from enum import Enum


class RelationKind(str, Enum):
    """How one memory stands to another, where neither derives from the other.

    Three, each from a measured failure rather than from a taxonomy. The
    roadmap's longer lists of edge types are not reproduced here: an edge kind
    that changes nothing about retrieval is ceremony, which is the argument
    `JustificationKind` already makes for keeping four of eight.
    """

    QUALIFIES = "qualifies"
    """The subject modifies the object's conclusion without being a premise of
    it. *"At depot-12, add 0.35 bar to the axle-set figure"* qualifies the
    axle-set rule: anyone relying on the rule at depot-12 needs both.

    Retrieval follows this **towards the qualifier**: a selected memory drags
    in whatever qualifies it, because the qualification changes the answer and
    its absence makes the answer wrong rather than incomplete.
    """

    EXCEPTS = "excepts"
    """The object is a general rule and the subject is outside its scope.

    Recorded on the *exception*, so a rule with four exceptions has four edges
    and the rule itself stays a single memory. A rule is a candidate for a
    query whose entities are not excepted, which is what makes
    `implied_by_default` reachable at all: the rule names neither the unit nor
    the site, and its applicability is a property of what it *excludes*.
    """

    PRECEDES = "precedes"
    """The subject happened before the object.

    Distinct from `valid_from` ordering, which says when a claim *held* rather
    than when an event *occurred*. LongMemEval's temporal-reasoning questions
    ask which of two events came first, and
    [its result](../research/results/longmemeval.md) measured that type as the
    weakest for every arm at 0.593 — while also measuring that filtering by
    validity costs 19 points there, because an ordering question needs the
    whole history rather than a snapshot of it.
    """


#: Relations whose object must be pulled in when the subject is selected, and
#: vice versa. Kept as data so the retrieval step reads a declaration rather
#: than a chain of `if`s.
PULLS_IN_SUBJECT = frozenset({RelationKind.QUALIFIES})
"""Selecting the object should also select the subject.

Only `QUALIFIES` so far. `EXCEPTS` deliberately does not: an exception is a
*reason not to use* a rule, so pulling it in on selection would add a memory
that argues against the one beside it, and `PRECEDES` is an ordering fact
rather than a completeness requirement.
"""
