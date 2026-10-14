"""Structure extracted from a memory at write time.

Registered in `research/prereg/x1-extraction-at-ingest.md`.

## The gap, in one line

Similarity cannot express what a memory **modifies** or whether it **asserts**
anything. `multi_hop_4` is 0.000 sufficiency for every arm at every budget
tried on both splits, and **1.000 given declared relations**; abstention has
four eliminated signal families behind it.

A third failure, `implied_by_default`, was part of this rationale and **has
been withdrawn from it**: its 0.000 was measured at k=3, and at k=5 a plain
lexical baseline solves the family on dev
(`research/results/facet-v1-implied.md` section 11). The applicability
machinery below is kept, because the mechanism is sound and cheap and the
family is still unreachable on test — but it is **not** evidence for
extraction, and X1 does not score it.

## One call per memory, not one per pair

A model asked "does A modify B?" is O(n²) and infeasible at any corpus size
this project measures. So the call is **per write**, producing a structured
record, and relations are inferred by **matching records** with no further
calls. That is what makes the approach tractable, and it is the shape
Hindsight's `retain` uses.

## Why a model and not a pattern

`research/results/relations-ceiling.md` declined to build a *pattern*
extractor, and the reason was circularity: the target text is this project's
own generated phrasing, so a regex for *"except at the … and … sites"* would
pass by construction and measure its own fit rather than the mechanism's. **A
general-purpose model is not fitted to my phrasing**, so the objection does not
transfer. The circularity was a property of the pattern.

The deterministic `StubExtractor` in this module is therefore **not an arm**. It
exists so the structural inference has tests that do not call a model, and a
result that quoted it as a measurement would be the pattern problem wearing a
different hat.

## Cost is the thing to watch

Every call goes through `OllamaClient`, which logs model, prompt hash, token
counts and tokens-as-cost — AGENTS.md's rule — and the prompt is hashed rather
than stored because it contains memory content, which is what the governance
layer exists to keep out of secondary surfaces.

At a second a write, ten thousand memories cost three hours. Prediction 4 of the
registration is that this makes extraction a batch job rather than an
ingest-path step, which is a product conclusion and is why nothing here is
wired into `remember` by default.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .relations import RelationKind

PROMPT = """You extract structure from a single short factual statement.

Return ONLY a JSON object with these keys:
  "asserts": true if the statement says what something IS or REQUIRES; false if
             it only adjusts, qualifies or comments on another statement.
  "subject": the thing the statement is about, lowercase, or null.
  "predicate": the property being stated, as one or two lowercase words
             ("clearance", "tyre pressure", "inspection interval"), or null.
  "value": the value stated, verbatim, or null.
  "scope": list of specific entities (sites, units, seasons) the statement
             applies to. Empty list if it applies generally.
  "excepts": list of entities explicitly EXCLUDED from it ("except at X").
  "modifies": the predicate this statement ADJUSTS rather than states, or null.
             Use this for statements like "add 0.4 bar to the X figure".
  "adjustment": the adjustment, verbatim, or null.

Statement: {content}

