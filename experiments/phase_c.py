"""Phase C: can a population learn what should propagate?

Pre-registration: research/prereg/phase-c-memory-ecology.md, with a dated
amendment moving the PB1 gate from "do not build" to "do not call it a
registered test".

The founding document said memories should propagate through a network like
traits through an ecology — selected for, inherited, going extinct. That is an
analogy. The testable version is whether a population of agents, each adjusting
*who it shares which memories with* from its own observed outcomes, converges on
a sharing structure that beats every fixed policy.

Eight agents, overlapping territories, six arms:

    isolated             nothing crosses
    share_all            everything to everyone
    best_fixed           whichever policy won Phase B, carried over
    learned              epsilon-greedy over recipients, driven by their outcomes
    learned_no_feedback  the same learner, fed only the sender's own outcomes
    oracle_share         exactly what is correct for each recipient

**`learned_no_feedback` is the arm that decides whether the design is worth
its cost.** `learned` requires recipients to report verified outcomes back to
senders — a channel a real federation may not have. If the two tie, the channel
is inert and the expensive part of the design earned nothing, which is the same
shape of finding as H2.

**The ecology claim is judged separately from PC.** A population can improve by
learning sharing rules while propagation stays uncorrelated with memory value;
that would mean the selective-pressure story is wrong even though the learning
story works. Keeping them apart is the difference between testing the mechanism
and decorating a result with its metaphor.

    python -m experiments.phase_c --pilot
    python -m experiments.phase_c
"""

from __future__ import annotations

import argparse
import json
import math
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
from memory_fabric.federation import imported_from, offer

from . import depotworld as W
from . import stats
from .phase_a import AGENT_MODEL, Lesson, _ask, _round, write_corpus
from .phase_b import federating_firewall

# Overlap varies continuously rather than falling into Phase B's four clean
# cases, because the learner's job is to discover the structure, and a structure
# with only a few distinct shapes can be guessed.
TERRITORIES = {
    "a1": ("cold_store", "urban"),
    "a2": ("coastal", "urban"),
    "a3": ("cold_store", "coastal"),
    "a4": ("urban",),
    "a5": ("cold_store",),
    "a6": ("coastal",),
    "a7": ("cold_store", "coastal", "urban"),
    "a8": ("urban", "coastal"),
}
AGENTS = tuple(TERRITORIES)

ARMS = (
    "isolated",
    "share_all",
    "best_fixed",
    "learned",
    "learned_no_feedback",
    "oracle_share",
)
LEARNING = ("learned", "learned_no_feedback")


@dataclass
class CDecision:
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
    shown_right: int = 0
    shown_wrong: int = 0
    tokens: float = 0.0


