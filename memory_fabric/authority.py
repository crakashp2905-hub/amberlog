"""Origin-bound authority: what a memory may be used *for*, fixed by where it came from.

A summary, a tool's copy or a peer's import of an injected note is a new
memory with a new author. Judged on its own, it looks clean. This module
judges it by its **origin**: every source it descends from, through lineage
(`derive`), recognised copies (`copy_of`) and federation (`context.federation`,
including the authority the origin store sent with it).

Three things are kept apart, because conflating them is how poison gains
authority:

- **The source** (`origins`): who first observed or wrote the content: a
  local agent, `tool:<name>`, or `<store>/<agent>` for a peer's author.
- **The transformer** (`transformed_by`): who summarised, copied or imported
  it. A trusted summariser does not make an untrusted source trusted.
- **The kind** (`kind`): an `instruction` (it tells someone what to do or
  say), an `observation` (it reports the world) or a `derived_claim` (a
  conclusion from other memories). Bound at the **first write**: the first
  version's `context["kind"]`, or inferred then. A later version cannot
  change it.

**Trust** is one of `untrusted` < `unverified` < `elevated`. Every memory
starts at most `unverified` and inherits the *lowest* trust of everything it
descends from. Reasons are of two classes:

- **hard**: a withdrawn or contested ancestor, a source caught being hostile,
  an ancestor that is an instruction. No elevation lifts these; only removing
  the cause does (review, a correction).
- **soft**: a tool output, an import, an external origin. Lifted only by
  `MemoryFabric.elevate`: a recorded decision, by an approver who is not the
  memory's author, about one exact version.

**A successful outcome is not evidence that a memory was right.** Nothing
here reads outcomes, and `tests/test_authority.py` checks that recording one
leaves authority unchanged. An agent that succeeded while relying on poison
was lucky; credit (`estimators.py`) and authority are different questions.

Consequential use goes through `ActionGate`, which refuses evidence below a
tool rule's `min_authority` (default `unverified`), and any `instruction`
evidence (an instruction is not evidence).
"""

from __future__ import annotations

__stability__ = "beta"

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from .governance import directive

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

KINDS = ("instruction", "observation", "derived_claim")
UNTRUSTED, UNVERIFIED, ELEVATED = "untrusted", "unverified", "elevated"
LEVELS = (UNTRUSTED, UNVERIFIED, ELEVATED)
EXTERNAL_PREFIXES = ("tool:", "web:", "external:", "email:", "document:")

# Reason codes.
WITHDRAWN = "withdrawn_ancestor"
CONTESTED = "contested_ancestor"
HOSTILE_SOURCE = "hostile_source"
INSTRUCTION = "instruction_ancestor"
TOOL_OUTPUT = "external_origin"
IMPORTED = "imported"
ORIGIN_FLOOR = "origin_store_floor"
HARD = frozenset({WITHDRAWN, CONTESTED, HOSTILE_SOURCE, INSTRUCTION})


@dataclass(frozen=True)
class Authority:
    memory_id: str
    version: int
    kind: str
    trust: str
    origins: tuple[str, ...]
    transformed_by: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    elevated_by: str | None = None
    via: Mapping[str, str] = field(default_factory=dict)
    """For each reason, the ancestor that caused it: what a reviewer reads."""

    @property
    def hard(self) -> bool:
        return any(r in HARD for r in self.reasons)

    def at_least(self, level: str) -> bool:
        return LEVELS.index(self.trust) >= LEVELS.index(level)

    def to_wire(self) -> dict[str, Any]:
        """What an origin store sends with an offer: ids and codes, never content."""
        return {"kind": self.kind, "trust": self.trust, "reasons": list(self.reasons),
                "origins": list(self.origins)}


def _first(fabric: "MemoryFabric", memory_id: str) -> Any:
    history = fabric.state.history.get(memory_id) or []
    return history[0] if history else fabric.state.memories[memory_id]


def _own_kind(memory: Any, first: Any) -> str:
    # Bound at the first write, and only ever escalated: a later version that
    # reads as an instruction makes the memory one (delayed activation), and
    # no later version can relabel an instruction as anything else.
    if directive.assess(memory.content).flagged:
        return "instruction"
    declared = (first.context or {}).get("kind")
    if declared in KINDS:
        return str(declared)
    if first.provenance.parents:
        return "derived_claim"
    if directive.assess(first.content).flagged:
        return "instruction"
    return "observation"