JSON:"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "asserts": {"type": "boolean"},
        "subject": {"type": ["string", "null"]},
        "predicate": {"type": ["string", "null"]},
        "value": {"type": ["string", "null"]},
        "scope": {"type": "array", "items": {"type": "string"}},
        "excepts": {"type": "array", "items": {"type": "string"}},
        "modifies": {"type": ["string", "null"]},
        "adjustment": {"type": ["string", "null"]},
    },
    "required": ["asserts", "subject", "predicate", "scope", "excepts",
                 "modifies"],
}
"""The same nine keys, as a schema Ollama enforces **during** sampling.

**What this buys, measured rather than assumed: nothing, at a price.** It
guarantees the *shape* of the reply and improves no figure. Across **seven
models in both modes** (`research/results/x1-extraction.md` section 10) the
schema never helped, made the false-positive column **worse** on three models,
and cost `gemma2` **58%** more wall time.

The mechanism is worth stating because it is the opposite of the intuition:
a schema that permits a `modifies` field does not stop a model filling it in,
and forcing the shape makes a model **more** willing to guess. `llama3.2:3b`
goes from 12/17 to 3/17 on ordinary statements under it.

I introduced this believing the opposite, on the strength of one observation:
a 1.5B model under the schema produced the correct `modifies` target that the
7B model got wrong free-form. The control says that was a property of **that
model**, not of the constraint. The first version of this docstring claimed
constraining the shape was "both the accuracy fix and the cost fix", and it is
neither.

It is kept, on narrower grounds: a guaranteed shape means `parse()` never has
to recover from prose, which removes a failure mode from the ingest path even
though it does not change what the measured models extract. Where latency
matters more than that guarantee, `constrained=False` is the faster setting on
this hardware.

`parse()` is kept regardless, because the schema is enforced by the server and
a caller may be pointed at one that does not enforce it.
"""


@dataclass(frozen=True)
class Extracted:
    """What one memory asserts, scopes, excludes or adjusts."""

    memory_id: str
    asserts: bool = True
    subject: str | None = None
    predicate: str | None = None
    value: str | None = None
    scope: tuple[str, ...] = ()
    excepts: tuple[str, ...] = ()
    modifies: str | None = None
    adjustment: str | None = None
    parsed: bool = True
    """Whether a structured record was recovered from the model's reply.

    The module docstring for `parse()` claimed a caller could tell "the
    extractor had nothing to say" from "the memory asserts nothing" **by this
    field**, and the field did not exist. The consequence was not cosmetic: an
    unparseable reply became `Extracted(asserts=False)`, which has no
    `modify_target` and no `excepts`, so every downstream classifier read it as
    an ordinary statement -- the majority class. A model that failed on every
    call scored **17/17** on the column built to catch bad behaviour.
    """

    @property
    def is_default(self) -> bool:
        """A rule with named exclusions.

        The `implied_by_default` shape: it names neither the unit nor the site
        asked about, so it is not *similar* to the query, and its applicability
        is a property of what it excludes.

        The first version also required an empty `scope`, which was a schema
        error rather than a refinement: *"all yard vehicles run 3.9 bar in
        winter, except at the harbour and quarry sites"* is scoped to a season
        **and** excepts two sites, and every model tested reported the season
        as scope. Exclusions are what make a default a default.
        """
        return self.parsed and bool(self.excepts)

    @property
    def modify_target(self) -> str | None:
        """What this record adjusts, from whichever field the model used.

        Models disagree about where it goes. `gemma2` fills `modifies`
        correctly; `qwen2.5:7b` recognises the statement asserts nothing and
        puts the target in `predicate` instead. Reading both is robustness
        across models, not accommodation of one -- a parser that only
        understood the field one model happened to choose would make the result
        a property of that choice.
        """
        if self.modifies:
            return self.modifies
        if not self.asserts and self.predicate:
            return self.predicate
        return None

    @property
    def is_modifier(self) -> bool:
        return self.parsed and bool(self.modify_target) and not self.asserts

    @property
    def is_adjustment(self) -> bool:
        """A modifier that applies to named entities rather than generally.

        *"At the depot-12 site, add 0.35 bar to the axle-set figure as a
        salt-corrosion margin"* adjusts a quantity **and** names where it
        applies. `gemma2` extracts exactly that:
        `modifies='axle-set figure'`, `scope=('depot-12',)`.

        This is the distinction X1 was missing, and the reason its mechanism
        scored 0.000. X1 tried to reach such a record through a
        memory-to-memory `QUALIFIES` relation, inferred by matching `modifies`
        against another memory's `predicate`. That cannot work, and not because
        of the models: the corpus holds **twelve** of these adjustments
        differing only by site name, so an adjustment does not qualify one rule
        rather than another -- all twelve qualify every rule equally. Which one
        applies is a property of the **query's** entities, exactly as a
        default's applicability is a property of what it excludes
        (`research/results/x1-extraction.md` section 11).

        So it is admitted the way a default is, and not related the way a
        premise is.
        """
        return self.is_modifier and bool(self.scope)

    def applies_to(self, entities: Iterable[str]) -> bool:
        """Whether this record covers a query about these entities.

        A **default** applies unless it excepts one of them — the inference no
        similarity measure can make, because the default mentions none of them
        at all. Its `scope` is deliberately **not** consulted, and that is the
        second half of the same schema error `is_default` already corrected:
        `scope` mixes dimensions. Every model tested put the *season* of "all
        yard vehicles run 3.9 bar in winter, except at the harbour and quarry
        sites" into `scope`, while a caller's `entities` are units and sites, so
        requiring the query to name a scope entity made every default
        inapplicable. The mechanism would have done nothing and an end-to-end
        run would have reported it as "extraction does not help".

        A **non-default** scoped record still has to name one of them: there the
        scope is what the statement is about rather than when it holds.
        """
        wanted = {e.lower() for e in entities}
        if any(e in wanted for e in self.excepts):
            return False
        if self.scope and not self.is_default:
            return any(e in wanted for e in self.scope)
        return True


