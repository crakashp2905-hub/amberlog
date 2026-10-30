"""S1 -- CorrectionSim: correcting exact versions across stores under faults.

Registered in research/prereg/s1-federated-correction.md before this file.
Deterministic (no model): five stores per arm, real MemoryFabric instances and
the real dispatcher for the fabric-based arms, a dictionary store for
`naive_overwrite`. Each seed: 12 facts shared to 2-4 stores, onward re-shares
(one cycle), derived conclusions at recipients (some with an independent
second premise), 1-3 corrections per fact (two concurrent), scripted
partitions, shuffled delivery with duplicates. After every step, every
(store, fact) pair that should hold the fact is checked: serving exactly the
latest value, a superseded one, or nothing.

    python -m experiments.s1_correction_sim --seeds 20 --out s1.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

STORES = ("s0", "s1", "s2", "s3", "s4")
FACTS = 12
STEPS = 20
ARMS = ("retraction_only", "naive_overwrite", "delete_and_reshare", "versioned", "oracle")


@dataclass
class Plan:
    """One seed's script, identical for every arm."""
    origin: dict[str, str] = field(default_factory=dict)
    targets: dict[str, list[str]] = field(default_factory=dict)
    reshares: list[tuple[str, str, str]] = field(default_factory=list)   # (fact, via, to)
    corrections: dict[int, list[str]] = field(default_factory=dict)       # step -> facts
    offline: dict[int, set[str]] = field(default_factory=dict)            # step -> stores
    derived: list[tuple[str, str, bool]] = field(default_factory=list)    # (fact, store, independent)
    values: dict[str, list[int]] = field(default_factory=dict)            # fact -> value history


def plan(seed: int) -> Plan:
    rng = random.Random(seed)
    p = Plan()
    for n in range(FACTS):
        fid = f"F{n}"
        p.origin[fid] = rng.choice(STORES)
        others = [s for s in STORES if s != p.origin[fid]]
        p.targets[fid] = rng.sample(others, rng.randint(2, 4))
        p.values[fid] = [rng.randint(10, 99)]
    facts = sorted(p.origin)
    for fid in rng.sample(facts, 4):  # onward re-shares
        via = rng.choice(p.targets[fid])
        onward = [s for s in STORES if s not in p.targets[fid] and s != p.origin[fid]]
        if onward:
            p.reshares.append((fid, via, rng.choice(onward)))
    cyc = facts[0]  # one cycle back to the origin
    p.reshares.append((cyc, p.targets[cyc][0], p.origin[cyc]))
    concurrent = rng.sample(facts, 2)
    for fid in facts:
        count = rng.randint(1, 3)
        steps = sorted(rng.sample(range(2, STEPS - 2), count))
        if fid in concurrent and count >= 1:
            steps = sorted(set(steps + [steps[0] + 1]))  # a second before the first lands
        for step in steps:
            p.corrections.setdefault(step, []).append(fid)
            p.values[fid].append(rng.randint(10, 99))
    for _ in range(3):  # partitions
        store, start = rng.choice(STORES), rng.randint(1, STEPS - 6)
        for step in range(start, start + rng.randint(2, 5)):
            p.offline.setdefault(step, set()).add(store)
    for fid in rng.sample(facts, 6):
        p.derived.append((fid, rng.choice(p.targets[fid]), rng.random() < 0.5))
    return p


def holders(p: Plan, fid: str) -> list[str]:
    out = [p.origin[fid], *p.targets[fid]]
    out += [to for f, _, to in p.reshares if f == fid and to not in out]
    return out


def text(fid: str, value: int) -> str:
    return f"Setting {fid} is {value}."


# --- the fabric-based arms ----------------------------------------------------