@dataclass
class CArm:
    arm: str
    decisions: list[CDecision] = field(default_factory=list)
    imports: int = 0
    imports_wrong: int = 0
    # memory key -> how many distinct stores it reached. The ecology claim is a
    # correlation between this and the memory's measured value.
    spread: dict[str, int] = field(default_factory=dict)
    value_of: dict[str, float] = field(default_factory=dict)
    graph_changes: list[int] = field(default_factory=list)
    learned_edges: dict[str, set[str]] = field(default_factory=dict)

    def success(self) -> list[float]:
        return [1.0 if d.success else 0.0 for d in self.decisions]

    def per_agent(self) -> dict[str, float]:
        out: dict[str, list[float]] = {a: [] for a in AGENTS}
        for d in self.decisions:
            out[d.agent].append(1.0 if d.success else 0.0)
        return {a: stats.mean(v) for a, v in out.items() if v}

    def worst_agent(self) -> float:
        per = self.per_agent()
        return min(per.values()) if per else 0.0

    def agent_spread(self) -> float:
        per = self.per_agent()
        return (max(per.values()) - min(per.values())) if per else 0.0


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Rank correlation, written out because the core has no dependencies.

    Ties get average ranks; without that, a population where most memories
    reached exactly one store would have its correlation decided by input order.

    Returns NaN when it cannot be computed, which happens for a real reason
    here: under `share_all` every memory reaches every store, so spread has no
    variance and there is nothing for value to correlate *with*. That is not a
    weak correlation, it is an undefined one, and `describe_rho` keeps the two
    from being read as the same thing.
    """
    if len(xs) < 3:
        return float("nan")

    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = average
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return num / (dx * dy) if dx > 0 and dy > 0 else float("nan")


class RecipientBandit:
    """What each sender learns: whether memories it sent to a recipient were
    followed by that recipient succeeding.

    Deliberately the simplest thing that could work. The claim under test is
    that *any* outcome-driven adjustment beats a fixed rule, and a complicated
    learner that wins tells us less than a simple one that does. It is a bandit
    over recipients, which cannot represent "share this kind of memory with that
    agent" — the registration states that limitation rather than leaving it to
    be discovered.
    """

    def __init__(self, rng: random.Random, epsilon: float = 0.25) -> None:
        self.rng = rng
        self.epsilon = epsilon
        self.wins: dict[tuple[str, str], float] = {}
        self.trials: dict[tuple[str, str], float] = {}

    def rate(self, sender: str, recipient: str) -> float:
        key = (sender, recipient)
        n = self.trials.get(key, 0.0)
        if n <= 0.0:
            # Optimistic start: an untried recipient is worth trying, or the
            # population freezes on whoever it happened to try first.
            return 1.0
        return self.wins.get(key, 0.0) / n

    def should_share(self, sender: str, recipient: str) -> bool:
        if self.rng.random() < self.epsilon:
            return self.rng.random() < 0.5
        return self.rate(sender, recipient) >= 0.5

    def record(self, sender: str, recipient: str, success: bool) -> None:
        key = (sender, recipient)
        self.trials[key] = self.trials.get(key, 0.0) + 1.0
        self.wins[key] = self.wins.get(key, 0.0) + (1.0 if success else 0.0)

    def edges(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {a: set() for a in AGENTS}
        for (sender, recipient), n in self.trials.items():
            if n > 0 and self.rate(sender, recipient) >= 0.5:
                out[sender].add(recipient)
        return out


def describe_rho(rho: float, n: int, spread: Sequence[float]) -> str:
    """Say why a correlation is missing, rather than printing NaN.

    "Undefined because every memory went everywhere" and "no relationship found"
    are opposite findings, and a bare NaN reads as the second.
    """
    if n < 3:
        return f"n/a ({n} memories with value evidence)"
    if len(set(spread)) <= 1:
        return "undefined (spread is constant: everything reached every store)"
    if rho != rho:  # NaN
        return "undefined (no variance)"
    return f"{rho:+.3f} (n={n})"


def agent_corpus(
    truth: W.Truth, rng: random.Random, client: OllamaClient, model: str, verbose: bool
) -> dict[str, list[Lesson]]:
    out: dict[str, list[Lesson]] = {}
    for agent, sites in TERRITORIES.items():
        episodes = [e for e in W.learning_episodes(truth, rng) if e.site in sites]
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
        exceptions = [e for e in pool if e.is_exception] or pool
        bases = [e for e in pool if not e.is_exception] or pool
        half = count // 2
        chosen = [rng.choice(exceptions) for _ in range(half)]
        chosen += [rng.choice(bases) for _ in range(count - half)]
        rng.shuffle(chosen)
        out[agent] = chosen
    return out


def overlap_graph() -> dict[str, set[str]]:
    """The true structure the learner is not told about."""
    return {
        a: {b for b in AGENTS if b != a and set(TERRITORIES[a]) & set(TERRITORIES[b])}
        for a in AGENTS
    }


def neighbourhood_match(learned: dict[str, set[str]]) -> float:
    """Jaccard between the learned sharing graph and the territory-overlap graph,
    averaged over senders. Not a threshold — a description of whether the
    population found the structure without being given it."""
    truth = overlap_graph()
    scores: list[float] = []
    for agent in AGENTS:
        a, b = learned.get(agent, set()), truth[agent]
        union = a | b
        scores.append(len(a & b) / len(union) if union else 1.0)
    return stats.mean(scores)


def run_arm(
    arm: str,
    seed: int,
    corpora: dict[str, list[Lesson]],
    episodes: dict[str, list[W.EvalEpisode]],
    client: OllamaClient,
    embedder: OllamaEmbedder,
    model: str,
    best_fixed: str = "share_overlap",
    k: int = 3,
    verbose: bool = True,
) -> CArm:
    rounds = len(next(iter(episodes.values())))
    rng = random.Random(seed * 1000 + 7)
    bandit = RecipientBandit(rng) if arm in LEARNING else None
    stores = {
        agent: MemoryFabric(
            ":memory:", seed=seed, embedder=embedder, estimator="amortized",
            exposure_policy=EpsilonGreedyPolicy(epsilon=0.2, rank_by="value"),
            firewall=federating_firewall(),
        )
        for agent in AGENTS
    }
    result = CArm(arm)
    try:
        native: dict[str, dict[str, Lesson]] = {a: {} for a in AGENTS}
        # A stable key per distinct lesson, so "how many stores did it reach?"
        # is a property of the knowledge rather than of a per-store id.
        key_of: dict[str, str] = {}
        for agent, lessons in corpora.items():
            for lesson in lessons:
                mid = stores[agent].remember(
                    agent, lesson.content,
                    context={"site": lesson.site, "fault": lesson.fault},
                )
                stores[agent].validate(mid, actor="supervisor")
                native[agent][mid] = lesson
                key = f"{agent}:{lesson.fault}:{lesson.site}"
                key_of[mid] = key
                result.spread[key] = 1

        imported: dict[str, dict[str, Lesson]] = {a: {} for a in AGENTS}
        import_key: dict[str, str] = {}
        offered: set[tuple[str, str, str]] = set()
        previous_edges: dict[str, set[str]] | None = None
        # Which senders contributed to each agent's current round, so the
        # recipient's verified outcome can be reported back to them.
        contributed: dict[str, set[str]] = {a: set() for a in AGENTS}

        for round_index in range(rounds):
            for sender in AGENTS:
                for mid, lesson in native[sender].items():
                    if stores[sender].get(mid).lifecycle_state != LifecycleState.ACTIVE:
                        continue
                    for recipient in AGENTS:
                        if recipient == sender:
                            continue
                        # Not named `token`: the project's own secret detector
                        # reads `token = ...` as a credential assignment, and an
                        # allowlist entry would weaken the rule for every file.
                        share_key = (sender, mid, recipient)
                        if share_key in offered:
                            continue
                        overlap = lesson.site in TERRITORIES[recipient]
                        if arm == "isolated":
                            allow = False
                        elif arm == "share_all":
                            allow = True
                        elif arm == "oracle_share":
                            allow = overlap and not lesson.poisoned
                        elif arm == "best_fixed":
                            allow = overlap if best_fixed == "share_overlap" else True
                        else:
                            allow = bandit.should_share(sender, recipient)
                        if not allow:
                            continue
                        got = offer(
                            stores[sender], mid, stores[recipient],
                            recipient_agent=recipient,
                        )
                        offered.add(share_key)
                        if got.accepted and got.imported_memory_id:
                            stores[recipient].validate(
                                got.imported_memory_id, actor=recipient
                            )
                            imported[recipient][got.imported_memory_id] = lesson
                            import_key[got.imported_memory_id] = key_of[mid]
                            result.imports += 1
                            result.spread[key_of[mid]] = (
                                result.spread.get(key_of[mid], 0) + 1
                            )
                            if lesson.poisoned or not overlap:
                                result.imports_wrong += 1

            if bandit is not None:
                edges = bandit.edges()
                if previous_edges is not None:
                    changed = sum(
                        len(edges[a] ^ previous_edges.get(a, set())) for a in AGENTS
                    )
                    result.graph_changes.append(changed)
                previous_edges = {a: set(v) for a, v in edges.items()}

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

                    shown: list[Lesson] = []
                    shown_imported = 0
                    senders: set[str] = set()
                    for memory in exposed:
                        lesson = native[agent].get(memory.id) or imported[agent].get(memory.id)
                        if lesson is None:
                            continue
                        shown.append(lesson)
                        if imported_from(store, memory.id) is not None:
                            shown_imported += 1
                            key = import_key.get(memory.id, "")
                            if key:
                                senders.add(key.split(":", 1)[0])
                    contributed[agent] = senders
                    session.record_outcome(
                        1.0 if success else 0.0, verifier_id="depotworld"
                    )

                if bandit is not None:
                    if arm == "learned":
                        # The outcome channel: the recipient's verified result
                        # goes back to whoever sent what it used. This is the
                        # cost `learned_no_feedback` exists to price.
                        for sender in senders:
                            bandit.record(sender, agent, success)
                    else:
                        # No channel: a sender can only see its own outcomes, so
                        # it credits every recipient with its own result.
                        for recipient in AGENTS:
                            if recipient != agent:
                                bandit.record(agent, recipient, success)

                result.decisions.append(
                    CDecision(
                        arm=arm, seed=seed, round_index=round_index, agent=agent,
                        fault=episode.fault, site=episode.site,
                        correct=episode.correct, is_exception=episode.is_exception,
                        answered=answered, success=success, shown=len(shown),
                        shown_imported=shown_imported,
                        shown_right=sum(1 for l in shown if l.right_for(episode)),
                        shown_wrong=sum(1 for l in shown if l.wrong_for(episode)),
                        tokens=tokens,
                    )
                )
                if verbose:
                    print(f"    {arm:<20} r{round_index:<2} {agent:<3} {episode.fault} "
                          f"{episode.site:<11} -> {str(answered):<18} "
                          f"{'ok ' if success else 'miss'} "
                          f"[{shown_imported} imported of {len(shown)}]", flush=True)

        # Value of each distinct lesson, measured at its origin store, for the
        # ecology correlation. Taken from the sender because that is where the
        # memory was actually exercised.
        for agent in AGENTS:
            for mid, _lesson in native[agent].items():
                value = stores[agent].value(mid)
                if value.n_eff > 0.0:
                    result.value_of[key_of[mid]] = value.mean
        if bandit is not None:
            result.learned_edges = {a: sorted(v) for a, v in bandit.edges().items()}
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
    best_fixed: str,
    verbose: bool,
) -> dict[str, CArm]:
    rng = random.Random(seed)
    truth = W.build_truth(rng)
    print(f"  seed {seed}: writing {len(AGENTS)} agent corpora...", flush=True)
    corpora = agent_corpus(truth, rng, client, model, verbose)
    for agent, lessons in corpora.items():
        print(f"    {agent:<3} {len(lessons):>2} lessons "
              f"({sum(1 for l in lessons if l.poisoned)} poisoned) {TERRITORIES[agent]}",
              flush=True)
    episodes = agent_episodes(truth, rng, rounds)
    embedder.warm([l.content for ls in corpora.values() for l in ls])
    embedder.warm([W.recall_query(e) for es in episodes.values() for e in es])

    out: dict[str, CArm] = {}
    for arm in arms:
        started = time.perf_counter()
        out[arm] = run_arm(
            arm, seed, corpora, episodes, client, embedder, model,
            best_fixed=best_fixed, verbose=verbose,
        )
        cell = out[arm]
        print(f"  seed {seed} {arm:<20} success {stats.mean(cell.success()):>5.0%}  "
              f"worst {cell.worst_agent():>5.0%}  imports {cell.imports:>4} "
              f"({cell.imports_wrong} wrong)  ({time.perf_counter()-started:.0f}s)",
              flush=True)
    return out


def report(pooled: dict[str, CArm], arms: Sequence[str]) -> dict[str, object]:
    print(f"\n{'arm':<20} {'success':>18} {'worst':>7} {'spread':>7} "
          f"{'imports':>8} {'wrong':>6} {'val~spread':>11} {'graph match':>12}")
    print("-" * 100)
    summary: dict[str, object] = {}
    for arm in arms:
        cell = pooled[arm]
        shared_keys = [k for k in cell.value_of if k in cell.spread]
        rho = spearman(
            [cell.value_of[k] for k in shared_keys],
            [float(cell.spread[k]) for k in shared_keys],
        )
        match = (
            neighbourhood_match({a: set(v) for a, v in cell.learned_edges.items()})
            if cell.learned_edges else float("nan")
        )
        spread_values = [float(cell.spread[k]) for k in shared_keys]
        print(f"{arm:<20} {stats.fmt_ci(cell.success()):>18} "
              f"{cell.worst_agent():>6.0%} {cell.agent_spread():>6.0%} "
              f"{cell.imports:>8} {cell.imports_wrong:>6} "
              f"{describe_rho(rho, len(shared_keys), spread_values):>30} "
              f"{match:>8.3f}")
        summary[arm] = {
            "success": stats.mean(cell.success()),
            "worst_agent": cell.worst_agent(),
            "spread": cell.agent_spread(),
            "per_agent": cell.per_agent(),
            "imports": cell.imports,
            "imports_wrong": cell.imports_wrong,
            "value_spread_rho": rho,
            "neighbourhood_match": match,
            "graph_changes": cell.graph_changes,
            "learned_edges": cell.learned_edges,
            "n": len(cell.decisions),
        }
    return summary


def verdict(pooled: dict[str, CArm], registered: bool) -> None:
    """Against §5, when the PB1 gate allows it to be called a test."""
    if not all(a in pooled for a in ARMS):
        print("\n(partial run: verdict needs every arm)")
        return

    base = pooled["best_fixed"]
    ceiling = pooled["oracle_share"]
    learned = pooled["learned"]
    blind = pooled["learned_no_feedback"]

    floor_v = stats.mean(base.success())
    ceil_v = stats.mean(ceiling.success())
    headroom = ceil_v - floor_v
    gain = stats.mean(learned.success()) - floor_v
    share = gain / headroom if headroom > 0 else float("nan")
    diffs = [l - b for l, b in zip(learned.success(), base.success())]
    low, high = stats.bootstrap_ci(diffs)

    print("\n=== Against the pre-registration ===")
    stats.report_ceiling(
        {arm: stats.mean(cell.success()) for arm, cell in pooled.items()},
        "oracle_share",
    )
    print(f"  best fixed policy:      {floor_v:.1%}")
    print(f"  ceiling (oracle_share): {ceil_v:.1%}")
    print(f"  headroom:               {headroom:+.1%}")
    print(f"\n  PC learned captures {share:.0%} of headroom (needs >= 30%), "
          f"paired diff {stats.mean(diffs):+.3f} [{low:+.3f}, {high:+.3f}]")
    print(f"     worst agent {learned.worst_agent():.1%} against "
          f"{base.worst_agent():.1%} (must not fall)")
    pc = (
        headroom > 0
        and share >= 0.30
        and low > 0
        and learned.worst_agent() >= base.worst_agent()
    )

    bdiffs = [l - n for l, n in zip(learned.success(), blind.success())]
    blow, bhigh = stats.bootstrap_ci(bdiffs)
    print(f"\n  The outcome channel: learned vs learned_no_feedback "
          f"{stats.mean(bdiffs):+.3f} [{blow:+.3f}, {bhigh:+.3f}]")
    if blow <= 0 <= bhigh:
        print("     The channel is inert. `learned` requires recipients to report")
        print("     verified outcomes to senders, and it bought nothing measurable.")

    shared_keys = [k for k in learned.value_of if k in learned.spread]
    rho = spearman(
        [learned.value_of[k] for k in shared_keys],
        [float(learned.spread[k]) for k in shared_keys],
    )
    print(f"\n  Ecology claim, judged separately: value~spread rho = {rho:.3f} "
          f"on {len(shared_keys)} memories (needs > 0.3)")
    if not (rho > 0.3):
        print("     Propagation is not tracking measured value: this is drift, not")
        print("     selection. A population can still improve by learning sharing")
        print("     rules, which is a different claim and judged above.")

    print(f"\n  learned sharing graph vs true overlap: "
          f"{neighbourhood_match({a: set(v) for a, v in learned.learned_edges.items()}):.3f}")

    if registered:
        print(f"\n  PC: {'SUPPORTED' if pc else 'KILLED'}")
    else:
        print("\n  PC: NOT REPORTED — exploratory run.")
        print("  Phase B's PB1 was not supported, so the gate in the registration")
        print("  holds: a threshold applied to a surface already measured to be")
        print("  flat is not a test. The numbers above describe; they do not judge.")


def main(argv: Sequence[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="Phase C: a population learning what to share")
    parser.add_argument("--pilot", action="store_true", help="one seed, 4 rounds")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--model", default=AGENT_MODEL)
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--best-fixed", default="share_overlap",
                        help="the policy that won Phase B; resolved from its result")
    parser.add_argument(
        "--registered", action="store_true",
        help="PB1 was supported, so report a verdict against the thresholds",
    )
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
    rounds = 4 if args.pilot else args.rounds

    print("Phase C: can a population learn what should propagate?")
    print(f"model={model}  seeds={seeds}  rounds={rounds}  agents={len(AGENTS)}")
    print(f"best_fixed={args.best_fixed}  "
          f"{'REGISTERED' if args.registered else 'EXPLORATORY (PB1 gate not passed)'}")
    print("prereg: research/prereg/phase-c-memory-ecology.md\n")

    embedder = OllamaEmbedder(client)
    pooled: dict[str, CArm] = {arm: CArm(arm) for arm in arms}
    started = time.perf_counter()
    for seed in seeds:
        per_seed = run_seed(
            seed, client, embedder, model, arms, rounds, args.best_fixed,
            verbose=not args.quiet,
        )
        for arm, cell in per_seed.items():
            target = pooled[arm]
            target.decisions.extend(cell.decisions)
            target.imports += cell.imports
            target.imports_wrong += cell.imports_wrong
            target.graph_changes.extend(cell.graph_changes)
            for key, count in cell.spread.items():
                target.spread[f"{seed}:{key}"] = count
            for key, value in cell.value_of.items():
                target.value_of[f"{seed}:{key}"] = value
            if cell.learned_edges:
                target.learned_edges = cell.learned_edges

    summary = report(pooled, arms)
    verdict(pooled, registered=args.registered)

    total = client.usage()
    print(f"\n{total['calls']:.0f} model calls, {total['tokens']:.0f} tokens, "
          f"{time.perf_counter()-started:.0f}s wall")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                _round({
                    "model": model, "seeds": seeds, "rounds": rounds,
                    "registered": args.registered, "best_fixed": args.best_fixed,
                    "territories": {a: list(s) for a, s in TERRITORIES.items()},
                    "summary": summary, "usage": total,
                    "decisions": [
                        asdict(d) for cell in pooled.values() for d in cell.decisions
                    ],
                }),
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
