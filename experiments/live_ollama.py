"""Live run: does the memory fabric actually change a real model's answers?

Every result in `research/` was produced with a scripted agent. That made
effects attributable and cheap, and it left one question open: whether a
language model behaves the way RuleWorld assumed. In particular RuleWorld's
central parameter — `compliance = 0.8`, the chance an agent follows a retrieved
claim — was a guess that every simulated number depends on.

This measures it, through the real path: `session.recall` -> `build_context` ->
prompt -> model -> verified outcome. Nothing is hand-assembled.

The task is multiple choice over 8 responses, so chance is 12.5% and the memory
is the only way to know the answer. Four arms:

    no_memory   nothing retrieved                  -> should sit at chance
    correct     the right claim is in the store    -> measures compliance
    wrong       a wrong claim is in the store      -> measures how misleadable
    contested   both, marked contested by the fabric -> tests whether the
                caveats in `adapters/context.py` do anything at all

    python -m experiments.live_ollama
    python -m experiments.live_ollama --quick
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Sequence

from memory_fabric import MemoryFabric
from memory_fabric.adapters.ollama import (
    OllamaClient,
    OllamaEmbedder,
    OllamaError,
    OllamaMemoryAgent,
)
from memory_fabric.cli import configure_output

from . import stats

ACTIONS = [
    "reseat_contactor",
    "replace_rcd",
    "reflash_firmware",
    "clean_earth_bond",
    "swap_pilot_cable",
    "recalibrate_meter",
    "reset_thermal_cutout",
    "replace_cooling_fan",
]

ARMS = ("no_memory", "correct", "wrong", "contested")
DEFAULT_MODELS = ("qwen2.5:3b", "llama3.2:3b")


@dataclass
class Trial:
    arm: str
    fault: str
    expected: str
    answered: str | None
    correct: bool
    retrieved: int
    retrieved_right_one: bool
    seconds: float


@dataclass
class ArmStats:
    arm: str
    trials: list[Trial] = field(default_factory=list)

    @property
    def accuracy(self) -> list[float]:
        return [1.0 if t.correct else 0.0 for t in self.trials]

    @property
    def unparsed(self) -> float:
        if not self.trials:
            return 0.0
        return sum(1 for t in self.trials if t.answered is None) / len(self.trials)

    @property
    def retrieval_hit(self) -> float:
        relevant = [t for t in self.trials if t.arm != "no_memory"]
        if not relevant:
            return float("nan")
        return sum(1.0 for t in relevant if t.retrieved_right_one) / len(relevant)

    @property
    def seconds(self) -> float:
        return stats.mean([t.seconds for t in self.trials])


def faults(n: int) -> list[str]:
    return [f"E{index:02d}" for index in range(1, n + 1)]


def build_store(
    arm: str,
    fault_codes: Sequence[str],
    truth: dict[str, str],
    embedder: OllamaEmbedder,
    rng: random.Random,
    tested: str,
) -> tuple[MemoryFabric, set[str]]:
    """A store holding exactly what this arm is meant to expose.

    Every arm but `no_memory` holds a claim for *every* fault code, so the model
    only sees the right one if retrieval actually finds it among the rest. That
    makes this a test of the retrieval path too, not just of the prompt.
    """
    fabric = MemoryFabric(auto_activate=True, seed=0, embedder=embedder)
    right_ids: set[str] = set()
    if arm == "no_memory":
        return fabric, right_ids

    for code in fault_codes:
        if code == tested:
            if arm == "correct":
                action = truth[code]
            elif arm == "wrong":
                action = rng.choice([a for a in ACTIONS if a != truth[code]])
            else:  # contested: the right claim, plus a rival added below
                action = truth[code]
        else:
            action = truth[code]
        memory_id = fabric.remember(
            "depot-engineer",
            f"When fault code {code} appears on a depot charger, "
            f"the correct response is {action}.",
            context={"fault": code},
        )
        if code == tested:
            right_ids.add(memory_id)

    if arm == "contested":
        rival_action = rng.choice([a for a in ACTIONS if a != truth[tested]])
        rival = fabric.remember(
            "night-shift",
            f"When fault code {tested} appears on a depot charger, "
            f"the correct response is {rival_action}.",
            context={"fault": tested},
        )
        right_ids.add(rival)
        fabric.challenge(
            sorted(right_ids),
            evidence="two shifts disagree about this fault code",
            detector_id="manual",
        )
    return fabric, right_ids


def ask(fault: str) -> str:
    options = "\n".join(f"  - {a}" for a in ACTIONS)
    return (
        f"A depot charger is reporting fault code {fault}.\n\n"
        f"Choose the correct response from this list:\n{options}\n\n"
        "Reply with the response name only, exactly as written above."
    )


def parse(text: str) -> str | None:
    lowered = (text or "").lower()
    hits = [action for action in ACTIONS if action in lowered]
    # Several named means the model listed options rather than choosing.
    return hits[0] if len(hits) == 1 else None


def run_arm(
    arm: str,
    model: str,
    fault_codes: Sequence[str],
    truth: dict[str, str],
    tested_codes: Sequence[str],
    client: OllamaClient,
    embedder: OllamaEmbedder,
    seed: int,
) -> ArmStats:
    out = ArmStats(arm=arm)
    for index, fault in enumerate(tested_codes):
        rng = random.Random(seed * 1000 + index)
        fabric, right_ids = build_store(arm, fault_codes, truth, embedder, rng, fault)
        try:
            agent = OllamaMemoryAgent(
                fabric, "depot-agent", model=model, client=client,
                recall_k=2, allow_remember=False,
            )
            started = time.perf_counter()
            run = agent.run(
                task_id=f"{arm}-{fault}",
                prompt=ask(fault),
                context={"fault": fault},
                recall=arm != "no_memory",
                include_contested=(arm == "contested"),
            )
            elapsed = time.perf_counter() - started
            answered = parse(run.text)
            out.trials.append(
                Trial(
                    arm=arm,
                    fault=fault,
                    expected=truth[fault],
                    answered=answered,
                    correct=answered == truth[fault],
                    retrieved=len(run.recalled),
                    retrieved_right_one=bool(right_ids & set(run.recalled)),
                    seconds=elapsed,
                )
            )
        finally:
            fabric.close()
    return out


def main(argv: Sequence[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="Live Ollama run against the fabric")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--models", nargs="*", default=list(DEFAULT_MODELS))
    parser.add_argument("--trials", type=int, default=20)
    args = parser.parse_args(argv)

    trials = 6 if args.quick else args.trials
    client = OllamaClient()
    try:
        available = client.available()
    except OllamaError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    resolved = {m: OllamaClient.resolve(m, available) for m in args.models}
    models = [r for r in resolved.values() if r]
    missing = [m for m, r in resolved.items() if not r]
    if missing:
        print(f"skipping models not installed: {', '.join(missing)}")
    if not models:
        print("none of the requested models are installed", file=sys.stderr)
        return 2

    rng = random.Random(0)
    codes = faults(20)
    truth = {code: rng.choice(ACTIONS) for code in codes}
    tested = codes[:trials]

    embedder = OllamaEmbedder(client)
    print("Live Ollama run - does the fabric change a real model's answers?")
    print(f"models={models}  trials={trials}  chance={1/len(ACTIONS):.1%}")
    print("warming the embedder over the whole corpus...")
    # The index embeds content *plus* context (MemoryFabric._index_text), so
    # warming the raw content alone misses the cache on every single store
    # build — at ~1.2s each, that is the whole runtime.
    corpus = [
        f"When fault code {c} appears on a depot charger, "
        f"the correct response is {a}. fault {c}"
        for c in codes for a in ACTIONS
    ] + [ask(c) for c in codes]
    started = time.perf_counter()
    embedder.warm(corpus)
    print(f"  {len(corpus)} texts in {time.perf_counter()-started:.1f}s "
          f"({embedder.calls} request(s))")

    # Guard: if the warm corpus and the index text ever drift apart again, the
    # run silently falls back to a live embed per store build and takes hours.
    warm_calls = embedder.calls
    probe = MemoryFabric(auto_activate=True, seed=0, embedder=embedder)
    probe.remember("probe", 
        f"When fault code {codes[0]} appears on a depot charger, "
        f"the correct response is {truth[codes[0]]}.", context={"fault": codes[0]})
    probe.close()
    if embedder.calls != warm_calls:
        print("  WARNING: warm corpus does not match the index text; every store "
              "build will embed live (~1.2s each)", file=sys.stderr)
    else:
        print("  cache verified: store builds will not embed live")

    results: dict[tuple[str, str], ArmStats] = {}
    for model in models:
        print(f"\n--- {model} ---")
        try:
            for arm in ARMS:
                started = time.perf_counter()
                cell = run_arm(arm, model, codes, truth, tested, client, embedder, seed=1)
                results[(model, arm)] = cell
                print(f"  {arm:<10} acc={stats.mean(cell.accuracy):5.1%}  "
                      f"({time.perf_counter()-started:.0f}s)", flush=True)
        except OllamaError as exc:
            # One unreachable model must not discard the models that worked.
            print(f"  SKIPPED - {exc}", flush=True)
            for arm in ARMS:
                results.pop((model, arm), None)
            continue

    print(f"\n{'model':<14} {'arm':<10} {'accuracy':>20} {'unparsed':>9} "
          f"{'retrieval':>10} {'s/call':>7}")
    print("-" * 76)
    done = [m for m in models if all((m, a) in results for a in ARMS)]
    for model in done:
        for arm in ARMS:
            cell = results[(model, arm)]
            hit = cell.retrieval_hit
            print(
                f"{model:<14} {arm:<10} {stats.fmt_ci(cell.accuracy):>20} "
                f"{cell.unparsed:>8.0%} "
                f"{('—' if hit != hit else f'{hit:.0%}'):>10} {cell.seconds:>7.2f}"
            )

    print("\n=== What this calibrates ===")
    for model in models:
        correct = stats.mean(results[(model, 'correct')].accuracy)
        base = stats.mean(results[(model, 'no_memory')].accuracy)
        wrong = stats.mean(results[(model, 'wrong')].accuracy)
        contested = stats.mean(results[(model, 'contested')].accuracy)
        print(f"\n{model}")
        print(f"  compliance (follows a correct memory): {correct:.1%}")
        print(f"  lift over no memory:                   {correct - base:+.1%}")
        print(f"  misled by a wrong memory:              {1.0 - wrong:.1%} of the time")
        print(f"  contested vs wrong:                    {contested - wrong:+.1%}")
    print(f"\nRuleWorld assumed compliance = 0.80 (experiments/ruleworld.py).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