class FabricArm:
    def __init__(self, mode: str, seed: int) -> None:
        from memory_fabric import MemoryFabric
        from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                                       rule_must_be_active,
                                                       rule_restricted_stays_private)
        from memory_fabric.transport import InProcessTransport, PeerRegistry

        rules = (rule_restricted_stays_private, rule_must_be_active,
                 rule_capabilities_must_be_granted)
        self.mode = mode
        self.rng = random.Random(seed * 7 + 1)
        self.f = {s: MemoryFabric(":memory:", firewall=Firewall(rules=rules), auto_activate=True)
                  for s in STORES}
        self.by_store_id = {fab.store_id: s for s, fab in self.f.items()}
        self.transport = InProcessTransport({fab.store_id: fab for fab in self.f.values()},
                                            registry=PeerRegistry())
        self.mid: dict[str, str] = {}              # fact -> origin memory id (current)
        self.edges: list[tuple[str, str, str]] = []  # (fact, from, to) share edges
        self.copy: dict[tuple[str, str], str] = {}   # (fact, store) -> latest local id there
        self.derived_ids: list[tuple[str, str, bool, str]] = []
        self.offline: set[str] = set()

    def _offer(self, fid: str, frm: str, to: str) -> None:
        from memory_fabric.federation import offer

        if to in self.offline or frm in self.offline:
            return
        source_id = self.mid[fid] if frm == self.origin(fid) else self.copy.get((fid, frm))
        if source_id is None:
            return
        src = self.f[frm]
        memory = src.state.memories.get(source_id)
        if memory is None or memory.lifecycle_state.value != "active":
            return
        if memory.scope.value != "federated":
            src.share(source_id, "federated", actor="admin")
        result = offer(src, source_id, self.f[to], recipient_agent="agent", activate=True)
        if result.accepted and result.imported_memory_id:
            self.copy[(fid, to)] = result.imported_memory_id

    def origin(self, fid: str) -> str:
        return self._origins[fid]

    def setup(self, p: Plan) -> None:
        from memory_fabric.justification import JustificationKind, justification_context

        self._origins = dict(p.origin)
        for fid in sorted(p.origin):
            o = p.origin[fid]
            self.mid[fid] = self.f[o].remember("author", text(fid, p.values[fid][0]), scope="team")
            for t in p.targets[fid]:
                self.edges.append((fid, o, t))
                self._offer(fid, o, t)
        for fid, via, to in p.reshares:
            self.edges.append((fid, via, to))
            self._offer(fid, via, to)
        for fid, store, independent in p.derived:
            premise = self.copy.get((fid, store))
            if premise is None:
                continue
            fab = self.f[store]
            if independent:
                other = fab.remember("local", f"Local observation backs {fid}.", scope="team")
                cid = fab.derive("local", f"Conclusion about {fid}.", parents=[premise, other],
                                 scope="team", context=justification_context(
                                     [(premise, JustificationKind.ALTERNATIVE),
                                      (other, JustificationKind.ALTERNATIVE)]))
            else:
                cid = fab.derive("local", f"Conclusion about {fid}.", parents=[premise],
                                 scope="team")
            self.derived_ids.append((fid, store, independent, cid))

    def correct(self, fid: str, value: int) -> None:
        o = self.origin(fid)
        fab = self.f[o]
        if self.mode == "delete_and_reshare":
            recipients = sorted(fab.state.shared_to.get(self.mid[fid], {}))
            fab.request_retraction(self.mid[fid], reason="corrected", recipients=recipients,
                                   actor="admin", basis="contradicted")
            self.mid[fid] = fab.remember("author", text(fid, value), scope="team")
            for key in [k for k in self.copy if k[0] == fid]:
                self.copy.pop(key)
        else:
            fab.revise(self.mid[fid], text(fid, value), agent_id="author", reason="correction")
            if self.mode == "versioned":
                fab.supersede_copies(self.mid[fid], actor="admin")

    def step(self) -> None:
        """Deliver what is due, shuffled, with duplicates; then re-offer current versions."""
        from memory_fabric.dispatcher import DispatchReport, Dispatcher
        from memory_fabric.outbox import now_ms

        self.transport.offline = {self.f[s].store_id for s in self.offline}
        for name in STORES:
            if name in self.offline:  # a partition is symmetric: it sends nothing either
                continue
            fab = self.f[name]
            dispatcher = Dispatcher(fab, self.transport)
            rows = fab.outbox.due(now_ms() + 10_000, limit=500)
            self.rng.shuffle(rows)
            for row in rows:
                report = DispatchReport()
                dispatcher._deliver(row, report)
                if self.rng.random() < 0.2:  # a duplicate delivery
                    try:
                        self.transport.send(row.recipient, row.retraction)
                    except Exception:  # noqa: BLE001 - an offline duplicate is just lost
                        pass
        for fid, frm, to in self.edges:  # the host re-offers the current version
            self._offer_if_stale(fid, frm, to)

    def _offer_if_stale(self, fid: str, frm: str, to: str) -> None:
        current = self.current_value(fid)
        have = self.served(fid, to)
        if have == {current}:
            return
        self._offer(fid, frm, to)

    def current_value(self, fid: str) -> int:
        memory = self.f[self.origin(fid)].state.memories[self.mid[fid]]
        return int(memory.content.rsplit(" ", 1)[1].rstrip("."))

    def served(self, fid: str, store: str) -> set[int]:
        out = set()
        for memory in self.f[store].state.memories.values():
            if memory.lifecycle_state.value == "active" and memory.content.startswith(f"Setting {fid} is "):
                out.add(int(memory.content.rsplit(" ", 1)[1].rstrip(".")))
        return out

    def independent_survival(self) -> list[bool]:
        return [self.f[store].state.memories[cid].lifecycle_state.value == "active"
                for _, store, independent, cid in self.derived_ids if independent]

    def dependent_rechecked(self) -> list[bool]:
        """Conclusions resting on a corrected fact alone: no longer active."""
        return [self.f[store].state.memories[cid].lifecycle_state.value != "active"
                for _, store, independent, cid in self.derived_ids if not independent]

    def status_truth(self) -> list[bool]:
        """Per retraction a sender recorded as enforced at a recipient: does that
        recipient in fact serve no copy of the withdrawn version?

        A forwarded retraction targets the sender's own copy, so the copies
        that count are the recipient's imports of whichever local memory at
        the sender stood for (origin, memory, version).
        """
        from memory_fabric.events import EventType

        def origin_of(memory: Any) -> dict[str, Any]:
            record = memory.context.get("federation")
            return record if isinstance(record, dict) else {}

        out = []
        for fab in self.f.values():
            for event in fab.log.read_types([EventType.RETRACTION_REQUESTED]):
                p = event.payload
                if p["origin_store_id"] == fab.store_id:
                    local = {p["origin_memory_id"]}
                else:
                    local = {mid for mid, m in fab.state.memories.items()
                             if origin_of(m).get("memory_id") == p["origin_memory_id"]
                             and origin_of(m).get("version") == p["origin_memory_version"]}
                acks = fab.outbox.acknowledgements(p["retraction_id"])
                for recipient, ack in acks.items():
                    if ack.state.value != "enforced" or recipient not in self.by_store_id:
                        continue
                    target = self.f[self.by_store_id[recipient]]
                    out.append(not any(
                        m.lifecycle_state.value == "active"
                        for m in target.state.memories.values()
                        # imports only: a conclusion derived from a copy
                        # inherits its context but is not a copy
                        if m.provenance.method.value == "imported"
                        and origin_of(m).get("store") == fab.store_id
                        and origin_of(m).get("memory_id") in local
                        and (p["origin_store_id"] != fab.store_id
                             or origin_of(m).get("version") == p["origin_memory_version"])))
        return out


