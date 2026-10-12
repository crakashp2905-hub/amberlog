"""TeamWorld — a multi-agent world for comparing memory systems.

Registered in `research/prereg/p3b-agent-teams.md`. This module is the runtime
priority 5 lists: agents with an execution loop, a shared task protocol, four
interchangeable memory backends, a fixed coordination policy and the counters
that make the comparison measurable.

## The agent is deterministic, and that is the design

"Does a team do better with Memory Fabric" is two questions: does the right
evidence reach the agent, and does the agent use it. [R6](../research/results/r6-downstream.md)
measured the second and **its dev finding did not replicate** — on a corpus a
model could simply read, perfect selection was worth +0.000.

So the agent here extracts whatever value its retrieved context states and
answers with it. It has no reading comprehension to add and none to lose, which
makes every difference between arms a property of the memory system. A real
model would mix the two contributions, and R6 showed its half is the noisier.
Stated in every write-up: **this does not measure whether a model uses good
evidence well.**

## One world, four memories

Every arm is driven by the same seeded schedule: the same facts discovered by
the same agents in the same rounds, the same corrections at the same times, the
same tasks assigned to the same agents. The only variable is where memory lives.

The coordination policy is deliberately fixed and dull — round-robin
assignment, no delegation, no review — because a policy that varied between
arms would make memory and coordination inseparable.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, Sequence

# Wide enough that 100 agents still get a fact each. At 8 units x 6 sites the
# pair space capped at 48, so the 50- and 100-agent runs covered an identical
# 96 facts and the larger one measured contention over a fixed fact space
# rather than a larger world. Both are worth measuring; only one of them was.
SITES = ("coastal", "inland", "northern", "harbour", "quarry", "estuary",
         "upland", "riverside", "airfield", "tidal", "depot-7", "depot-12")
UNITS = ("tug-1", "tug-3", "tug-8", "crane-2", "crane-5", "crane-9",
         "forklift-9", "forklift-14", "hoist-6", "hoist-12", "winch-2",
         "winch-5", "genset-4", "genset-10", "loader-3", "chiller-1")
VALUES = ("1.2 m", "1.8 m", "2.4 m", "3.0 m", "3.6 m", "4.2 m")


# --- the world --------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    """One attribute of one unit at one site, at one revision.

    Two attributes per (unit, site), and the second is load-bearing rather than
    decoration. With only one, a correction and its replacement concerned the
    same statement, so the naive `shared_blanket` rule -- suppress everything
    about this unit and site -- destroyed only what was already superseded and
    scored a perfect `wrong_invalidation_rate` of 0.000. The failure that rule
    actually commits is destroying *neighbouring valid knowledge*, and a world
    with one attribute per pair has no neighbouring knowledge to destroy.
    """

    unit: str
    site: str
    value: str
    revision: int
    attribute: str = "clearance"

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.unit, self.site, self.attribute)

    @property
    def pair(self) -> tuple[str, str]:
        return (self.unit, self.site)

    def statement(self) -> str:
        if self.attribute == "clearance":
            return (f"{self.unit} requires {self.value} of clearance at the "
                    f"{self.site} site.")
        return (f"{self.unit} has a {self.value} access gap at the "
                f"{self.site} site.")

    def question(self) -> str:
        if self.attribute == "clearance":
            return (f"How much clearance does {self.unit} require at the "
                    f"{self.site} site?")
        return (f"How large is the access gap for {self.unit} at the "
                f"{self.site} site?")


@dataclass
class Event:
    """One thing that happens in a round."""

    round: int
    kind: str          # discover | correct | duplicate | contradict | task
    agent: str
    fact: Fact
    note: str = ""


@dataclass
class World:
    """Ground truth and a schedule, built once and shared by every arm."""

    facts: dict[tuple[str, str, str], Fact]
    schedule: list[Event]
    agents: list[str]
    rounds: int
    # What the world currently holds, replayed as the schedule advances.
    current: dict[tuple[str, str, str], Fact] = field(default_factory=dict)
    withdrawn: set[str] = field(default_factory=set)
    reproducible: set[tuple[str, str, str]] = field(default_factory=set)
    """Facts an agent can go and re-measure on demand.

    Not all of them, and this is the modelling decision the first two versions
    of this world got wrong in opposite directions. With rediscovery free for
    everything, an isolated agent simply re-measures whatever it lacks and
    reaches 0.950 task success while paying 21.6 duplicate discoveries against
    the fabric's 5.4 -- so the primary metric could not see the cost, a
    baseline sat on the ceiling, and principle 8c's check fired.

    Half the facts are reproducible. For the other half the surveyor has gone,
    the document is unavailable, the gantry has been moved: memory is the only
    route to the answer, which is the condition under which a memory system is
    worth having at all.
    """

    def truth(self, key: tuple[str, str, str]) -> Fact | None:
        return self.current.get(key)


def build_world(seed: int, agents: int = 10, rounds: int = 60) -> World:
    """A world with all four injections on a fixed schedule.

    Written as a *schedule* rather than as live decisions so that every arm
    sees an identical history. An arm that influenced what happened next could
    not be compared against one that did not.
    """
    rng = random.Random(f"teamworld/{seed}")
    names = [f"ag-{i:02d}" for i in range(agents)]
    pairs = [(u, s) for u in UNITS for s in SITES]
    rng.shuffle(pairs)
    pairs = pairs[: max(8, agents)]

    base: dict[tuple[str, str, str], Fact] = {}
    keys: list[tuple[str, str, str]] = []
    for unit, site in pairs:
        for attribute in ("clearance", "access_gap"):
            fact = Fact(unit, site, rng.choice(VALUES), revision=1,
                        attribute=attribute)
            base[fact.key] = fact
            keys.append(fact.key)

    schedule: list[Event] = []
    # Phase 1: discovery. One agent finds each fact. Spread over early rounds,
    # so a task can legitimately precede the discovery that answers it.
    for index, key in enumerate(keys):
        schedule.append(Event(
            round=index % max(1, rounds // 4),
            kind="discover",
            agent=names[index % len(names)],
            fact=base[key],
        ))

    # Phase 2: the injections, each on a declared share of the facts.
    clearances = [k for k in keys if k[2] == "clearance"]
    # Corrections land on the clearance only. The access gap for the same unit
    # and site remains current, so a rule that invalidates by unit-and-site
    # overlap destroys knowledge that was never in question -- which is the
    # whole point of including `shared_blanket`.
    corrected = set(rng.sample(clearances, max(2, len(clearances) // 2)))
    duplicated = set(rng.sample(keys, max(2, len(keys) // 4)))
    contradicted = set(rng.sample(keys, max(2, len(keys) // 5)))

    for key in sorted(duplicated):
        # The same statement ingested again by a different agent. A plain store
        # now holds two votes for one source.
        schedule.append(Event(
            round=rounds // 3,
            kind="duplicate",
            agent=names[(keys.index(key) + 3) % len(names)],
            fact=base[key],
            note="re-ingested from the shared drive",
        ))

    for key in sorted(contradicted):
        unit, site, attribute = key
        other = [v for v in VALUES if v != base[key].value]
        schedule.append(Event(
            round=rounds // 3 + 1,
            kind="contradict",
            agent=names[(keys.index(key) + 5) % len(names)],
            fact=Fact(unit, site, rng.choice(other), revision=1,
                      attribute=attribute),
            note="a second agent measured something else",
        ))

    for key in sorted(corrected):
        unit, site, attribute = key
        old = base[key]
        replacement = [v for v in VALUES if v != old.value]
        schedule.append(Event(
            round=rounds // 2,
            kind="correct",
            agent=names[(keys.index(key) + 1) % len(names)],
            fact=Fact(unit, site, rng.choice(replacement), revision=2,
                      attribute=attribute),
            note="re-measured after the gantry was moved",
        ))

    # Phase 3: tasks, after every injection has landed, so each task has one
    # currently-correct answer.
    task_round = rounds - rounds // 4
    for index, key in enumerate(keys):
        schedule.append(Event(
            round=task_round + index % (rounds // 4),
            kind="task",
            agent=names[(index * 7) % len(names)],
            fact=base[key],
        ))

    schedule.sort(key=lambda e: (e.round, e.kind, e.agent, e.fact.unit,
                                 e.fact.site, e.fact.attribute))
    # Deterministic from the key, so every arm faces the same half.
    reproducible = {k for i, k in enumerate(sorted(keys)) if i % 2 == 0}
    return World(facts=base, schedule=schedule, agents=names, rounds=rounds,
                 reproducible=reproducible)


# --- the memory interface every arm implements ------------------------------


class Memory(Protocol):
    """What an agent can do with memory. Four implementations, one protocol."""

    def write(self, agent: str, content: str, fact_key: tuple[str, str]) -> str: ...

    def withdraw(self, agent: str, fact_key: tuple[str, str], reason: str) -> None: ...

    def read(self, agent: str, query: str, k: int = 5) -> list[tuple[str, str]]:
        """(memory_id, content), best first, already filtered by the backend."""
        ...

    def holds(self, agent: str, needle: str) -> bool:
        """Whether this agent could in principle reach a statement containing
        `needle`, ignoring whatever the backend withholds.

        The denominator for `wrong_invalidation_rate`. The first version of
        that metric asked only whether the *team* knew the fact, which scored
        `local` at 0.510 -- but an agent that never learned something has not
        had it invalidated, it simply never had it. Isolation and wrongful
        suppression are different failures and were being added together.
        """
        ...

    def close(self) -> None: ...


def _tokens(text: str) -> set[str]:
    return {t for t in text.lower().replace(".", " ").replace(",", " ").split()
            if len(t) > 2}


def _score(query: str, content: str) -> float:
    q, c = _tokens(query), _tokens(content)
    return len(q & c) / len(q) if q else 0.0


@dataclass
class LocalMemory:
    """Each agent knows only what it wrote.

    Isolation is a real defence and a real cost: an agent cannot act on another
    agent's withdrawn fact, and cannot benefit from another agent's discovery
    either, so the team rediscovers.
    """

    stores: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    _next: int = 0

    def write(self, agent: str, content: str, fact_key) -> str:
        self._next += 1
        mid = f"m{self._next}"
        self.stores.setdefault(agent, []).append((mid, content))
        return mid

    def withdraw(self, agent: str, fact_key, reason: str) -> None:
        # An agent can only withdraw from its own store, and only what it holds.
        rows = self.stores.get(agent, [])
        unit, site = fact_key[0], fact_key[1]
        self.stores[agent] = [
            (mid, c) for mid, c in rows if not (unit in c and site in c)
        ]

    def read(self, agent: str, query: str, k: int = 5):
        rows = self.stores.get(agent, [])
        ranked = sorted(rows, key=lambda r: (-_score(query, r[1]), r[0]))
        return [r for r in ranked[:k] if _score(query, r[1]) > 0]

    def holds(self, agent: str, needle: str) -> bool:
        return any(needle in c for _, c in self.stores.get(agent, []))

    def close(self) -> None:
        pass


@dataclass
class SharedMemory:
    """One append-only store, lexical top-k, no lifecycle and no provenance.

    The ordinary shared store, and the point of including it: a correction is
    just another write, so the superseded statement stays retrievable for ever
    and ranks exactly as well as it used to.
    """

    blanket: bool = False
    rows: list[tuple[str, str]] = field(default_factory=list)
    suppressed: set[str] = field(default_factory=set)
    _next: int = 0

    def write(self, agent: str, content: str, fact_key) -> str:
        self._next += 1
        mid = f"m{self._next}"
        self.rows.append((mid, content))
        return mid

    def withdraw(self, agent: str, fact_key, reason: str) -> None:
        if not self.blanket:
            # Nothing to do: the store has no notion of withdrawal. This is the
            # behaviour being measured, not an omission.
            return
        # The naive correction rule: suppress anything whose content overlaps
        # the withdrawn fact. It catches the superseded statement and
        # everything else about that unit and site, which is the failure
        # `wrong_invalidation_rate` exists to see.
        # Deliberately unit-and-site, not the whole key. That is the naive
        # rule a team writes: "this unit at this site was re-measured, so
        # distrust what we hold about it". It cannot tell the corrected
        # attribute from the one beside it that was never in question.
        unit, site = fact_key[0], fact_key[1]
        for mid, content in self.rows:
            if unit in content and site in content:
                self.suppressed.add(mid)

    def read(self, agent: str, query: str, k: int = 5):
        live = [(m, c) for m, c in self.rows if m not in self.suppressed]
        ranked = sorted(live, key=lambda r: (-_score(query, r[1]), r[0]))
        return [r for r in ranked[:k] if _score(query, r[1]) > 0]

    def holds(self, agent: str, needle: str) -> bool:
        # Ignores `suppressed` on purpose: the question is whether the store
        # has it, not whether the store is currently willing to show it.
        return any(needle in c for _, c in self.rows)

    def close(self) -> None:
        pass


class FabricMemory:
    """Memory Fabric at its defaults."""

    def __init__(self) -> None:
        from memory_fabric import MemoryFabric

        self.fabric = MemoryFabric(
            ":memory:", auto_activate=True, encrypt_content=False,
            retrieval="lexical",
        )
        self.by_key: dict[tuple[str, str], list[str]] = {}

    def write(self, agent: str, content: str, fact_key) -> str:
        mid = self.fabric.remember(agent_id=agent, content=content)
        self.by_key.setdefault(fact_key, []).append(mid)
        return mid

    def withdraw(self, agent: str, fact_key, reason: str) -> None:
        # Withdraw the statements of the superseded value, by id. A real
        # operator knows which memory is wrong; the point of the comparison is
        # what the store then does about copies and conclusions, not whether it
        # can guess.
        for mid in self.by_key.get(fact_key, []):
            memory = self.fabric.state.memories.get(mid)
            if memory is None:
                continue
            from memory_fabric.model import LifecycleState

            if memory.lifecycle_state is LifecycleState.QUARANTINED:
                continue
            self.fabric.quarantine(
                mid, reason=reason, actor=agent, basis="contradicted")

    def read(self, agent: str, query: str, k: int = 5):
        result = self.fabric.retrieve(
            agent_id=agent, query=query, k=k, min_relevance=0.0)
        return [(m.id, m.content) for m in result.exposed]

    def holds(self, agent: str, needle: str) -> bool:
        return any(needle in m.content
                   for m in self.fabric.state.memories.values())

    def close(self) -> None:
        self.fabric.close()


@dataclass
class OracleMemory:
    """Handed the currently-correct statement. The ceiling, not a method."""

    world: World

    def write(self, agent: str, content: str, fact_key) -> str:
        return "oracle"

    def withdraw(self, agent: str, fact_key, reason: str) -> None:
        pass

    def read(self, agent: str, query: str, k: int = 5):
        for key, fact in self.world.current.items():
            if fact.question() == query:
                return [("oracle", fact.statement())]
        return []

    def holds(self, agent: str, needle: str) -> bool:
        return any(needle in f.statement() for f in self.world.current.values())

    def close(self) -> None:
        pass


BACKENDS = ("local", "shared", "shared_blanket", "fabric", "oracle")


def build_memory(arm: str, world: World) -> Memory:
    if arm == "local":
        return LocalMemory()
    if arm == "shared":
        return SharedMemory(blanket=False)
    if arm == "shared_blanket":
        return SharedMemory(blanket=True)
    if arm == "fabric":
        return FabricMemory()
    if arm == "oracle":
        return OracleMemory(world=world)
    raise ValueError(arm)
