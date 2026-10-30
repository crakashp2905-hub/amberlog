"""X4 — the governed store against a pooled one, when memory gets corrected.

Registered in `research/prereg/x4-governed-vs-pooled.md`.

[Phase A](../research/results/phase-a-real-agent-benchmark.md) killed the
headline claim at 0.283 against a pooled store's 0.583, and
[PA'](../research/results/phase-a-prime-attribution.md) confirmed it with
better attribution. Every governed arm in both used
**withdrawal-on-failure**, which the product now warns against. Phase A's own
section 7.3 says *"a different governed policy might not lose"*, and nobody
measured one.

DepotWorld cannot answer that on its own: it has a poison rate and
site-dependent truth, which is a world for *detecting* bad memory, and no
retractions, no re-ingested copies and no time-varying truth. So this adds
**one** event and nothing else: an origin retracting its own lesson.

## The arms

    no_memory              floor
    shared_memory          pooled, corrections arrive as documents, originals kept
    shared_memory_delete   pooled, corrections delete the best text match -- the STRONG baseline
    fabric_governed        provenance-linked retraction, NO outcome-driven withdrawal
    oracle                 ceiling

`shared_memory_delete` is what makes this honest. A competent engineer with a
vector store does not ignore a correction; they find the document and remove
it. If the governed arm only beats *ignoring* corrections, the claim is
worthless.

## The correction rate is swept, not chosen

0.0, 0.5, 1.0 of the poisoned lessons get retracted. **Rate 0 is the
adversarial point** and the registration requires it to be near-neutral, not
merely reported: a mechanism that wins when corrections are frequent and hurts
when they are absent is a liability a reader has to be told about.

Every arm receives the same correction text. The governed arm's only extra is
the provenance link, which is the thing under test.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as stats
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from experiments import checks  # noqa: E402
from experiments import depotworld as W  # noqa: E402
from experiments import phase_a_prime as PA  # noqa: E402
from amberlog import LifecycleState, Amberlog  # noqa: E402
from amberlog.adapters.context import build_context  # noqa: E402

ARMS = ("no_memory", "shared_memory", "shared_memory_delete",
        "fabric_governed", "oracle")
RATE_FREE = ("no_memory",)
"""Arms whose behaviour cannot depend on the correction rate.

**`oracle` is not one of them**, and the pilot proved it: `shared_memory` at
rate 1.0 scored 1.000 against the oracle's 0.917, and `checks.ceiling` failed
on the run. The cause was mine. The correction stream hands every other arm an
explicit instruction -- *"the lesson about E03 at coastal is wrong, disregard
it"* -- and the oracle, which only *filters* wrong lessons out, never saw that
text. An arm with information the ceiling lacks is not bounded by it.