# --- naive overwrite ---------------------------------------------------------------

class NaiveArm:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed * 7 + 2)
        self.store: dict[str, dict[str, int]] = {s: {} for s in STORES}
        self.queue: list[tuple[str, str, str, int]] = []  # (from, to, fact, value)
        self.offline: set[str] = set()
        self.current: dict[str, int] = {}
        self.holders: dict[str, list[str]] = {}

    def setup(self, p: Plan) -> None:
        for fid in sorted(p.origin):
            self.current[fid] = p.values[fid][0]
            self.holders[fid] = holders(p, fid)
            self.store[p.origin[fid]][fid] = p.values[fid][0]
            for to in self.holders[fid][1:]:
                self.queue.append((p.origin[fid], to, fid, p.values[fid][0]))

    def correct(self, fid: str, value: int, origin: str) -> None:
        self.current[fid] = value
        self.store[origin][fid] = value
        for to in self.holders[fid]:
            if to != origin:
                self.queue.append((origin, to, fid, value))

    def step(self) -> None:
        self.rng.shuffle(self.queue)
        kept = []
        for item in self.queue:
            frm, to, fid, value = item
            if to in self.offline or frm in self.offline:
                kept.append(item)
                continue
            self.store[to][fid] = value  # last arrival wins
            if self.rng.random() < 0.2:
                kept.append(item)  # a duplicate, delivered later
        self.queue = kept

    def served(self, fid: str, store: str) -> set[int]:
        return {self.store[store][fid]} if fid in self.store[store] else set()

    def current_value(self, fid: str) -> int:
        return self.current[fid]


# --- one seed --------------------------------------------------------------------

