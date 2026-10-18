"""A memory objective: what counts as relevant for a session, said before it starts.

M1 (`research/prereg/m1-memory-objective.md`).

Similarity cannot tell which of five near-identical memories a session
needs:

- this plant's approved procedure;
- the same procedure at another plant;
- a draft;
- the version before the revision;
- a vendor's claim.

Every one of them matches the question. What decides it is the session's
purpose, which the store has never been told. A **memory objective** states
it, before the session, in two forms:

- **the statement**, in words, which can be given to the agent as rules
  (`prompt()`);
- **rules over memory metadata**, applied by retrieval at the same
  chokepoint as tenancy and lifecycle (`MemoryFabric.retrieve(objective=)`).
  A memory the objective excludes is never ranked, never exposed and never
  logged as a candidate, so propensities stay honest.

Rules are an OR of AND-groups for inclusion ("approved procedures for this
plant, *or* plant-wide safety rules"), plus a list of exclusions, any of which
rules a memory out. A rule names a context field, an operator and a value.
`compile_objective` asks a model to turn a statement into rules against the
fields the store actually has, and drops what it cannot validate, saying so.
A compiled objective is something to review, not to trust: M1 measures how
often the compilation is right.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

OPS = ("eq", "neq", "in", "not_in", "gte", "lte")


@dataclass(frozen=True)
class Rule:
    field: str
    op: str
    value: Any

    def __post_init__(self) -> None:
        if self.op not in OPS:
            raise ValueError(f"unknown operator {self.op!r}; known: {OPS}")

    def holds(self, context: Mapping[str, Any]) -> bool:
        """Whether a memory's context satisfies this rule. A missing field satisfies nothing."""
        if self.field not in context:
            return False
        actual = context[self.field]
        if self.op == "eq":
            return bool(actual == self.value)
        if self.op == "neq":
            return bool(actual != self.value)
        if self.op == "in":
            return actual in (self.value if isinstance(self.value, (list, tuple)) else [self.value])
        if self.op == "not_in":
            return actual not in (self.value if isinstance(self.value, (list, tuple)) else [self.value])
        try:
            if self.op == "gte":
                return bool(actual >= self.value)
            return bool(actual <= self.value)
        except TypeError:
            return False

    def to_json(self) -> dict[str, Any]:
        return {"field": self.field, "op": self.op, "value": self.value}


@dataclass(frozen=True)
class MemoryObjective:
    statement: str
    include: tuple[tuple[Rule, ...], ...] = ()
    exclude: tuple[Rule, ...] = ()
    dropped: tuple[str, ...] = field(default=())
    """Rules a compiler proposed that could not be validated, kept for review."""

    def admits(self, context: Mapping[str, Any]) -> bool:
        if any(rule.holds(context) for rule in self.exclude):
            return False
        if not self.include:
            return True
        return any(all(rule.holds(context) for rule in group) for group in self.include)

    def prompt(self) -> str:
        """The objective as rules for an agent's system prompt."""
        lines = [f"Session objective: {self.statement}"]
        for group in self.include:
            lines.append("Relevant: notes where " + " and ".join(_say(r) for r in group) + ".")
        for rule in self.exclude:
            lines.append("Irrelevant: notes where " + _say(rule) + ". Do not use them.")
        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {"statement": self.statement,
                "include": [[r.to_json() for r in group] for group in self.include],
                "exclude": [r.to_json() for r in self.exclude],
                "dropped": list(self.dropped)}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "MemoryObjective":
        return cls(statement=str(data.get("statement", "")),
                   include=tuple(tuple(Rule(**r) for r in group) for group in data.get("include", [])),
                   exclude=tuple(Rule(**r) for r in data.get("exclude", [])),
                   dropped=tuple(data.get("dropped", [])))


def _say(rule: Rule) -> str:
    words = {"eq": "is", "neq": "is not", "in": "is one of", "not_in": "is none of",
             "gte": "is at least", "lte": "is at most"}
    return f"{rule.field} {words[rule.op]} {rule.value!r}"


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "include": {"type": "array", "items": {"type": "array", "items": {
            "type": "object", "properties": {"field": {"type": "string"},
                                             "op": {"type": "string", "enum": list(OPS)},
                                             "value": {}},
            "required": ["field", "op", "value"]}}},
        "exclude": {"type": "array", "items": {
            "type": "object", "properties": {"field": {"type": "string"},
                                             "op": {"type": "string", "enum": list(OPS)},
                                             "value": {}},
            "required": ["field", "op", "value"]}},
    },
    "required": ["include", "exclude"],
}


