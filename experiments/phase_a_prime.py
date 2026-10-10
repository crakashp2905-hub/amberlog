"""PA′: if not blame, then what?

Pre-registration: research/prereg/phase-a-prime-attribution.md.

Phase A established that withdrawing the memory which asserted the action the
agent wrongly took makes an agent much worse — it cut the rate at which a correct
memory reached the prompt from 60% of episodes to 18%. It did not establish what
to do instead, and the product still offers a one-command `quarantine` to an
operator who will reach for exactly that rule.

Five withdrawal policies over the identical world, corpus and episodes:

    shared_memory        withdraw nothing. The baseline, because it won Phase A
    fabric_blame         the memory that asserted the agent's wrong answer
    fabric_loo           only a memory whose removal would have fixed the episode
    fabric_contrastive   only a memory whose contrastive estimate shows harm
    oracle               the corrected ceiling (Phase A amendment 3)

The registration predicts PA′1 fails — that no withdrawal policy beats
withdrawing nothing — and says why: in this world the corpus holds far more
useful lessons than harmful ones, so any withdrawal policy is a bet against that
ratio.

    python -m experiments.phase_a_prime --pilot
    python -m experiments.phase_a_prime
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

from memory_fabric import (
    EpsilonGreedyPolicy,
    LifecycleState,
    MemoryFabric,
    TopKPolicy,
)
from memory_fabric.adapters.context import build_context
from memory_fabric.adapters.ollama import OllamaClient, OllamaEmbedder, OllamaError
from memory_fabric.cli import configure_output
from memory_fabric.vectors import VectorIndex

from . import depotworld as W
from . import stats
from .phase_a import (
    AGENT_MODEL,
    SYSTEM,
    ArmResult,
    Decision,
    Lesson,
    _ask,
    _score,
    release_schedule,
    run_simple_arm,
    write_corpus,
)

ARMS = (
    "no_memory",
    "shared_memory",
    "fabric_blame",
    "fabric_loo",
    "fabric_contrastive",
    "oracle",
)
WITHDRAWING = ("fabric_blame", "fabric_loo", "fabric_contrastive")


@dataclass
class Withdrawal:
    """One memory taken out of circulation, and whether that was a mistake.

    `was_correct` is the diagnostic Phase A only found by looking: a policy can
    score acceptably on success while quietly destroying good material, and a
    count of withdrawals alone cannot tell a careful policy from a lucky one.
    """

    arm: str
    seed: int
    index: int
    memory_id: str
    fault: str
    asserted: str
    was_correct: bool
    reason: str


@dataclass
class ArmRun:
    result: ArmResult
    withdrawals: list[Withdrawal] = field(default_factory=list)
    extra_calls: int = 0
    extra_tokens: float = 0.0


def _policy(arm: str):
    """`fabric_contrastive` needs overlap for its estimate to exist at all, so it
    runs epsilon-greedy. Phase A measured that exploration carrying a cost of its
    own; §3 of the registration states the resulting confound rather than
    leaving it to be discovered."""
    if arm == "fabric_contrastive":
        return EpsilonGreedyPolicy(epsilon=0.2, rank_by="value"), "amortized"
    return TopKPolicy(rank_by="relevance"), "naive_usage"


def _loo_withdrawals(
    shown: Sequence[tuple[str, Lesson]],
    episode: W.EvalEpisode,
    client: OllamaClient,
    model: str,
) -> tuple[list[tuple[str, Lesson]], int, float]:
    """Leave-one-out screening: re-ask without each memory, and withdraw only
    those whose absence produces the correct answer.

    This is MeClear's screening step. It is also the arm that cannot be deployed
    without a cheap verifier for every episode, which many tasks do not have —
    so its result is an upper bound on what attribution can buy rather than a
    recipe. Its extra calls are returned, because the cost is the point.
    """
    guilty: list[tuple[str, Lesson]] = []
    calls = 0
    tokens = 0.0
    for candidate_id, candidate in shown:
        others = [lesson.content for mid, lesson in shown if mid != candidate_id]
        text, used, _ = _ask(client, model, W.render_plain(others), episode)
        calls += 1
        tokens += used
        if W.parse_action(text) == episode.correct:
            # Removing this memory fixes the episode. That is attribution, not
            # agreement: the counterfactual is what identifies the cause.
            guilty.append((candidate_id, candidate))
    return guilty, calls, tokens


def run_arm(
    arm: str,
    seed: int,
    lessons: Sequence[Lesson],
    episodes: Sequence[W.EvalEpisode],
    schedule: Sequence[int],
    client: OllamaClient,
    embedder: OllamaEmbedder,
    model: str,
    k: int = 3,
    verbose: bool = True,
) -> ArmRun:
    """Every memory arm. They share the governed write path and the same
    retrieval; the only difference is which memories a verified failure takes
    out of circulation, which is the whole question."""
    policy, estimator = _policy(arm)
    fabric = MemoryFabric(
        ":memory:", seed=seed, embedder=embedder,
        estimator=estimator, exposure_policy=policy,
    )
    run = ArmRun(result=ArmResult(arm))
    try:
        ids: dict[int, str] = {}
        by_fault: dict[str, list[str]] = {}
        contested: set[str] = set()

        for index, episode in enumerate(episodes):
            for i in range(schedule[index]):
                if i in ids:
                    continue
                lesson = lessons[i]
                mid = fabric.remember(
                    f"engineer-{lesson.site}", lesson.content,
                    context={"site": lesson.site, "fault": lesson.fault},
                )
                fabric.validate(mid, actor="depot-supervisor")
                ids[i] = mid
                by_fault.setdefault(lesson.fault, []).append(mid)

            for fault, group in by_fault.items():
                if len(group) < 2 or any(m in contested for m in group):
                    continue
                claims = {lessons[i].asserted for i, mid in ids.items() if mid in group}
                if len(claims) > 1:
                    fabric.challenge(
                        group,
                        evidence=f"lessons about {fault} assert different responses",
                        detector_id="consolidation",
                    )
                    contested.update(group)

            reverse = {mid: i for i, mid in ids.items()}
            with fabric.session(
                "engineer-field", f"{arm}-{seed}-{index}",
                {"site": episode.site, "fault": episode.fault},
            ) as session:
                started = time.perf_counter()
                hits = session.recall(W.recall_query(episode), k=k, include_contested=True)
                exposed = list(hits.exposed)
                memory_ms = (time.perf_counter() - started) * 1000.0
                memory_text = (
                    build_context(fabric, exposed, W.recall_query(episode)).render()
                    if exposed else ""
                )
                text, tokens, model_ms = _ask(client, model, memory_text, episode)
                shown_pairs = [
                    (m.id, lessons[reverse[m.id]]) for m in exposed if m.id in reverse
                ]
                decision = _score(
                    arm, seed, index, episode, [lesson for _, lesson in shown_pairs],
                    text, tokens, memory_ms, model_ms, store_size=len(ids),
                )
                session.record_outcome(
                    1.0 if decision.success else 0.0, verifier_id="depotworld"
                )
            run.result.decisions.append(decision)

            if not decision.success and arm in WITHDRAWING and shown_pairs:
                guilty: list[tuple[str, Lesson]] = []
                reason = ""
                if arm == "fabric_blame":
                    reason = "asserted the action the agent took"
                    guilty = [
                        pair for pair in shown_pairs
                        if decision.answered and pair[1].asserted == decision.answered
                    ]
                elif arm == "fabric_loo":
                    reason = "removing it would have fixed the episode"
                    guilty, calls, extra = _loo_withdrawals(
                        shown_pairs, episode, client, model
                    )
                    run.extra_calls += calls
                    run.extra_tokens += extra
                else:
                    reason = "contrastive estimate shows harm"
                    for mid, lesson in shown_pairs:
                        value = fabric.value(mid)
                        if value.contrastive and value.n_eff > 0 and value.ci_high < 0.0:
                            guilty.append((mid, lesson))

                for mid, lesson in guilty:
                    if fabric.get(mid).lifecycle_state == LifecycleState.QUARANTINED:
                        continue
                    fabric.quarantine(mid, reason=reason, actor="depotworld")
                    run.withdrawals.append(
                        Withdrawal(
                            arm=arm, seed=seed, index=index, memory_id=mid,
                            fault=lesson.fault, asserted=lesson.asserted,
                            # Correct where it was written, which is what makes
                            # withdrawing it a loss rather than a cleanup.
                            was_correct=not lesson.poisoned,
                            reason=reason,
                        )
                    )
            if verbose:
                mark = "ok " if decision.success else ("HARM" if decision.harmful else "miss")
                print(f"    {arm:<20} {index:>2} {episode.fault} {episode.site:<11}"
                      f"{'EXC' if episode.is_exception else '   '} -> "
                      f"{str(decision.answered):<18} {mark} "
                      f"[{decision.shown_right}+/{decision.shown_wrong}- of "
                      f"{len(decision.shown)}]", flush=True)
    finally:
        fabric.close()
    return run


def run_vector_baseline(
    seed: int,
    lessons: Sequence[Lesson],
    episodes: Sequence[W.EvalEpisode],
    schedule: Sequence[int],
    client: OllamaClient,
    embedder: OllamaEmbedder,
    model: str,
    k: int = 3,
    verbose: bool = True,
) -> ArmRun:
    """`shared_memory`: pooled, ungoverned, withdraws nothing. Identical to the
    arm that won Phase A, carried over unchanged so the baseline is the same
    one."""
    run = ArmRun(result=ArmResult("shared_memory"))
    index_store = VectorIndex(embedder)
    admitted: set[int] = set()
    for index, episode in enumerate(episodes):
        for i, lesson in enumerate(lessons[: schedule[index]]):
            if i not in admitted:
                index_store.add(str(i), lesson.content)
                admitted.add(i)
        started = time.perf_counter()
        hits = index_store.search(
            W.recall_query(episode), k=k, restrict_to={str(i) for i in admitted}
        )
        memory_ms = (time.perf_counter() - started) * 1000.0
        shown = [lessons[int(key)] for key, _ in hits]
        text, tokens, model_ms = _ask(
            client, model, W.render_plain([lesson.content for lesson in shown]), episode
        )
        decision = _score(
            "shared_memory", seed, index, episode, shown, text, tokens,
            memory_ms, model_ms, store_size=len(admitted),
        )
        run.result.decisions.append(decision)
        if verbose:
            mark = "ok " if decision.success else ("HARM" if decision.harmful else "miss")
            print(f"    {'shared_memory':<20} {index:>2} {episode.fault} "
                  f"{episode.site:<11}{'EXC' if episode.is_exception else '   '} -> "
                  f"{str(decision.answered):<18} {mark} "
                  f"[{decision.shown_right}+/{decision.shown_wrong}- of "
                  f"{len(decision.shown)}]", flush=True)
    return run


def right_memory_rate(result: ArmResult) -> list[float]:
    """Promoted to a primary metric by the registration: Phase A found this is
    nearly the whole story, since every arm converts a correct memory into a
    correct answer about 95% of the time."""
    return [1.0 if d.shown_right > 0 else 0.0 for d in result.decisions]


def run_seed(
    seed: int,
    client: OllamaClient,
    embedder: OllamaEmbedder,
    model: str,
    arms: Sequence[str],
    episodes: int,
    verbose: bool,
) -> dict[str, ArmRun]:
    rng = random.Random(seed)
    truth = W.build_truth(rng)
    learning = W.learning_episodes(truth, rng)
    evaluation = W.eval_episodes(truth, rng, count=episodes)

    print(f"  seed {seed}: writing {len(learning)} lessons "
          f"({sum(e.poisoned for e in learning)} poisoned)...", flush=True)
    lessons = write_corpus(learning, client, model, verbose=verbose)
    print(f"  seed {seed}: {len(lessons)}/{len(learning)} usable lessons; "
          f"{sum(1 for l in lessons if l.poisoned)} assert a wrong action for "
          f"their own site", flush=True)
    if len(lessons) < 6:
        raise RuntimeError(f"seed {seed}: only {len(lessons)} usable lessons")

    embedder.warm([lesson.content for lesson in lessons])
    embedder.warm([W.recall_query(e) for e in evaluation])
    schedule = release_schedule(len(lessons), len(evaluation))

    out: dict[str, ArmRun] = {}
    for arm in arms:
        started = time.perf_counter()
        if arm in ("no_memory", "oracle"):
            out[arm] = ArmRun(result=run_simple_arm(
                arm, seed, lessons, evaluation, schedule, client, model,
                embedder=embedder, verbose=verbose,
            ))
        elif arm == "shared_memory":
            out[arm] = run_vector_baseline(
                seed, lessons, evaluation, schedule, client, embedder, model,
                verbose=verbose,
            )
        else:
            out[arm] = run_arm(
                arm, seed, lessons, evaluation, schedule, client, embedder, model,
                verbose=verbose,
            )
        cell = out[arm]
        lost = sum(1 for w in cell.withdrawals if w.was_correct)
        print(f"  seed {seed} {arm:<20} success {stats.mean(cell.result.success):>5.0%}  "
              f"right-memory {stats.mean(right_memory_rate(cell.result)):>5.0%}  "
              f"withdrew {len(cell.withdrawals):>2} ({lost} correct)  "
              f"({time.perf_counter()-started:.0f}s)", flush=True)
    return out


def report(pooled: dict[str, ArmRun], arms: Sequence[str]) -> dict[str, object]:
    print(f"\n{'arm':<20} {'success':>18} {'right memory':>18} {'withdrew':>9} "
          f"{'of those ok':>12} {'tokens':>8} {'calls/ep':>9}")
    print("-" * 102)
    summary: dict[str, object] = {}
    for arm in arms:
        cell = pooled[arm]
        n = len(cell.result.decisions)
        lost = sum(1 for w in cell.withdrawals if w.was_correct)
        calls_per_episode = 1.0 + (cell.extra_calls / n if n else 0.0)
        print(f"{arm:<20} {stats.fmt_ci(cell.result.success):>18} "
              f"{stats.fmt_ci(right_memory_rate(cell.result)):>18} "
              f"{len(cell.withdrawals):>9} {lost:>12} "
              f"{stats.mean(cell.result.column('tokens')) + (cell.extra_tokens / n if n else 0):>8.0f} "
              f"{calls_per_episode:>9.2f}")
        summary[arm] = {
            "success": stats.mean(cell.result.success),
            "right_memory_rate": stats.mean(right_memory_rate(cell.result)),
            "harmful": stats.mean(cell.result.harmful),
            "contamination": stats.mean(cell.result.contamination),
            "withdrawals": len(cell.withdrawals),
            "withdrawals_correct": lost,
            "tokens_per_episode": stats.mean(cell.result.column("tokens"))
            + (cell.extra_tokens / n if n else 0),
            "calls_per_episode": calls_per_episode,
            "first_third": cell.result.thirds()[0],
            "last_third": cell.result.thirds()[1],
            "n": n,
        }
    return summary


def verdict(pooled: dict[str, ArmRun]) -> None:
    """Against §5 of the registration, and nothing else."""
    if not all(arm in pooled for arm in ARMS):
        print("\n(partial run: verdict needs every arm)")
        return

    base = pooled["shared_memory"].result
    ceiling = pooled["oracle"].result
    blame = pooled["fabric_blame"].result
    loo = pooled["fabric_loo"].result

    floor_v = stats.mean(base.success)
    ceil_v = stats.mean(ceiling.success)
    headroom = ceil_v - floor_v

    print("\n=== Against the pre-registration ===")
    print(f"  baseline (withdraw nothing): {floor_v:.1%}")
    print(f"  ceiling (corrected oracle):  {ceil_v:.1%}")
    print(f"  headroom:                    {headroom:+.1%}")

    best = max(WITHDRAWING, key=lambda a: stats.mean(pooled[a].result.success))
    best_v = stats.mean(pooled[best].result.success)
    diffs = [t - b for t, b in zip(pooled[best].result.success, base.success)]
    low, high = stats.bootstrap_ci(diffs)
    share = (best_v - floor_v) / headroom if headroom > 0 else float("nan")
    print(f"\n  PA'1 best withdrawal arm: {best} at {best_v:.1%}")
    print(f"       headroom captured {share:.0%} (needs >= 30%), "
          f"paired diff {stats.mean(diffs):+.3f} [{low:+.3f}, {high:+.3f}]")
    pa1 = headroom > 0 and share >= 0.30 and low > 0

    gap = floor_v - stats.mean(blame.success)
    recovered = stats.mean(loo.success) - stats.mean(blame.success)
    closed = recovered / gap if gap > 0 else float("nan")
    ldiffs = [l - b for l, b in zip(loo.success, blame.success)]
    llow, lhigh = stats.bootstrap_ci(ldiffs)
    blame_lost = sum(1 for w in pooled["fabric_blame"].withdrawals if w.was_correct)
    loo_lost = sum(1 for w in pooled["fabric_loo"].withdrawals if w.was_correct)
    print(f"\n  PA'2 leave-one-out vs naive blame:")
    print(f"       gap to close {gap:+.1%}, recovered {recovered:+.1%} "
          f"= {closed:.0%} (needs >= 50%)")
    print(f"       paired diff {stats.mean(ldiffs):+.3f} [{llow:+.3f}, {lhigh:+.3f}]")
    print(f"       correct memories withdrawn: blame {blame_lost}, loo {loo_lost} "
          f"(loo must be fewer)")
    pa2 = gap > 0 and closed >= 0.50 and llow > 0 and loo_lost < blame_lost

    n = len(loo.decisions)
    print(f"\n  cost of attribution: {1.0 + pooled['fabric_loo'].extra_calls / n:.2f} "
          f"model calls per episode against 1.00 for the baseline "
          f"({pooled['fabric_loo'].extra_calls} counterfactual calls in all)")

    print(f"\n  replication check: fabric_blame {stats.fmt_ci(blame.success)} "
          f"against Phase A's fabric 0.283 [0.208, 0.367]")

    print(f"\n  PA'1: {'SUPPORTED' if pa1 else 'KILLED'}")
    print(f"  PA'2: {'SUPPORTED' if pa2 else 'KILLED'}")
    if not pa1:
        print("\n  Product conclusion: do not withdraw memories on outcome "
              "evidence at this hazard rate.")


def main(argv: Sequence[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="PA': if not blame, then what?")
    parser.add_argument("--pilot", action="store_true", help="one seed, 12 episodes")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--episodes", type=int, default=24)
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
    episodes = 12 if args.pilot else args.episodes

    print("PA': if not blame, then what?")
    print(f"model={model}  seeds={seeds}  episodes={episodes}  arms={arms}")
    print("prereg: research/prereg/phase-a-prime-attribution.md\n")

    embedder = OllamaEmbedder(client)
    pooled: dict[str, ArmRun] = {arm: ArmRun(result=ArmResult(arm)) for arm in arms}
    started = time.perf_counter()
    for seed in seeds:
        per_seed = run_seed(
            seed, client, embedder, model, arms, episodes, verbose=not args.quiet
        )
        for arm, cell in per_seed.items():
            pooled[arm].result.decisions.extend(cell.result.decisions)
            pooled[arm].withdrawals.extend(cell.withdrawals)
            pooled[arm].extra_calls += cell.extra_calls
            pooled[arm].extra_tokens += cell.extra_tokens

    summary = report(pooled, arms)
    verdict(pooled)

    total = client.usage()
    print(f"\n{total['calls']:.0f} model calls, {total['tokens']:.0f} tokens, "
          f"{time.perf_counter()-started:.0f}s wall")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "model": model, "seeds": seeds, "episodes": episodes,
                    "summary": summary, "usage": total,
                    "decisions": [
                        asdict(d) for cell in pooled.values()
                        for d in cell.result.decisions
                    ],
                    "withdrawals": [
                        asdict(w) for cell in pooled.values() for w in cell.withdrawals
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