def run_seed(seed: int) -> dict[str, Any]:
    p = plan(seed)
    arms: dict[str, Any] = {m: FabricArm(m, seed) for m in
                            ("retraction_only", "delete_and_reshare", "versioned")}
    arms["naive_overwrite"] = NaiveArm(seed)
    for arm in arms.values():
        arm.setup(p)
    counts = {a: {"correct": 0, "stale": 0, "missing": 0, "checks": 0} for a in ARMS}
    value_index = {fid: 0 for fid in p.origin}
    # The oracle knows every value the moment it exists and moves it straight
    # to every holder, ignoring topology -- but it cannot cross a partition
    # (AGENTS.md 8b: the same constraints as the arms, only the knowledge).
    oracle: dict[str, dict[str, int]] = {
        s: {fid: p.values[fid][0] for fid in p.origin if s in holders(p, fid)} for s in STORES}
    for step in range(STEPS):
        offline = p.offline.get(step, set())
        for arm in arms.values():
            arm.offline = set(offline)
        for fid in p.corrections.get(step, []):
            value_index[fid] += 1
            value = p.values[fid][value_index[fid]]
            for name, arm in arms.items():
                if name == "naive_overwrite":
                    arm.correct(fid, value, p.origin[fid])
                else:
                    arm.correct(fid, value)
        for arm in arms.values():
            arm.step()
        for fid in sorted(p.origin):
            latest = p.values[fid][value_index[fid]]
            oracle[p.origin[fid]][fid] = latest
            if p.origin[fid] not in offline:
                for store in holders(p, fid):
                    if store not in offline:
                        oracle[store][fid] = latest
            for store in holders(p, fid):
                results = {name: arm.served(fid, store) for name, arm in arms.items()}
                results["oracle"] = {oracle[store][fid]}
                for name, served in results.items():
                    c = counts[name]
                    c["checks"] += 1
                    if served == {latest}:
                        c["correct"] += 1
                    elif not served:
                        c["missing"] += 1
                    else:
                        c["stale"] += 1
    for arm in arms.values():  # heal everything and drain
        arm.offline = set()
        for _ in range(4):
            arm.step()
    final = {}
    for name, arm in arms.items():
        final[name] = all(arm.served(fid, store) == {p.values[fid][-1]}
                          for fid in p.origin for store in holders(p, fid))
    final["oracle"] = True
    survival = {name: arm.independent_survival() for name, arm in arms.items()
                if hasattr(arm, "independent_survival")}
    truth = {name: arm.status_truth() for name, arm in arms.items()
             if hasattr(arm, "status_truth")}
    dependent = {name: arm.dependent_rechecked() for name, arm in arms.items()
                 if hasattr(arm, "dependent_rechecked")}
    return {"seed": seed, "counts": counts, "final": final, "survival": survival, "truth": truth,
            "dependent": dependent}


def analyse(seeds: list[dict[str, Any]]) -> dict[str, Any]:
    from memeval import Registration

    def rate(arm: str, key: str) -> float:
        num = sum(s["counts"][arm][key] for s in seeds)
        den = sum(s["counts"][arm]["checks"] for s in seeds)
        return round(num / den, 4) if den else float("nan")

    arms = {a: {"correct_state": rate(a, "correct"), "stale": rate(a, "stale"),
                "missing": rate(a, "missing"),
                "final_convergence": sum(s["final"][a] for s in seeds) / len(seeds)}
            for a in ARMS}
    for a in ("retraction_only", "delete_and_reshare", "versioned"):
        kept = [x for s in seeds for x in s["survival"].get(a, [])]
        arms[a]["unnecessary_invalidation"] = round(1 - sum(kept) / len(kept), 4) if kept else None
        truth = [x for s in seeds for x in s["truth"].get(a, [])]
        arms[a]["status_truth"] = round(sum(truth) / len(truth), 4) if truth else None
        dependent = [x for s in seeds for x in s["dependent"].get(a, [])]
        arms[a]["dependent_rechecked"] = (round(sum(dependent) / len(dependent), 4)
                                          if dependent else None)
    baselines = ["retraction_only", "naive_overwrite", "delete_and_reshare"]
    verdict = Registration(hypothesis="S1", metric="correct_state", mechanism="versioned",
                           baselines=baselines, ceiling="oracle", seeds_required=20).evaluate(
        arms, seeds=len(seeds))
    conditions = {
        # AGENTS.md 8b: an arm above the ceiling proves the ceiling wrong.
        "no_arm_beats_the_oracle": all(arms[a]["correct_state"] <= arms["oracle"]["correct_state"]
                                       for a in ARMS),
        "headroom_share": verdict.outcome.value,
        "versioned_converges_every_seed": arms["versioned"]["final_convergence"] == 1.0,
        "invalidation_no_worse_than_retraction_only":
            (arms["versioned"]["unnecessary_invalidation"] or 0)
            <= (arms["retraction_only"]["unnecessary_invalidation"] or 0),
    }
    supported = (conditions["headroom_share"] == "SUPPORTED"
                 and conditions["versioned_converges_every_seed"]
                 and conditions["invalidation_no_worse_than_retraction_only"])
    return {"arms": arms, "verdict": verdict.to_json(), "conditions": conditions,
            "S1": "SUPPORTED" if supported else verdict.outcome.value
            if verdict.outcome.value != "SUPPORTED" else "NOT SUPPORTED"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    seeds = [run_seed(s) for s in range(args.seeds)]
    import subprocess
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    result = {"experiment": "s1-correction-sim", "commit": commit, "seeds": args.seeds,
              "wall_s": round(time.perf_counter() - started, 1), **analyse(seeds), "per_seed": seeds}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "per_seed"}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