def validate(raw: Mapping[str, Any], fields: Mapping[str, Sequence[Any]],
             statement: str) -> MemoryObjective:
    """Keep only rules over known fields, known operators and values the store has."""
    dropped: list[str] = []

    def check(item: Any) -> Rule | None:
        try:
            rule = Rule(field=str(item["field"]), op=str(item["op"]), value=item["value"])
        except (KeyError, TypeError, ValueError) as exc:
            dropped.append(f"malformed rule {item!r}: {exc}")
            return None
        if rule.field not in fields:
            dropped.append(f"unknown field {rule.field!r}")
            return None
        known = list(fields[rule.field])
        rule = Rule(rule.field, rule.op, _coerce(rule.value, known))
        values = rule.value if isinstance(rule.value, (list, tuple)) else [rule.value]
        if rule.op in ("eq", "neq", "in", "not_in") and known and not all(v in known for v in values):
            dropped.append(f"value {rule.value!r} not seen for {rule.field!r}")
            return None
        return rule

    include = []
    for group in raw.get("include") or []:
        rules = [r for r in (check(i) for i in (group or [])) if r is not None]
        if rules:
            include.append(tuple(rules))
    exclude = tuple(r for r in (check(i) for i in raw.get("exclude") or []) if r is not None)
    return MemoryObjective(statement, tuple(include), exclude, tuple(dropped))


def _coerce(value: Any, known: Sequence[Any]) -> Any:
    """Give a proposed value the type the store's values have ("2026" -> 2026).

    A model writes JSON, so a year arrives as a string about as often as a
    number. Without this, a correct rule is dropped as "value not seen", which
    M1's dev pilot found.
    """
    if isinstance(value, (list, tuple)):
        return [_coerce(v, known) for v in value]
    for example in known:
        if isinstance(example, bool) or not isinstance(example, (int, float)):
            continue
        try:
            return type(example)(value)
        except (TypeError, ValueError):
            return value
    if known and all(isinstance(k, str) for k in known) and not isinstance(value, str):
        return str(value)
    return value


def sanity(objective: MemoryObjective, contexts: Sequence[Mapping[str, Any]]) -> str | None:
    """Why this objective should not be applied to a store with these contexts, or None.

    An objective that admits **nothing** is a compilation error, not a session
    with nothing relevant. In M1's dev pilot a model wrote "exclude every
    source", which would have blanked retrieval for the whole session. The
    caller should fall back to no filter, keep the statement in the prompt,
    and show the reason to the person who wrote the objective.
    """
    if not contexts:
        return None
    if not any(objective.admits(c) for c in contexts):
        return "it admits none of the store's memories"
    return None


def compile_objective(statement: str, fields: Mapping[str, Sequence[Any]], client: Any,
                      model: str) -> MemoryObjective:
    """Ask a model to turn a statement into rules over the store's fields, then validate."""
    described = "\n".join(f"- {name}: one of {sorted(map(str, values))}"
                          for name, values in sorted(fields.items()))
    messages = [
        {"role": "system", "content": (
            "You turn a session objective into retrieval rules over memory metadata. "
            "Use only these fields and values:\n" + described + "\n"
            "Return JSON: include is a list of alternatives, each a list of conditions that must "
            "all hold; exclude is a list of conditions any one of which rules a memory out. "
            "Operators: eq, neq, in, not_in, gte, lte. "
            "Put everything the statement calls relevant in include, with all of its conditions "
            "in one alternative. Use exclude only for what the statement names as irrelevant, "
            "and never exclude a value that an include alternative needs.")},
        {"role": "user", "content": statement},
    ]
    reply = client.chat(model, messages, temperature=0.0, num_predict=512, schema=SCHEMA)
    text = (reply.get("message") or {}).get("content", "") if isinstance(reply, Mapping) else ""
    try:
        raw = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return MemoryObjective(statement, dropped=(f"unparseable compiler reply: {text[:200]!r}",))
    return validate(raw if isinstance(raw, Mapping) else {}, fields, statement)