def _origin(fabric: "MemoryFabric", memory: Any, first: Any) -> str:
    fed = (memory.context or {}).get("federation")
    if isinstance(fed, Mapping):
        return f"{fed.get('store')}/{fed.get('agent')}"
    declared = (first.context or {}).get("origin")
    if isinstance(declared, str) and declared:
        return declared
    return str(first.provenance.created_by)


def of(fabric: "MemoryFabric", memory_id: str) -> Authority:
    """The origin-bound authority of a memory's current version."""
    from . import hindsight
    from .model import LifecycleState, WITHDRAWN_STATES

    hostile = hindsight.discredited_authors(fabric, hindsight.HOSTILE)
    elevations = _elevations(fabric)
    memory = fabric.state.memories[memory_id]

    reasons: dict[str, str] = {}
    origins: set[str] = set()
    transformers: set[str] = set()
    seen: set[str] = set()
    stack = [memory_id]
    while stack:
        current = stack.pop()
        if current in seen or current not in fabric.state.memories:
            continue
        seen.add(current)
        node = fabric.state.memories[current]
        first = _first(fabric, current)
        kind = _own_kind(node, first)
        parents = [p for p, _ in node.provenance.parents]
        copy = fabric.state.copy_of.get(current)
        fed = (node.context or {}).get("federation")
        is_source = not parents and copy is None
        source = _origin(fabric, node, first)
        if is_source:
            origins.add(source)
        else:
            transformers.add(str(node.provenance.created_by))
        if current != memory_id and kind == "instruction":
            reasons.setdefault(INSTRUCTION, current)
        if node.lifecycle_state in WITHDRAWN_STATES:
            reasons.setdefault(WITHDRAWN, current)
        elif node.lifecycle_state is LifecycleState.CONTESTED:
            reasons.setdefault(CONTESTED, current)
        author = source if isinstance(fed, Mapping) else str(node.provenance.created_by)
        if author in hostile or source in hostile:
            reasons.setdefault(HOSTILE_SOURCE, current)
        if isinstance(fed, Mapping):
            reasons.setdefault(IMPORTED, current)
            floor = fed.get("authority")
            if isinstance(floor, Mapping):
                for code in floor.get("reasons", ()):
                    if code in HARD:
                        reasons.setdefault(str(code), current)
                if floor.get("trust") == UNTRUSTED:
                    reasons.setdefault(ORIGIN_FLOOR, current)
                if floor.get("kind") == "instruction":
                    reasons.setdefault(INSTRUCTION, current)
        if source.startswith(EXTERNAL_PREFIXES):
            reasons.setdefault(TOOL_OUTPUT, current)
        # An ancestor elevated at its current version vouches for its soft
        # reasons only; everything above it is still walked for hard ones.
        stack.extend(parents)
        if copy is not None:
            stack.append(copy)

    own_kind = _own_kind(memory, _first(fabric, memory_id))
    if own_kind == "instruction":
        reasons.setdefault(INSTRUCTION, memory_id)
    hard = any(r in HARD for r in reasons)
    elevated_by = elevations.get((memory_id, memory.version))
    if hard:
        trust = UNTRUSTED
    elif elevated_by:
        trust = ELEVATED
    elif reasons:
        trust = UNTRUSTED
    else:
        trust = UNVERIFIED
    return Authority(memory_id=memory_id, version=memory.version, kind=own_kind, trust=trust,
                     origins=tuple(sorted(origins)), transformed_by=tuple(sorted(transformers)),
                     reasons=tuple(sorted(reasons)),
                     elevated_by=elevated_by if trust == ELEVATED else None,
                     via=dict(sorted(reasons.items())))


def _elevations(fabric: "MemoryFabric") -> dict[tuple[str, int], str]:
    from . import events as ev

    out: dict[tuple[str, int], str] = {}
    for event in fabric.log.read_types([ev.EventType.AUTHORITY_ELEVATED]):
        p = event.payload
        key = (str(p["memory_id"]), int(p["version"]))
        if p.get("revoked"):
            out.pop(key, None)
        else:
            out[key] = str(p["approver"])
    return out