This is Phase A's amendment 3 recurring in a new form. There the oracle showed
one memory where every arm showed three; here it sees one fewer document than
every arm at a non-zero rate. Principle 8b: the oracle gets the same budget,
the same k and the same mechanisms, differing only in knowing the answer. So
it is swept too, and receives the same corrections."""

RATES = (0.0, 0.5, 1.0)


@dataclass
class Correction:
    """An origin retracting its own lesson.

    `text` is what every arm sees. `lesson_index` is the provenance link, which
    only the governed arm can use -- and which is the claim under test.
    """

    lesson_index: int
    fault: str
    site: str
    text: str


def corrections_for(lessons: Sequence[PA.Lesson], rate: float,
                    rng: random.Random) -> list[Correction]:
    """Retract a swept fraction of the lessons that assert a wrong action.

    The world knows which those are because it created them, and **it tells
    every arm**, in the same words. See section 2 of the registration for why
    that is a comparison of mechanisms rather than of information.
    """
    poisoned = [i for i, lesson in enumerate(lessons) if lesson.poisoned]
    rng.shuffle(poisoned)
    chosen = poisoned[:round(rate * len(poisoned))]
    out = []
    for index in sorted(chosen):
        lesson = lessons[index]
        out.append(Correction(
            lesson_index=index, fault=lesson.fault, site=lesson.site,
            text=(f"Correction from engineer-{lesson.site}: the lesson I "
                  f"wrote about fault {lesson.fault} at the {lesson.site} "
                  f"site was based on a misdiagnosis and is wrong. Disregard "
                  f"it."),
        ))
    return out


def run_governed(
    seed: int, lessons: Sequence[PA.Lesson],
    episodes: Sequence[W.EvalEpisode], schedule: Sequence[int],
    corrections: Sequence[Correction], client: Any, embedder: Any,
    model: str, k: int = 3, verbose: bool = False,
) -> PA.ArmRun:
    """The recommended configuration: provenance, contested-on-conflict and
    bitemporal validity on; **withdrawal on outcome evidence off**.

    A correction arrives as a memory *and* as a retraction carrying the
    retracted memory's id, so the store quarantines it and contests whatever
    was derived from it. That is PB2's mechanism, which measured acting on
    origin-retracted memory falling from 17% to 0% across a federation
    boundary; here it runs inside one store against a pooled baseline holding
    the same text.
    """
    policy, estimator = PA._policy("shared_memory")
    fabric = Amberlog(
        ":memory:", seed=seed, embedder=embedder,
        estimator=estimator, exposure_policy=policy,
    )
    run = PA.ArmRun(result=PA.ArmResult("fabric_governed"))
    pending = {c.lesson_index: c for c in corrections}
    applied: set[int] = set()
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
                    context={"site": lesson.site, "fault": lesson.fault}, scope="team",
                )
                fabric.validate(mid, actor="depot-supervisor")
                ids[i] = mid
                by_fault.setdefault(lesson.fault, []).append(mid)

            # Contested-on-conflict, exactly as PA' does it, because H4b
            # measured this helping and it is part of the recommended
            # configuration rather than an addition for this experiment.
            for fault, group in by_fault.items():
                if len(group) < 2 or any(m in contested for m in group):
                    continue
                claims = {lessons[i].asserted
                          for i, mid in ids.items() if mid in group}
                if len(claims) > 1:
                    fabric.challenge(
                        group,
                        evidence=f"lessons about {fault} assert different responses",
                        detector_id="consolidation",
                    )
                    contested.update(group)

            # A correction lands as soon as its lesson is in the store.
            for lesson_index, correction in list(pending.items()):
                if lesson_index not in ids or lesson_index in applied:
                    continue
                fabric.remember(
                    f"engineer-{correction.site}", correction.text,
                    context={"site": correction.site, "fault": correction.fault}, scope="team",
                )
                fabric.quarantine(
                    ids[lesson_index],
                    reason="the origin retracted this observation",
                    actor=f"engineer-{correction.site}",
                    propagate=True,
                )
                applied.add(lesson_index)
                retracted = lessons[lesson_index]
                run.withdrawals.append(PA.Withdrawal(
                    arm="fabric_governed", seed=seed, index=index,
                    memory_id=ids[lesson_index], fault=retracted.fault,
                    asserted=retracted.asserted,
                    # False for every one of these by construction: only
                    # poisoned lessons are retracted. Recorded anyway, because
                    # Phase A's whole finding was that a withdrawal policy
                    # destroys correct memory, and an arm claiming it never
                    # does should have to say so in the same field.
                    was_correct=not retracted.poisoned,
                    reason="origin retraction",
                ))

            reverse = {mid: i for i, mid in ids.items()}
            with fabric.session(
                "engineer-field", f"governed-{seed}-{index}",
                {"site": episode.site, "fault": episode.fault},
            ) as session:
                started = time.perf_counter()
                hits = session.recall(W.recall_query(episode), k=k,
                                      include_contested=True)
                exposed = list(hits.exposed)
                memory_ms = (time.perf_counter() - started) * 1000.0
                memory_text = (
                    build_context(fabric, exposed, W.recall_query(episode)).render()
                    if exposed else ""
                )
                text, tokens, model_ms = PA._ask(client, model, memory_text, episode)
                shown = [lessons[reverse[m.id]] for m in exposed if m.id in reverse]
                decision = PA._score(
                    "fabric_governed", seed, index, episode, shown,
                    text, tokens, memory_ms, model_ms, store_size=len(ids),
                )
                session.record_outcome(
                    1.0 if decision.success else 0.0, verifier_id="depotworld")
            run.result.decisions.append(decision)
    finally:
        fabric.close()
    return run


def run_pooled(
    arm: str, seed: int, lessons: Sequence[PA.Lesson],
    episodes: Sequence[W.EvalEpisode], schedule: Sequence[int],
    corrections: Sequence[Correction], client: Any, embedder: Any,
    model: str, k: int = 3, verbose: bool = False,
) -> PA.ArmRun:
    """A pooled vector store, with and without best-effort deletion.

    `shared_memory` keeps the original and adds the correction, which is what
    an ungoverned store does by default. `shared_memory_delete` additionally
    removes the document the correction best matches **by embedding
    similarity**, which is what a competent engineer does and is the baseline
    that makes this comparison worth running.

    The deletion is deliberately not given the id. That is the whole
    difference being measured, and `wrongly_removed` counts what it costs.
    """
    from amberlog.vectors import cosine

    run = PA.ArmRun(result=PA.ArmResult(arm))
    live: dict[int, str] = {}
    extra: list[str] = []
    vectors: dict[int, list[float]] = {}
    pending = {c.lesson_index: c for c in corrections}
    applied: set[int] = set()
    wrongly_removed = 0

    for index, episode in enumerate(episodes):
        for i in range(schedule[index]):
            if i in live:
                continue
            live[i] = lessons[i].content
            vectors[i] = embedder.embed(lessons[i].content)

        for lesson_index, correction in list(pending.items()):
            if lesson_index not in live or lesson_index in applied:
                continue
            extra.append(correction.text)
            if arm == "shared_memory_delete":
                target = embedder.embed(correction.text)
                best, best_score = None, -2.0
                for i, vector in vectors.items():
                    if i not in live:
                        continue
                    score = cosine(target, vector)
                    if score > best_score:
                        best, best_score = i, score
                if best is not None:
                    if best != lesson_index:
                        wrongly_removed += 1
                    live.pop(best, None)
            applied.add(lesson_index)

        query = W.recall_query(episode)
        target = embedder.embed(query)
        scored = sorted(
            ((cosine(target, vectors[i]), i) for i in live),
            key=lambda row: -row[0],
        )[:k]
        shown = [lessons[i] for _s, i in scored]
        pieces = [lessons[i].content for _s, i in scored] + extra[-k:]
        memory_text = W.render_plain(pieces) if pieces else ""
        text, tokens, model_ms = PA._ask(client, model, memory_text, episode)
        decision = PA._score(
            arm, seed, index, episode, shown, text, tokens, 0.0, model_ms,
            store_size=len(live),
        )
        run.result.decisions.append(decision)
    # Carried on the run rather than the result, which PA' defines with only
    # `arm` and `decisions`: a shared dataclass is not the place for one
    # experiment's metric.
    run.wrongly_removed = wrongly_removed
    return run


def run_oracle(
    seed: int, lessons: Sequence[PA.Lesson],
    episodes: Sequence[W.EvalEpisode], schedule: Sequence[int],
    corrections: Sequence[Correction], client: Any, embedder: Any,
    model: str, k: int = 3, verbose: bool = False,
) -> PA.ArmRun:
    """Perfect filtering, the same budget, **and the same corrections**.

    Phase A's amendment 3 fixed this arm once, by giving it the same k as the
    arms it bounds rather than a single perfect memory. The correction stream
    broke it again from the other side: at a non-zero rate every other arm gets
    a document the oracle did not, and an arm with information the ceiling
    lacks is not bounded by it. So the oracle receives the corrections too, and
    keeps only its real advantage -- knowing which lessons are wrong for this
    episode.
    """
    from amberlog.vectors import VectorIndex

    run = PA.ArmRun(result=PA.ArmResult("oracle"))
    index = VectorIndex(embedder)
    admitted: set[int] = set()
    extra: list[str] = []
    applied: set[int] = set()
    pending = {c.lesson_index: c for c in corrections}

    for position, episode in enumerate(episodes):
        released = list(range(schedule[position]))
        for i in released:
            if i not in admitted:
                index.add(str(i), lessons[i].content)
                admitted.add(i)
        for lesson_index, correction in list(pending.items()):
            if lesson_index in released and lesson_index not in applied:
                extra.append(correction.text)
                applied.add(lesson_index)

        eligible = {str(i) for i in released
                    if not lessons[i].wrong_for(episode)}
        hits = index.search(W.recall_query(episode), k=k,
                            restrict_to=eligible) if eligible else []
        shown = [lessons[int(key)] for key, _score in hits]
        pieces = [l.content for l in shown] + extra[-k:]
        memory_text = W.render_plain(pieces) if pieces else ""
        text, tokens, model_ms = PA._ask(client, model, memory_text, episode)
        run.result.decisions.append(PA._score(
            "oracle", seed, position, episode, shown, text, tokens, 0.0,
            model_ms, store_size=len(released)))
    return run


def run_seed(seed: int, client: Any, embedder: Any, model: str,
             rates: Sequence[float], episodes: int,
             verbose: bool) -> dict[tuple[str, float | None], PA.ArmRun]:
    rng = random.Random(seed)
    truth = W.build_truth(rng)
    learning = W.learning_episodes(truth, rng)
    evaluation = W.eval_episodes(truth, rng, count=episodes)

    lessons = PA.write_corpus(learning, client, model, verbose=verbose)
    if len(lessons) < 6:
        raise RuntimeError(f"seed {seed}: only {len(lessons)} usable lessons")
    poisoned = sum(1 for l in lessons if l.poisoned)
    print(f"  seed {seed}: {len(lessons)} lessons, {poisoned} poisoned",
          flush=True)

    embedder.warm([l.content for l in lessons])
    embedder.warm([W.recall_query(e) for e in evaluation])
    schedule = PA.release_schedule(len(lessons), len(evaluation))

    out: dict[tuple[str, float | None], PA.ArmRun] = {}
    for arm in RATE_FREE:
        out[(arm, None)] = PA.ArmRun(result=PA.run_simple_arm(
            arm, seed, lessons, evaluation, schedule, client, model,
            embedder=embedder, verbose=verbose))
        print(f"  seed {seed} {arm:<22} success "
              f"{stats.mean(out[(arm, None)].result.success):>5.0%}", flush=True)

    for rate in rates:
        # One correction set per (seed, rate), shared by every arm at that
        # rate: the arms must see the same corrections or the comparison is
        # partly between correction sets.
        corrections = corrections_for(lessons, rate, random.Random(seed * 97))
        out[("oracle", rate)] = run_oracle(
            seed, lessons, evaluation, schedule, corrections, client,
            embedder, model, verbose=verbose)
        print(f"  seed {seed} rate {rate:<4} {'oracle':<22} success "
              f"{stats.mean(out[('oracle', rate)].result.success):>5.0%}",
              flush=True)
        for arm in ("shared_memory", "shared_memory_delete", "fabric_governed"):
            started = time.perf_counter()
            if arm == "fabric_governed":
                cell = run_governed(seed, lessons, evaluation, schedule,
                                    corrections, client, embedder, model,
                                    verbose=verbose)
            else:
                cell = run_pooled(arm, seed, lessons, evaluation, schedule,
                                  corrections, client, embedder, model,
                                  verbose=verbose)
            out[(arm, rate)] = cell
            print(f"  seed {seed} rate {rate:<4} {arm:<22} success "
                  f"{stats.mean(cell.result.success):>5.0%}  "
                  f"({len(corrections)} corrections, "
                  f"{time.perf_counter()-started:.0f}s)", flush=True)
    return out


def summarise(pooled: dict[tuple[str, float | None], list[PA.ArmRun]]
              ) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for (arm, rate), cells in pooled.items():
        successes = [s for cell in cells for s in cell.result.success]
        right = [r for cell in cells for r in PA.right_memory_rate(cell.result)]
        key = arm if rate is None else f"{arm}@{rate}"
        rows[key] = {
            "arm": arm, "rate": rate, "n": len(successes),
            "success": round(stats.mean(successes), 4) if successes else None,
            "right_memory": round(stats.mean(right), 4) if right else None,
            "wrongly_removed": sum(
                getattr(cell, "wrongly_removed", 0) or 0 for cell in cells),
            "withdrawals": sum(len(cell.withdrawals) for cell in cells),
        }
    return rows


def verdict(rows: dict[str, Any], rates: Sequence[float]) -> dict[str, Any]:
    out: dict[str, Any] = {"by_rate": {}}
    for rate in rates:
        # The oracle at this rate, because it is swept too -- see RATE_FREE.
        oracle = rows.get(f"oracle@{rate}", {}).get("success")
        baselines = [rows.get(f"{a}@{rate}", {}).get("success")
                     for a in ("shared_memory", "shared_memory_delete")]
        baselines = [b for b in baselines if b is not None]
        governed = rows.get(f"fabric_governed@{rate}", {}).get("success")
        if not baselines or governed is None or oracle is None:
            continue
        best = max(baselines)
        headroom = round(oracle - best, 4)
        bar = round(best + 0.40 * (oracle - best), 4)
        out["by_rate"][str(rate)] = {
            "C_oracle": oracle,
            "B_best_pooled": round(best, 4),
            "headroom": headroom,
            "bar": bar,
            "fabric_governed": governed,
            "passes_bar": governed >= bar,
            "abandoned_degenerate_headroom": headroom <= 0.05,
            "delta_vs_best_pooled": round(governed - best, 4),
        }
    zero = out["by_rate"].get("0.0")
    out["rate_zero_near_neutral"] = (
        None if zero is None else zero["delta_vs_best_pooled"] >= -0.05)
    passing = [r for r, row in out["by_rate"].items()
               if row["passes_bar"] and not row["abandoned_degenerate_headroom"]]
    out["supported"] = bool(passing) and bool(out["rate_zero_near_neutral"])
    out["rates_passing"] = passing
    return out


def run(seeds: int, episodes: int, rates: Sequence[float], model: str,
        verbose: bool) -> dict[str, Any]:
    from amberlog.adapters.ollama import OllamaClient, OllamaEmbedder

    client = OllamaClient()
    embedder = OllamaEmbedder(client=client)
    started = time.perf_counter()

    pooled: dict[tuple[str, float | None], list[PA.ArmRun]] = {}
    for seed in range(seeds):
        for key, cell in run_seed(seed, client, embedder, model, rates,
                                  episodes, verbose).items():
            pooled.setdefault(key, []).append(cell)

    rows = summarise(pooled)
    decision = verdict(rows, rates)
    return {
        "experiment": "x4-governed-vs-pooled",
        "model": model, "seeds": seeds, "episodes": episodes,
        "rates": list(rates),
        "arms": rows,
        "registered": decision,
        # Per rate, because the oracle is swept: comparing an arm at one rate
        # against a ceiling measured at another is how a ceiling stops being
        # one, which the pilot demonstrated.
        "checks": checks.verify(**{
            f"ceiling_at_{r}": checks.ceiling(
                {k: {"success": v["success"]} for k, v in rows.items()
                 if v["rate"] == r},
                "success", f"oracle@{r}")
            for r in rates
        }, **{
            f"baseline_max_at_{r}": checks.baseline_max(
                {k: {"success": v["success"]} for k, v in rows.items()
                 if v["rate"] == r},
                "success",
                [f"shared_memory@{r}", f"shared_memory_delete@{r}"],
                ceiling_arm=f"oracle@{r}")
            for r in rates
        }),
        "cost": {
            "calls": float(len(client.calls)),
            "tokens": float(sum(c.tokens for c in client.calls)),
            "wall_s": round(time.perf_counter() - started, 1),
        },
    }


def to_markdown(result: Any) -> str:
    reg = result["registered"]
    lines = [
        "# X4 - the governed store against a pooled one, when memory gets corrected",
        "",
        f"- `{result['model']}`, {result['seeds']} seeds x "
        f"{result['episodes']} episodes, correction rates {result['rates']}",
        "- The oracle is swept with the arms, so C is per rate; see RATE_FREE",
        "",
        "| arm | rate | success | right memory | wrongly removed | retractions |",
        "|---|---|---|---|---|---|",
    ]
    for key, row in result["arms"].items():
        rate = "-" if row["rate"] is None else row["rate"]
        lines.append(
            f"| `{row['arm']}` | {rate} | **{row['success']}** | "
            f"{row['right_memory']} | {row['wrongly_removed']} | "
            f"{row['withdrawals']} |")
    lines += ["", "| rate | C (oracle) | B (best pooled) | headroom | bar | "
              "fabric_governed | delta | passes |",
              "|---|---|---|---|---|---|---|---|"]
    for rate, row in reg["by_rate"].items():
        note = " (abandoned)" if row["abandoned_degenerate_headroom"] else ""
        lines.append(
            f"| {rate} | {row['C_oracle']} | {row['B_best_pooled']} | "
            f"{row['headroom']}{note} | {row['bar']} | "
            f"**{row['fabric_governed']}** | {row['delta_vs_best_pooled']:+} | "
            f"{'YES' if row['passes_bar'] else 'no'} |")
    lines += [
        "",
        f"**{'SUPPORTED' if reg['supported'] else 'NOT SUPPORTED'}** - rates "
        f"passing: {reg['rates_passing'] or 'none'}; rate-0 near-neutral: "
        f"{reg['rate_zero_near_neutral']}.",
        "",
        "The rate-0 row is the adversarial point: it measures what governance "
        "costs when nothing is ever corrected, and the registration requires "
        "it to be near-neutral rather than merely reported.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pilot", action="store_true",
                        help="one seed, 12 episodes, rates 0 and 1")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--episodes", type=int, default=24)
    parser.add_argument("--rates", type=float, nargs="*", default=list(RATES))
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    seeds = 1 if args.pilot else args.seeds
    episodes = 12 if args.pilot else args.episodes
    rates = [0.0, 1.0] if args.pilot else args.rates

    result = run(seeds, episodes, rates, args.model, args.verbose)
    if args.out:
        Path(args.out).write_text(
            json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    text = (json.dumps(result, indent=2, default=str) if args.as_json
            else to_markdown(result))
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
