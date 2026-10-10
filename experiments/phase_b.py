"""Phase B: what should cross a federation boundary?

Pre-registration: research/prereg/phase-b-federated-agents.md.

Four agents with partially overlapping territories, each holding only what it
learned at its own sites, so every agent holds lessons that are true for it and
false for a neighbour. `west` has a single site deliberately: it is the agent
most exposed to a confident import from a territory it cannot check, which is
the case a federation gets wrong.

Eight cells: six sharing policies, with retraction propagation crossed into the
two that share broadly. PB2 counts only if propagation helps under both — a
mechanism that works only when everything is shared is not the one being
claimed.

Two design decisions this file makes, which the registration left open:

**Every arm runs the same exposure policy** (epsilon-greedy, 0.2). `share_valued`
needs contrastive value evidence to exist at all, and a deterministic policy
never generates the overlap an unbiased estimate requires — so a store under
`top_k` would simply never promote anything and that arm would silently become
`isolated`. Holding exposure constant across every arm pays the exploration cost
everywhere rather than only where it is needed, which Phase A measured at a few
points of accuracy, but it keeps the arms differing in exactly one thing.

**Retraction is a scheduled environment event**, not an agent's inference. At the
halfway episode every poisoned lesson is retracted at its origin, as a
manufacturer's bulletin would do it. Deriving the retraction from "this memory
was in context when something failed" would import the policy Phase A killed
into the middle of PB2 and make its result unreadable.

    python -m experiments.phase_b --pilot
    python -m experiments.phase_b
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

from memory_fabric import EpsilonGreedyPolicy, LifecycleState, MemoryFabric
from memory_fabric.adapters.context import build_context
from memory_fabric.adapters.ollama import OllamaClient, OllamaEmbedder, OllamaError
from memory_fabric.cli import configure_output
from memory_fabric.federation import imported_from, offer, propagate_retraction
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)

from . import depotworld as W
from . import stats
from .phase_a import AGENT_MODEL, Lesson, _ask, write_corpus

TERRITORIES = {
    "north": ("cold_store", "urban"),
    "south": ("coastal", "urban"),
    "east": ("cold_store", "coastal"),
    "west": ("urban",),
}
AGENTS = tuple(TERRITORIES)

ARMS = (
    "isolated",
    "share_all",
    "share_all_propagate",
    "share_overlap",
    "share_overlap_propagate",
    "share_valued",
    "share_valued_overlap",
    "oracle_share",
)
PROPAGATING = ("share_all_propagate", "share_overlap_propagate")
BASE_POLICY = {
    "share_all_propagate": "share_all",
    "share_overlap_propagate": "share_overlap",
}


def federating_firewall() -> Firewall:
    """Without the value rule: the sharing *policies* are the independent
    variable here, and leaving the firewall's own value gate in would apply a
    second, uncontrolled filter on top of every one of them."""
    return Firewall(
        rules=(
            rule_restricted_stays_private,
            rule_must_be_active,
            rule_capabilities_must_be_granted,
        )
    )


@dataclass
class BDecision:
    arm: str
    seed: int
    round_index: int
    agent: str
    fault: str
    site: str
    correct: str
    is_exception: bool
    answered: str | None
    success: bool
    shown: int = 0
    shown_imported: int = 0
    shown_wrong: int = 0
    shown_right: int = 0
    negative_transfer: bool = False
    tokens: float = 0.0
    held_retracted: bool = False
    """True when a memory retracted at its origin was still active here and in
    context. This is `propagation_lag` measured per episode rather than as a
    single number, so an arm that never stops acting on a retracted memory is
    visible rather than averaged away."""


@dataclass
class BArm:
    arm: str
    decisions: list[BDecision] = field(default_factory=list)
    imports: int = 0
    imports_wrong: int = 0
    propagated: int = 0

    def success(self) -> list[float]:
        return [1.0 if d.success else 0.0 for d in self.decisions]

    def negative_transfer(self) -> list[float]:
        return [1.0 if d.negative_transfer else 0.0 for d in self.decisions]

    def held_retracted(self) -> list[float]:
        return [1.0 if d.held_retracted else 0.0 for d in self.decisions]

    def per_agent(self) -> dict[str, float]:
        out: dict[str, list[float]] = {a: [] for a in AGENTS}
        for d in self.decisions:
            out[d.agent].append(1.0 if d.success else 0.0)
        return {a: stats.mean(v) for a, v in out.items() if v}

    def spread(self) -> float:
        per = self.per_agent()
        return (max(per.values()) - min(per.values())) if per else 0.0


def agent_corpus(
    truth: W.Truth,
    rng: random.Random,
    client: OllamaClient,
    model: str,
    verbose: bool,
) -> dict[str, list[Lesson]]:
    """Each agent learns only its own sites, so negative transfer is available
    by construction rather than injected."""
    out: dict[str, list[Lesson]] = {}
    for agent, sites in TERRITORIES.items():
        episodes = [
            e
            for e in W.learning_episodes(truth, rng)
            if e.site in sites
        ]
        out[agent] = write_corpus(episodes, client, model, verbose=verbose)
    return out


def agent_episodes(
    truth: W.Truth, rng: random.Random, count: int
) -> dict[str, list[W.EvalEpisode]]:
    out: dict[str, list[W.EvalEpisode]] = {}
    for agent, sites in TERRITORIES.items():
        pool = [
            W.EvalEpisode(f, s, truth.action(f, s), truth.is_exception(f, s))
            for f in W.FAULTS
            for s in sites
        ]
        exceptions = [e for e in pool if e.is_exception]
        bases = [e for e in pool if not e.is_exception]
        half = count // 2
        chosen = [rng.choice(exceptions or bases) for _ in range(half)]
        chosen += [rng.choice(bases or exceptions) for _ in range(count - half)]
        rng.shuffle(chosen)
        out[agent] = chosen
    return out


def _should_share(
    arm: str,
    lesson: Lesson,
    recipient: str,
    value_ok: bool,
    correct_for_recipient: bool,
) -> bool:
    policy = BASE_POLICY.get(arm, arm)
    if policy == "isolated":
        return False
    if policy == "oracle_share":
        return correct_for_recipient
    overlap = lesson.site in TERRITORIES[recipient]
    if policy == "share_all":
        return True
    if policy == "share_overlap":
        return overlap
    if policy == "share_valued":
        return value_ok
    if policy == "share_valued_overlap":
        return value_ok and overlap
    raise KeyError(arm)


def run_arm(
    arm: str,
    seed: int,
    corpora: dict[str, list[Lesson]],
    episodes: dict[str, list[W.EvalEpisode]],
    client: OllamaClient,
    embedder: OllamaEmbedder,
    model: str,
    k: int = 3,
    verbose: bool = True,
) -> BArm:
    rounds = len(next(iter(episodes.values())))
    retract_at = rounds // 2
    stores = {
        agent: MemoryFabric(
            ":memory:", seed=seed, embedder=embedder, estimator="amortized",
            exposure_policy=EpsilonGreedyPolicy(epsilon=0.2, rank_by="value"),
            firewall=federating_firewall(),
        )
        for agent in AGENTS
    }
    result = BArm(arm)
    try:
        # Native memories, written and validated at their own agent.
        native: dict[str, dict[str, Lesson]] = {a: {} for a in AGENTS}
        for agent, lessons in corpora.items():
            for lesson in lessons:
                mid = stores[agent].remember(
                    agent, lesson.content,
                    context={"site": lesson.site, "fault": lesson.fault},
                )
                stores[agent].validate(mid, actor="supervisor")
                native[agent][mid] = lesson
        shared_already: set[tuple[str, str, str]] = set()
        imported: dict[str, dict[str, Lesson]] = {a: {} for a in AGENTS}
        retracted_origins: set[tuple[str, str]] = set()

        for round_index in range(rounds):
            # --- share, before the round's work ---------------------------
            for sender in AGENTS:
                for mid, lesson in native[sender].items():
                    if stores[sender].get(mid).lifecycle_state != LifecycleState.ACTIVE:
                        continue
                    value = stores[sender].value(mid)
                    value_ok = bool(
                        value.contrastive and value.n_eff > 0 and value.shows_benefit
                    )
                    for recipient in AGENTS:
                        if recipient == sender:
                            continue
                        key = (sender, mid, recipient)
                        if key in shared_already:
                            continue
                        correct_here = all(
                            lesson.asserted
                            == next(
                                (
                                    e.correct
                                    for e in episodes[recipient]
                                    if e.fault == lesson.fault and e.site == site
                                ),
                                lesson.asserted,
                            )
                            for site in (lesson.site,)
                            if site in TERRITORIES[recipient]
                        ) and lesson.site in TERRITORIES[recipient] and not lesson.poisoned
                        if not _should_share(
                            arm, lesson, recipient, value_ok, correct_here
                        ):
                            continue
                        got = offer(
                            stores[sender], mid, stores[recipient],
                            recipient_agent=recipient,
                        )
                        shared_already.add(key)
                        if got.accepted and got.imported_memory_id:
                            # An import arrives as a candidate. The recipient
                            # activating it is the recipient's decision, which
                            # is the guarantee federation.py exists to make.
                            stores[recipient].validate(
                                got.imported_memory_id, actor=recipient
                            )
                            imported[recipient][got.imported_memory_id] = lesson
                            result.imports += 1
                            if lesson.poisoned or lesson.site not in TERRITORIES[recipient]:
                                result.imports_wrong += 1

            # --- the scheduled retraction --------------------------------
            if round_index == retract_at:
                for sender in AGENTS:
                    for mid, lesson in native[sender].items():
                        if not lesson.poisoned:
                            continue
                        if stores[sender].get(mid).lifecycle_state == LifecycleState.QUARANTINED:
                            continue
                        stores[sender].quarantine(
                            mid, reason="manufacturer bulletin: diagnosis was wrong",
                            actor="environment",
                        )
                        retracted_origins.add((sender, mid))
                        if arm in PROPAGATING:
                            done = propagate_retraction(
                                stores[sender], mid,
                                [stores[a] for a in AGENTS if a != sender],
                                actor="federation",
                            )
                            result.propagated += sum(1 for d in done if d.acted)

            # --- each agent works one episode ----------------------------
            for agent in AGENTS:
                episode = episodes[agent][round_index]
                store = stores[agent]
                with store.session(
                    agent, f"{arm}-{seed}-{round_index}-{agent}",
                    {"site": episode.site, "fault": episode.fault},
                ) as session:
                    hits = session.recall(
                        W.recall_query(episode), k=k, include_contested=True
                    )
                    exposed = list(hits.exposed)
                    memory_text = (
                        build_context(store, exposed, W.recall_query(episode)).render()
                        if exposed else ""
                    )
                    text, tokens, _ = _ask(client, model, memory_text, episode)
                    answered = W.parse_action(text)
                    success = answered == episode.correct

                    shown_lessons = []
                    shown_imported = 0
                    held_retracted = False
                    for memory in exposed:
                        lesson = native[agent].get(memory.id) or imported[agent].get(memory.id)
                        if lesson is None:
                            continue
                        shown_lessons.append((memory.id, lesson))
                        origin = imported_from(store, memory.id)
                        if origin is not None:
                            shown_imported += 1
                            if lesson.poisoned and round_index > retract_at:
                                held_retracted = True

                    session.record_outcome(
                        1.0 if success else 0.0, verifier_id="depotworld"
                    )

                decision = BDecision(
                    arm=arm, seed=seed, round_index=round_index, agent=agent,
                    fault=episode.fault, site=episode.site, correct=episode.correct,
                    is_exception=episode.is_exception, answered=answered,
                    success=success, shown=len(shown_lessons),
                    shown_imported=shown_imported,
                    shown_wrong=sum(
                        1 for _, l in shown_lessons if l.wrong_for(episode)
                    ),
                    shown_right=sum(
                        1 for _, l in shown_lessons if l.right_for(episode)
                    ),
                    # Harm attributable to federation specifically: the agent
                    # acted on something another agent sent it.
                    negative_transfer=bool(
                        answered
                        and not success
                        and any(
                            l.asserted == answered
                            for mid, l in shown_lessons
                            if imported_from(store, mid) is not None
                        )
                    ),
                    tokens=tokens,
                    held_retracted=held_retracted,
                )
                result.decisions.append(decision)
                if verbose:
                    print(f"    {arm:<24} r{round_index:<2} {agent:<6} {episode.fault} "
                          f"{episode.site:<11}{'EXC' if episode.is_exception else '   '}"
                          f" -> {str(answered):<18}"
                          f" {'ok ' if success else 'miss'}"
                          f" [{decision.shown_right}+/{decision.shown_wrong}-"
                          f" of {decision.shown}, {shown_imported} imported]",
                          flush=True)
    finally:
        for store in stores.values():
            store.close()
    return result


def run_seed(
    seed: int,
    client: OllamaClient,
    embedder: OllamaEmbedder,
    model: str,
    arms: Sequence[str],
    rounds: int,
    verbose: bool,
) -> dict[str, BArm]:
    rng = random.Random(seed)
    truth = W.build_truth(rng)
    print(f"  seed {seed}: writing each agent's own corpus...", flush=True)
    corpora = agent_corpus(truth, rng, client, model, verbose=verbose)
    for agent, lessons in corpora.items():
        print(f"    {agent:<6} {len(lessons)} lessons "
              f"({sum(1 for l in lessons if l.poisoned)} poisoned), "
              f"sites {TERRITORIES[agent]}", flush=True)
    episodes = agent_episodes(truth, rng, rounds)
    texts = [l.content for ls in corpora.values() for l in ls]
    embedder.warm(texts)
    embedder.warm([W.recall_query(e) for es in episodes.values() for e in es])

    out: dict[str, BArm] = {}
    for arm in arms:
        started = time.perf_counter()
        out[arm] = run_arm(
            arm, seed, corpora, episodes, client, embedder, model, verbose=verbose
        )
        cell = out[arm]
        print(f"  seed {seed} {arm:<24} success {stats.mean(cell.success()):>5.0%}  "
              f"neg-transfer {stats.mean(cell.negative_transfer()):>5.0%}  "
              f"imports {cell.imports:>3} ({cell.imports_wrong} wrong)  "
              f"propagated {cell.propagated:>3}  "
              f"({time.perf_counter()-started:.0f}s)", flush=True)
    return out


def report(pooled: dict[str, BArm], arms: Sequence[str]) -> dict[str, object]:
    print(f"\n{'arm':<24} {'success':>18} {'neg transfer':>18} {'spread':>7} "
          f"{'worst':>7} {'imports':>8} {'wrong':>6} {'held retr':>10}")
    print("-" * 108)
    summary: dict[str, object] = {}
    for arm in arms:
        cell = pooled[arm]
        per = cell.per_agent()
        worst = min(per.values()) if per else 0.0
        print(f"{arm:<24} {stats.fmt_ci(cell.success()):>18} "
              f"{stats.fmt_ci(cell.negative_transfer()):>18} "
              f"{cell.spread():>6.0%} {worst:>6.0%} "
              f"{cell.imports:>8} {cell.imports_wrong:>6} "
              f"{stats.mean(cell.held_retracted()):>9.0%}")
        summary[arm] = {
            "success": stats.mean(cell.success()),
            "negative_transfer": stats.mean(cell.negative_transfer()),
            "spread": cell.spread(),
            "worst_agent": worst,
            "per_agent": per,
            "imports": cell.imports,
            "imports_wrong": cell.imports_wrong,
            "propagated": cell.propagated,
            "held_retracted": stats.mean(cell.held_retracted()),
            "n": len(cell.decisions),
        }
    return summary


def verdict(pooled: dict[str, BArm]) -> None:
    """Against §6 of the registration, and nothing else."""
    needed = ("isolated", "share_all", "share_overlap", "share_valued",
              "share_valued_overlap", "oracle_share",
              "share_all_propagate", "share_overlap_propagate")
    if not all(a in pooled for a in needed):
        print("\n(partial run: verdict needs every cell)")
        return

    simple = max(("isolated", "share_all"), key=lambda a: stats.mean(pooled[a].success()))
    base = pooled[simple]
    ceiling = pooled["oracle_share"]
    floor_v = stats.mean(base.success())
    ceil_v = stats.mean(ceiling.success())
    headroom = ceil_v - floor_v

    print("\n=== Against the pre-registration ===")
    print(f"  best simple policy: {simple} at {floor_v:.1%}")
    print(f"  ceiling (oracle_share): {ceil_v:.1%}")
    print(f"  headroom: {headroom:+.1%}")

    selective = ("share_overlap", "share_valued", "share_valued_overlap")
    best = max(selective, key=lambda a: stats.mean(pooled[a].success()))
    best_v = stats.mean(pooled[best].success())
    diffs = [t - b for t, b in zip(pooled[best].success(), base.success())]
    low, high = stats.bootstrap_ci(diffs)
    share = (best_v - floor_v) / headroom if headroom > 0 else float("nan")
    base_worst = min(base.per_agent().values())
    best_worst = min(pooled[best].per_agent().values())
    print(f"\n  PB1 best selective policy: {best} at {best_v:.1%}")
    print(f"      headroom captured {share:.0%} (needs >= 40%), "
          f"paired diff {stats.mean(diffs):+.3f} [{low:+.3f}, {high:+.3f}]")
    print(f"      worst agent: {best_worst:.1%} against {base_worst:.1%} "
          f"(must not fall)")
    pb1 = headroom > 0 and share >= 0.40 and low > 0 and best_worst >= base_worst

    print("\n  PB2 retraction propagation, required under BOTH policies:")
    pb2_each = []
    for prop, plain in (("share_all_propagate", "share_all"),
                        ("share_overlap_propagate", "share_overlap")):
        held_plain = stats.mean(pooled[plain].held_retracted())
        held_prop = stats.mean(pooled[prop].held_retracted())
        sdiffs = [p - q for p, q in zip(pooled[prop].success(), pooled[plain].success())]
        slow, shigh = stats.bootstrap_ci(sdiffs)
        ceil_held = stats.mean(ceiling.held_retracted())
        hroom = held_plain - ceil_held
        cut = held_plain - held_prop
        cshare = cut / hroom if hroom > 0 else float("nan")
        ok = hroom > 0 and cshare >= 0.50 and held_prop < held_plain
        pb2_each.append(ok)
        print(f"      {plain:<16} still acting on a retracted memory "
              f"{held_plain:.1%} -> {held_prop:.1%} "
              f"({cshare:.0%} of headroom, needs >= 50%)")
        print(f"      {'':<16} success {stats.mean(sdiffs):+.3f} "
              f"[{slow:+.3f}, {shigh:+.3f}], propagated "
              f"{pooled[prop].propagated}")
    pb2 = all(pb2_each)

    per_sender = pooled["share_all"].imports / max(1, len(AGENTS) * (len(AGENTS) - 1))
    print(f"\n  PB3 reputation: not implemented this run. "
          f"{per_sender:.0f} imports per sender pair under share_all; "
          f"the registration declares PB3 inconclusive-by-design below 10.")

    print(f"\n  PB1: {'SUPPORTED' if pb1 else 'KILLED'}")
    print(f"  PB2: {'SUPPORTED' if pb2 else 'KILLED'}")
    print(f"  PB3: INCONCLUSIVE (not run)")
    if not pb1:
        print("\n  Phase C stays gated: PB1 is the gate, and it did not pass.")


def main(argv: Sequence[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="Phase B: federated agents, live")
    parser.add_argument("--pilot", action="store_true", help="one seed, 6 rounds")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=12,
                        help="episodes per agent (amended from 24; see prereg)")
    parser.add_argument("--model", default=AGENT_MODEL)
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--out", help="write the per-decision record as JSON")
    args = parser.parse_args(argv)

    arms = [a for a in args.arms.split(",") if a]
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        print(f"unknown arms: {unknown}", file=sys.stderr)
        return 2

    client = OllamaClient()
    try:
        available = client.available()
    except OllamaError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2
    model = OllamaClient.resolve(args.model, available)
    if not model:
        print(f"{args.model} is not installed", file=sys.stderr)
        return 2

    seeds = [0] if args.pilot else list(range(args.seeds))
    rounds = 6 if args.pilot else args.rounds

    print("Phase B: what should cross a federation boundary?")
    print(f"model={model}  seeds={seeds}  rounds={rounds}  arms={arms}")
    print(f"territories={TERRITORIES}")
    print("prereg: research/prereg/phase-b-federated-agents.md\n")

    embedder = OllamaEmbedder(client)
    pooled: dict[str, BArm] = {arm: BArm(arm) for arm in arms}
    started = time.perf_counter()
    for seed in seeds:
        per_seed = run_seed(
            seed, client, embedder, model, arms, rounds, verbose=not args.quiet
        )
        for arm, cell in per_seed.items():
            pooled[arm].decisions.extend(cell.decisions)
            pooled[arm].imports += cell.imports
            pooled[arm].imports_wrong += cell.imports_wrong
            pooled[arm].propagated += cell.propagated

    summary = report(pooled, arms)
    verdict(pooled)

    total = client.usage()
    print(f"\n{total['calls']:.0f} model calls, {total['tokens']:.0f} tokens, "
          f"{time.perf_counter()-started:.0f}s wall")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "model": model, "seeds": seeds, "rounds": rounds,
                    "territories": {a: list(s) for a, s in TERRITORIES.items()},
                    "summary": summary, "usage": total,
                    "decisions": [
                        asdict(d) for cell in pooled.values() for d in cell.decisions
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