class Extractor(Protocol):
    def extract(self, memory_id: str, content: str) -> Extracted: ...


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


_LEADING = re.compile(r"^(?:at|in|on|for)\s+(?:the\s+)?")
_TRAILING = re.compile(r"\s+(?:site|sites|depot|depots|location|locations)$")


def _entities(text: str) -> list[str]:
    """Split an exclusion phrase into the entities it names.

    Models return exclusions as prose as often as as a list: `qwen2.5:7b` gave
    `["at the harbour and quarry sites"]` where `gemma2` gave
    `["harbour", "quarry sites"]`. Generic English list-splitting plus
    stripping a leading preposition and a trailing noun -- not a pattern for
    any fixture's phrasing, and necessary because applicability compares against
    entity names.
    """
    out: list[str] = []
    # Word boundaries matter, and they were lost once: `\b` is a valid
    # Python escape for backspace, so a single-backslash occurrence was
    # written to this file as an invisible control character and the split
    # silently stopped matching whole words.
    for part in re.split(r",|\band\b|\bor\b", text):
        cleaned = _TRAILING.sub("", _LEADING.sub("", part.strip())).strip()
        if cleaned:
            out.append(cleaned)
    return out


def _norm_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[str] = []
    for item in value:
        text = _norm(item)
        if text:
            out.extend(_entities(text))
    return tuple(dict.fromkeys(out))


def parse(memory_id: str, raw: str) -> Extracted:
    """Parse a model's reply, tolerating the ways models wrap JSON.

    A model that returns prose, fenced JSON, or JSON with a preamble is the
    normal case rather than an error, so the first balanced object in the reply
    is taken. A reply with none yields a record that asserts nothing and
    carries no structure, which is the honest representation of "the extractor
    had nothing to say" and is distinguishable from "the memory asserts
    nothing" by `parsed`, which is now a field rather than an aspiration.
    """
    found = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not found:
        return Extracted(memory_id=memory_id, asserts=False, parsed=False)
    try:
        data = json.loads(found.group(0))
    except (ValueError, TypeError):
        return Extracted(memory_id=memory_id, asserts=False, parsed=False)
    if not isinstance(data, Mapping):
        return Extracted(memory_id=memory_id, asserts=False, parsed=False)
    if not any(key in data for key in SCHEMA["properties"]):
        # An object, but not *this* object. A model that replies
        # `{"answer": "3.9 bar"}` has not extracted a record, and counting it
        # as one would put it in the majority class with everything that
        # genuinely asserts nothing -- the same error `parsed` exists to fix,
        # one level in.
        return Extracted(memory_id=memory_id, asserts=False, parsed=False)
    return Extracted(
        memory_id=memory_id,
        asserts=bool(data.get("asserts", True)),
        subject=_norm(data.get("subject")),
        predicate=_norm(data.get("predicate")),
        value=_norm(data.get("value")),
        scope=_norm_list(data.get("scope")),
        excepts=_norm_list(data.get("excepts")),
        modifies=_norm(data.get("modifies")),
        adjustment=_norm(data.get("adjustment")),
    )


