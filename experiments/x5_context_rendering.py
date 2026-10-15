"""X5 — does the governed context rendering cost accuracy?

Registered in `research/prereg/x5-context-rendering.md`.

[X4](../research/results/x4-governed-vs-pooled.md) found that the governed arm
put the correct lesson in context **more** often than any pooled arm and
converted it **equally or less** often. Its arms differed in retrieval *and* in
rendering, so it could not attribute that -- and its minimum detectable effect
was 0.10 to 0.14 against an observed 0.04, so it could not have detected it
either.

Here **retrieval happens once per episode** and the identical exposed memories
are rendered four ways, so rendering is the only variable and every comparison
is paired per episode. 640 pairs, for an MDE of about 0.05 matched to the
registered action threshold.

## The four renderings

`build_context` bundles three separable things, and a single rich-versus-plain
test could not tell you which matters:

    plain       bare contents, as the pooled arms in X4 used
    delimited   injection preamble + <retrieved_memories> delimiters
    annotated   delimiters + per-memory [id | type | evidence | state] headers
    full        all three -- what ships

`full - annotated` is the preamble's cost, `full - delimited` the annotations',
`full - plain` the total.

**The preamble is a documented security control** (SECURITY.md T1: a retrieved
memory is text an earlier run wrote, and a poisoned one is a prompt-injection
payload aimed at every later run). A result showing it costs accuracy is a
*trade*, not a recommendation, and the registration says so in advance.
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments import checks  # noqa: E402
from experiments import depotworld as W  # noqa: E402
from experiments import phase_a_prime as PA  # noqa: E402
from memory_fabric import MemoryFabric  # noqa: E402
from memory_fabric.adapters.context import (  # noqa: E402
    CLOSE, INJECTION_PREAMBLE, OPEN, build_context,
)

RENDERINGS = ("plain", "delimited", "annotated", "full")

EVIDENCE_SENTENCE = "Each memory carries how well it is evidenced"


def preamble_without_evidence() -> str:
    """The injection preamble minus its sentence about evidence labels.

    Used by the `delimited` arm, which has no labels for that sentence to refer
    to. Derived from the shipped constant rather than copied, so a change to
    the preamble cannot silently desynchronise this arm.
    """
    head, _, _tail = INJECTION_PREAMBLE.partition(EVIDENCE_SENTENCE)
    return head.strip() if head.strip() else INJECTION_PREAMBLE



@dataclass
class Trial:
    """One episode, rendered every way. The unit of pairing."""

    seed: int
    index: int
    fault: str
    site: str
    right_memory: bool
    success: dict[str, bool] = field(default_factory=dict)
    hedged: dict[str, bool] = field(default_factory=dict)
    prompt_tokens: dict[str, int] = field(default_factory=dict)


def render(kind: str, fabric: MemoryFabric, exposed: Sequence[Any],
           query: str) -> str:
    """One exposed set, four ways.

    `delimited` and `annotated` are built from the same `MemoryBlock`s the
    shipped path uses, so the only thing that varies is which of the three
    components is present -- not two separate code paths that might differ for
    some other reason.
    """
    if not exposed:
        return ""
    if kind == "plain":
        return W.render_plain([m.content for m in exposed])
    context = build_context(fabric, exposed, query)
    if kind == "full":
        return context.render()
    if kind == "annotated":
        # Everything except the preamble.
        return context.render(preamble="").strip()
    if kind == "delimited":
        # Preamble and delimiters, blocks reduced to their content -- and the
        # preamble's *evidence* sentence removed along with them.
        #
        # The shipped preamble ends "Each memory carries how well it is
        # evidenced - prefer well-evidenced ones, treat contested ones as open
        # questions...". With no annotations present that sentence points at
        # labels the model cannot see, which would handicap this arm and
        # inflate the measured cost of the annotations.
        #
        # So `full - delimited` measures the annotations **together with the
        # sentence that explains them**, which is the right unit for a product
        # decision: you would not ship the labels without telling the model
        # what they mean, nor keep the explanation without the labels.
        body = "\n\n".join(block.content for block in context.blocks)
        return f"{preamble_without_evidence()}\n\n{OPEN}\n{body}\n{CLOSE}"
    raise ValueError(f"unknown rendering {kind!r}")


def run_seed(seed: int, client: Any, embedder: Any, model: str,
             episodes: int, verbose: bool) -> list[Trial]:
    rng = random.Random(seed)
    truth = W.build_truth(rng)
    learning = W.learning_episodes(truth, rng)
    evaluation = W.eval_episodes(truth, rng, count=episodes)

    lessons = PA.write_corpus(learning, client, model, verbose=verbose)
    if len(lessons) < 6:
        raise RuntimeError(f"seed {seed}: only {len(lessons)} usable lessons")
    embedder.warm([l.content for l in lessons])
    embedder.warm([W.recall_query(e) for e in evaluation])
    schedule = PA.release_schedule(len(lessons), len(evaluation))
    print(f"  seed {seed}: {len(lessons)} lessons, "
          f"{sum(1 for l in lessons if l.poisoned)} poisoned", flush=True)

    policy, estimator = PA._policy("shared_memory")
    fabric = MemoryFabric(":memory:", seed=seed, embedder=embedder,
                          estimator=estimator, exposure_policy=policy)
    trials: list[Trial] = []
    try:
        ids: dict[int, str] = {}
        for index, episode in enumerate(evaluation):
            for i in range(schedule[index]):
                if i in ids:
                    continue
                lesson = lessons[i]
                mid = fabric.remember(
                    f"engineer-{lesson.site}", lesson.content,
                    context={"site": lesson.site, "fault": lesson.fault})
                fabric.validate(mid, actor="depot-supervisor")
                ids[i] = mid

            reverse = {mid: i for i, mid in ids.items()}
            query = W.recall_query(episode)
            # ONE retrieval, shared by every rendering. This is the whole
            # design: X4 varied retrieval and rendering together and could
            # attribute neither.
            result = fabric.retrieve(
                agent_id="engineer-field", query=query, k=3,
                min_relevance=0.0, context={"site": episode.site,
                                            "fault": episode.fault})
            exposed = list(result.exposed)
            shown = [lessons[reverse[m.id]] for m in exposed
                     if m.id in reverse]
            trial = Trial(
                seed=seed, index=index, fault=episode.fault,
                site=episode.site,
                right_memory=any(l.right_for(episode) for l in shown),
            )
            for kind in RENDERINGS:
                text = render(kind, fabric, exposed, query)
                reply, tokens, _ms = PA._ask(client, model, text, episode)
                decision = PA._score(
                    kind, seed, index, episode, shown, reply, tokens,
                    0.0, 0.0, store_size=len(ids))
                trial.success[kind] = bool(decision.success)
                trial.hedged[kind] = bool(getattr(decision, "hedged", False))
                trial.prompt_tokens[kind] = len(text.split())
            trials.append(trial)
            if verbose and index % 25 == 0:
                print(f"    seed {seed} episode {index}: "
                      + "  ".join(f"{k}={trial.success[k]}" for k in RENDERINGS),
                      flush=True)
    finally:
        fabric.close()
    return trials


def paired(trials: Sequence[Trial], left: str, right: str,
           seed: int = 7, draws: int = 2000) -> dict[str, Any]:
    """Mean of (left - right) with a bootstrap CI, and the discordance rate.

    Discordance is reported because it sets the realised power: the registered
    MDE assumed a rate, and a reader should be able to see whether that held
    rather than take the power calculation on trust.
    """
    deltas = [float(t.success[left]) - float(t.success[right])
              for t in trials]
    if not deltas:
        return {}
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        sample = [deltas[rng.randrange(len(deltas))] for _ in deltas]
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = means[int(0.025 * draws)]
    hi = means[int(0.975 * draws)]
    discordant = sum(1 for d in deltas if d != 0.0) / len(deltas)
    point = sum(deltas) / len(deltas)
    return {
        "comparison": f"{left} - {right}",
        "n_pairs": len(deltas),
        "mean": round(point, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "excludes_zero": bool(lo > 0.0 or hi < 0.0),
        "discordance": round(discordant, 4),
        "realised_se": round((discordant / len(deltas)) ** 0.5, 4),
    }


def run(seeds: int, episodes: int, model: str, verbose: bool) -> dict[str, Any]:
    from memory_fabric.adapters.ollama import OllamaClient, OllamaEmbedder

    client = OllamaClient()
    embedder = OllamaEmbedder(client=client)
    started = time.perf_counter()

    trials: list[Trial] = []
    for seed in range(seeds):
        trials += run_seed(seed, client, embedder, model, episodes, verbose)
        done = {k: stats.mean(float(t.success[k]) for t in trials)
                for k in RENDERINGS}
        print(f"  after seed {seed}: "
              + "  ".join(f"{k}={v:.3f}" for k, v in done.items()), flush=True)

    arms = {
        kind: {
            "success": round(stats.mean(float(t.success[kind]) for t in trials), 4),
            "hedged": round(stats.mean(float(t.hedged[kind]) for t in trials), 4),
            "prompt_words": round(stats.mean(
                t.prompt_tokens[kind] for t in trials), 1),
        }
        for kind in RENDERINGS
    }
    comparisons = {
        "total (plain - full)": paired(trials, "plain", "full"),
        "annotations (delimited - full)": paired(trials, "delimited", "full"),
        "preamble (annotated - full)": paired(trials, "annotated", "full"),
        "plain - delimited": paired(trials, "plain", "delimited"),
    }
    primary = comparisons["total (plain - full)"]
    supported = bool(primary.get("excludes_zero")
                     and (primary.get("mean") or 0.0) >= 0.05)
    real_but_small = bool(primary.get("excludes_zero") and not supported)

    return {
        "experiment": "x5-context-rendering",
        "model": model, "seeds": seeds, "episodes": episodes,
        "pairs": len(trials),
        "right_memory": round(
            stats.mean(float(t.right_memory) for t in trials), 4),
        "arms": arms,
        "comparisons": comparisons,
        "registered": {
            "threshold": 0.05,
            "primary": primary,
            "supported": supported,
            "real_but_below_action_threshold": real_but_small,
        },
        "checks": checks.verify(
            # Retrieval is shared, so a per-arm difference in which memories
            # were present would mean the pairing is broken. There is no
            # selection oracle here and section 3 of the registration says
            # why, so `ceiling` has nothing to bound.
            shared_retrieval={
                "ok": True,
                "note": ("one retrieval per episode feeds every rendering, so "
                         "right_memory is identical by construction; a "
                         "difference would be a bug rather than a finding"),
                "right_memory": round(
                    stats.mean(float(t.right_memory) for t in trials), 4),
            },
            power={
                "ok": primary.get("realised_se", 1.0) * 2.80 <= 0.06,
                "registered_mde": 0.05,
                "realised_mde": round(
                    (primary.get("realised_se") or 0.0) * 2.80, 4),
                "note": ("the registered MDE assumed a discordance rate; this "
                         "is the realised one, so a reader can see whether "
                         "the power held"),
            },
        ),
        "cost": {
            "calls": float(len(client.calls)),
            "tokens": float(sum(c.tokens for c in client.calls)),
            "wall_s": round(time.perf_counter() - started, 1),
        },
    }


def to_markdown(result: Any) -> str:
    reg = result["registered"]
    lines = [
        "# X5 - does the governed context rendering cost accuracy?",
        "",
        f"- `{result['model']}`, {result['seeds']} seeds x "
        f"{result['episodes']} episodes = **{result['pairs']} paired "
        f"episodes**; one retrieval per episode, four renderings of the same "
        f"memories",
        f"- Correct lesson in context: {result['right_memory']} "
        f"(identical across arms by construction)",
        "",
        "| rendering | success | hedged | prompt words |",
        "|---|---|---|---|",
    ]
    for kind, row in result["arms"].items():
        lines.append(f"| `{kind}` | **{row['success']}** | {row['hedged']} | "
                     f"{row['prompt_words']} |")
    lines += ["", "| comparison | mean | 95% CI | excludes 0 | discordance |",
              "|---|---|---|---|---|"]
    for label, row in result["comparisons"].items():
        if not row:
            continue
        lines.append(
            f"| {label} | **{row['mean']:+}** | "
            f"[{row['ci95'][0]:+}, {row['ci95'][1]:+}] | "
            f"{'yes' if row['excludes_zero'] else 'no'} | "
            f"{row['discordance']} |")
    if reg["supported"]:
        verdict = "SUPPORTED - the rendering costs accuracy above the action threshold"
    elif reg["real_but_below_action_threshold"]:
        verdict = ("REAL BUT BELOW THE ACTION THRESHOLD - the CI excludes zero "
                   "and the effect is under 0.05")
    else:
        verdict = "NOT SUPPORTED"
    power = result["checks"]["power"]
    lines += [
        "",
        f"**{verdict}.**",
        "",
        f"Realised MDE {power['realised_mde']} against a registered "
        f"{power['registered_mde']}; X4's was 0.10-0.14 against an observed "
        f"0.04, which is why this run exists at this size.",
        "",
        "A result against the preamble is a **trade** with a documented "
        "security control, not a recommendation - see section 2 of the "
        "registration.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pilot", action="store_true",
                        help="one seed, 16 episodes")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--episodes", type=int, default=128)
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    seeds = 1 if args.pilot else args.seeds
    episodes = 16 if args.pilot else args.episodes
    result = run(seeds, episodes, args.model, args.verbose)
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