@dataclass
class ModelExtractor:
    """One `OllamaClient.chat` call per memory.

    Temperature 0 and a JSON-only instruction, because the output is an index
    and an index that varies between runs cannot be compared across them.

    `constrained` passes `SCHEMA` to the client and defaults to **off**, which
    is where the measurement put it. Across seven models in both modes
    (`research/results/x1-extraction.md` section 10) the schema never improved
    a figure, made the false-positive column **worse** on three models, and
    cost `gemma2` 58% more wall time. It is kept as a flag because a caller
    whose parser cannot tolerate prose may still want the guaranteed shape.
    """

    client: Any
    model: str = "gemma2:latest"
    """The only model measured to produce a usable extraction of both sides of
    a relation; see sections 10 and 11 of the result. `qwen2.5:7b` was the
    first default and extracts `modifies` as the verb `'add'`, which no
    predicate matches."""

    constrained: bool = False
    think: bool | None = False
    """Reasoning trace off by default, because this task has no use for one.

    A reasoning model given 220 output tokens spends them reasoning:
    `qwen3:1.7b` hit the cap on 12 of 12 calls and never emitted the object.
    `None` leaves the server's default, which is what the figures measured
    before this existed used; `True` is here for completeness and is not a
    configuration any measurement recommends.
    """
    _cache: dict[str, Extracted] = field(default_factory=dict)

    def extract(self, memory_id: str, content: str) -> Extracted:
        cached = self._cache.get(content)
        if cached is not None:
            # Keyed on content, not id: the same sentence extracts the same
            # structure, and a benchmark writes the same filler into hundreds
            # of corpora. Without this the cost is the measurement.
            return Extracted(**{**cached.__dict__, "memory_id": memory_id})
        kwargs: dict[str, Any] = {}
        if self.constrained:
            kwargs["schema"] = SCHEMA
        if self.think is not None:
            kwargs["think"] = self.think
        reply = self.client.chat(
            model=self.model,
            messages=[{"role": "user",
                       "content": PROMPT.format(content=content)}],
            temperature=0.0,
            # Enough for the nine-key object and no more. A structured reply
            # that runs long is a model narrating rather than extracting, and
            # paying for the narration would put it in the cost column.
            num_predict=220,
            **kwargs,
        )
        text = reply if isinstance(reply, str) else _reply_text(reply)
        record = parse(memory_id, text)
        self._cache[content] = record
        return record


def _reply_text(reply: Any) -> str:
    """Pull the assistant text out of whatever shape the client returns."""
    if isinstance(reply, Mapping):
        message = reply.get("message")
        if isinstance(message, Mapping):
            return str(message.get("content") or "")
        for key in ("content", "response", "text"):
            if key in reply:
                return str(reply[key])
    return str(reply)


class StubExtractor:
    """Deterministic, for testing the structural half without a model.

    **Not an arm.** A stub fitted to this project's fixtures is the pattern
    problem the registration rejected; it exists so that relation inference,
    applicability and the no-model code paths have tests, and no result may
    quote it.
    """

    _ADD = re.compile(r"(?i)\badd\s+([\d.]+\s*\w+)\s+to\s+the\s+([\w -]+?)\s*(?:figure|value)?\b")
    _EXCEPT = re.compile(r"(?i)\bexcept\s+(?:at\s+)?(?:the\s+)?(.+?)(?:\s+sites?)?\.?$")

    def extract(self, memory_id: str, content: str) -> Extracted:
        add = self._ADD.search(content)
        if add:
            return Extracted(
                memory_id=memory_id, asserts=False,
                modifies=add.group(2).strip().lower(),
                adjustment=add.group(1).strip().lower(),
            )
        excepts: tuple[str, ...] = ()
        exc = self._EXCEPT.search(content)
        if exc:
            excepts = tuple(
                part.strip().lower()
                for part in re.split(r",|\band\b", exc.group(1))
                if part.strip()
            )
        return Extracted(memory_id=memory_id, asserts=True, excepts=excepts)


# --- structural inference, with no further model calls ----------------------


def _loose(text: str) -> str:
    """Hyphens and underscores to spaces, for comparing compound predicates.

    "axle-set" and "axle set" are the same predicate written two ways, and the
    models write both forms within one corpus.
    """
    return re.sub(r"[-_]+", " ", text).strip()


def infer_relations(records: Sequence[Extracted]
                    ) -> list[tuple[str, RelationKind, str]]:
    """Relations implied by the extracted records.

    A record that *modifies* a predicate qualifies every record that *states*
    it. No model call here: the edges fall out of matching two fields, which is
    what makes one call per memory enough.

    Matching is on the predicate, loosely and after normalisation: a modifier
    adjusting the "axle-set" figure and a rule whose predicate is "tyre
    pressure for the axle set" must meet, so hyphens and underscores collapse
    to spaces before comparing and containment either way counts. Without the
    normalisation those two never matched and the inference produced nothing,
    because the corpus writes the compound both ways.

    A tighter match would miss edges, and the registration's own prediction is
    that recall matters more than precision here -- a missed edge costs what
    the family already scores, which is zero.
    """
    stated: dict[str, list[str]] = {}
    for record in records:
        if record.asserts and record.predicate:
            stated.setdefault(_loose(record.predicate), []).append(
                record.memory_id)

    out: list[tuple[str, RelationKind, str]] = []
    for record in records:
        target = record.modify_target
        if not record.is_modifier or not target:
            continue
        loose = _loose(target)
        for predicate, ids in stated.items():
            if loose in predicate or predicate in loose:
                for memory_id in ids:
                    if memory_id != record.memory_id:
                        out.append(
                            (record.memory_id, RelationKind.QUALIFIES, memory_id))
    return out


def applicable_adjustments(records: Sequence[Extracted],
                           entities: Iterable[str]) -> list[str]:
    """Scoped adjustments that apply to a query about these entities.

    The counterpart of `applicable_defaults`, and the gap that measurement
    found: `_admit_defaults` admitted only records with **exceptions**, so a
    record carrying a scope and no exceptions -- which is what every
    site-scoped adjustment is -- had no path into a context at all. The
    extraction was correct and nothing consumed it.

    Measured ceiling for admitting these: `multi_hop_4` sufficiency 0.000 ->
    **1.000** on dev, 3 of 3 cases, and 0 of 3 on test where the chain
    retrieves the wrong sibling rule
    (`research/prereg/x3-scoped-adjustments.md`).
    """
    wanted = {e.lower() for e in entities}
    if not wanted:
        return []
    return [
        record.memory_id
        for record in records
        if record.is_adjustment and record.applies_to(wanted)
    ]


def applicable_defaults(records: Sequence[Extracted],
                        entities: Iterable[str]) -> list[str]:
    """Default rules that cover a query about these entities.

    The `implied_by_default` mechanism, and the one `EXCEPTS` could not provide:
    a memory-to-memory relation has nothing to attach to when the exception
    names a *site* rather than a memory
    (`research/results/relations-ceiling.md` section 3). Applicability is a
    property of the record, so it is answered here.
    """
    wanted = {e.lower() for e in entities}
    if not wanted:
        return []
    return [
        record.memory_id
        for record in records
        if record.is_default and record.applies_to(wanted)
    ]
