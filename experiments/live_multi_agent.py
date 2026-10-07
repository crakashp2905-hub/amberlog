"""Multiple agents, different models, genuine disagreement.

H4b is this project's strongest result: preserving contested hypotheses rather
than collapsing to the majority took P(correct) from 0.905 to 1.000 in
simulation. It has never been tested with real agents producing real conflict,
and the earlier live runs did not test it either — they used several agent
*identities* but a single model, in a scripted sequence.

This sets up the premature-consensus trap with real models:

    three observer agents, each on a different model, each given a different
    piece of evidence about the same fault. Two are fed the wrong lead and one
    the right one, so the **majority is wrong** — which is exactly the case a
    "collapse to consensus" policy gets wrong and a "preserve the disagreement"
    policy is supposed to survive.

Each observer writes its own memory, in its own words, into its own store. All
of them federate into a consolidator. Then a reader agent answers the question
under two arms:

    collapse  only the majority memory is active
    preserve  all of them are active and marked contested by the fabric

The question is not whether the reader magically picks the minority. It is
whether it *stops being confidently wrong*. A reader that flags the conflict
and asks for verification has behaved correctly even if it names no action.

    python -m experiments.live_multi_agent
    python -m experiments.live_multi_agent --quick
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Sequence

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.adapters.ollama import (
    OllamaClient,
    OllamaEmbedder,
    OllamaError,
    OllamaMemoryAgent,
)
from memory_fabric.cli import configure_output
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)

from . import stats

ACTIONS = [
    "reseat_contactor",
    "replace_rcd",
    "reflash_firmware",
    "clean_earth_bond",
    "swap_pilot_cable",
    "recalibrate_meter",
]

OBSERVER_MODELS = ("qwen2.5:3b", "llama3.2:3b", "qwen2.5:7b")
READER_MODEL = "qwen2.5:3b"
ARMS = ("collapse", "preserve")

HEDGE = re.compile(
    r"\b(conflict|disagree|contradic|uncertain|unclear|ambiguous|verify|confirm|"
    r"inconsisten|both|however|cannot determine|not sure|insufficient)\w*",
    re.IGNORECASE,
)


def federating_firewall() -> Firewall:
    return Firewall(
        rules=(rule_restricted_stays_private, rule_must_be_active,
               rule_capabilities_must_be_granted)
    )


@dataclass
class Trial:
    arm: str
    fault: str
    truth: str
    majority: str
    answered: str | None
    hedged: bool
    confidently_wrong: bool
    text: str
    memories: int
    observers_usable: int = 0


@dataclass
class ArmStats:
    arm: str
    trials: list[Trial] = field(default_factory=list)

    @property
    def confidently_wrong(self) -> list[float]:
        return [1.0 if t.confidently_wrong else 0.0 for t in self.trials]

    @property
    def hedged(self) -> list[float]:
        return [1.0 if t.hedged else 0.0 for t in self.trials]

    @property
    def correct(self) -> list[float]:
        return [1.0 if t.answered == t.truth else 0.0 for t in self.trials]

    @property
    def followed_majority(self) -> list[float]:
        return [1.0 if t.answered == t.majority else 0.0 for t in self.trials]


def observe_prompt(fault: str, lead: str, action: str) -> str:
    """Make the observer name a canonical action.

    The first run let observers describe the fix in their own words — "requires
    replacement of faulty conductor" — while the reader had to choose from a
    fixed list of action names. The memories therefore named none of the
    options, and both arms scored 0% correct: the reader was being asked a
    question its own memories could not answer. Naming the action connects the
    written memory to the answer space.
    """
    return (
        f"You inspected a depot charger reporting fault code {fault}. "
        f"Your inspection found: {lead}.\n\n"
        f"The response this calls for is: {action}\n\n"
        "Record the durable lesson for future incidents, in one sentence. "
        f"Your sentence must contain the fault code {fault} and the exact "
        f"response name {action}."
    )


LEADS = {
    "reseat_contactor": "the contactor had worked loose in its housing",
    "replace_rcd": "the residual current device had failed closed",
    "reflash_firmware": "the controller firmware had a corrupted checksum",
    "clean_earth_bond": "the earth bond was damp and corroded",
    "swap_pilot_cable": "the pilot cable had a broken conductor",
    "recalibrate_meter": "the energy meter was reading 12% high",
}


def ask(fault: str) -> str:
    options = "\n".join(f"  - {a}" for a in ACTIONS)
    return (
        f"A depot charger is reporting fault code {fault}.\n\n"
        f"Possible responses:\n{options}\n\n"
        "What is the correct response? If the evidence you have is in conflict "
        "or insufficient, say so plainly instead of guessing."
    )


def parse(text: str) -> str | None:
    """Find the single action a reply commits to.

    Matches the prose form as well as the token: a model asked about
    `swap_pilot_cable` answers "swap the pilot cable", and scoring only the
    token form records a confidently wrong answer as no answer at all — which
    biases *against* the collapse arm being seen as wrong.

    Still requires exactly one distinct action: naming several is listing
    options, not committing.
    """
    # Everything becomes single-spaced words, so `swap_pilot_cable` and
    # "swap the pilot cable" reduce to the same shape.
    normalised = " " + " ".join(re.findall(r"[a-z0-9]+", (text or "").lower())) + " "
    hits: list[str] = []
    for action in ACTIONS:
        words = action.split("_")
        # Allow up to two filler words between parts ("swap *the* pilot cable").
        gap = r"(?: \w+){0,2} "
        pattern = " " + gap.join(map(re.escape, words))
        if re.search(pattern, normalised):
            hits.append(action)
    return hits[0] if len(hits) == 1 else None


def run_trial(
    fault: str,
    truth: str,
    wrong: str,
    arm: str,
    observer_models: Sequence[str],
    reader_model: str,
    client: OllamaClient,
    embedder: OllamaEmbedder,
    shared_memories: list[tuple[str, str]] | None,
) -> tuple[Trial, list[tuple[str, str]]]:
    """One trial. `shared_memories` lets the two arms reuse the same observer
    output, so the arms differ only in what the consolidator keeps active."""
    consolidator = MemoryFabric(seed=7, embedder=embedder, firewall=federating_firewall())
    try:
        if shared_memories is None:
            # Two observers get the wrong lead, one gets the right one.
            leads = [wrong, wrong, truth]
            shared_memories = []
            for model, lead in zip(observer_models, leads):
                store = MemoryFabric(
                    seed=1, embedder=embedder, firewall=federating_firewall()
                )
                try:
                    agent = OllamaMemoryAgent(
                        store, f"observer-{model}", model=model, client=client,
                        allow_remember=True,
                    )
                    run = agent.run(
                        task_id=f"inspect-{fault}-{model}",
                        prompt=observe_prompt(fault, LEADS[lead], lead),
                        context={"fault": fault},
                        recall=False,
                    )
                    # Keep only memories that name the action; duplicate
                    # suppression in the fabric already collapses tool loops.
                    for mid in dict.fromkeys(run.remembered):
                        content = store.get(mid).content
                        if parse(content) == lead:
                            shared_memories.append((lead, content))
                            break
                finally:
                    store.close()

        imported: list[tuple[str, str]] = []
        for lead, content in shared_memories:
            source = MemoryFabric(seed=2, embedder=embedder,
                                  firewall=federating_firewall())
            try:
                mid = source.remember(
                    f"observer-{lead}", content, context={"fault": fault}
                )
                source.validate(mid, actor="observer")
                result = offer(source, mid, consolidator,
                               recipient_agent="consolidator")
                if result.accepted:
                    imported.append((lead, result.imported_memory_id))
            finally:
                source.close()

        majority_ids = [mid for lead, mid in imported if lead == wrong]
        minority_ids = [mid for lead, mid in imported if lead == truth]

        if arm == "collapse":
            # The majority wins and the dissent is dropped, which is what a
            # consensus-collapsing store does.
            for mid in majority_ids:
                consolidator.validate(mid, actor="consolidator")
            for mid in minority_ids:
                consolidator.forget(mid, reason="minority view discarded",
                                    actor="consolidator")
        else:
            for _, mid in imported:
                consolidator.validate(mid, actor="consolidator")
            if majority_ids and minority_ids:
                consolidator.challenge(
                    [mid for _, mid in imported],
                    evidence="observers disagree about this fault code",
                    detector_id="consolidation",
                )

        reader = OllamaMemoryAgent(
            consolidator, "reader", model=reader_model, client=client,
            recall_k=3, allow_remember=False,
        )
        run = reader.run(
            task_id=f"decide-{fault}-{arm}",
            prompt=ask(fault),
            context={"fault": fault},
            include_contested=(arm == "preserve"),
        )
        answered = parse(run.text)
        hedged = bool(HEDGE.search(run.text))
        trial = Trial(
            arm=arm,
            fault=fault,
            truth=truth,
            majority=wrong,
            answered=answered,
            hedged=hedged,
            # The failure that matters: naming the wrong action with no caveat.
            confidently_wrong=(answered == wrong and not hedged),
            text=run.text,
            memories=len(run.recalled),
        )
        return trial, shared_memories
    finally:
        consolidator.close()


def generate_observations(
    faults: Sequence[str],
    truths: dict[str, str],
    wrongs: dict[str, str],
    observer_models: Sequence[str],
    client: OllamaClient,
    embedder: OllamaEmbedder,
) -> dict[str, list[tuple[str, str]]]:
    """Write every observer memory up front, grouped by model.

    Interleaving models costs a cold load on every switch — 20-30s each, and
    the first version paid it three times per trial. Doing all of one model's
    work before moving on loads each model once for the whole run.
    """
    by_fault: dict[str, list[tuple[str, str]]] = {f: [] for f in faults}
    for position, model in enumerate(observer_models):
        started = time.perf_counter()
        produced = 0
        for fault in faults:
            # Observers 0 and 1 get the wrong lead, observer 2 the right one.
            lead = truths[fault] if position == 2 else wrongs[fault]
            store = MemoryFabric(seed=1, embedder=embedder,
                                 firewall=federating_firewall())
            try:
                agent = OllamaMemoryAgent(
                    store, f"observer-{model}", model=model, client=client,
                    allow_remember=True,
                )
                run = agent.run(
                    task_id=f"inspect-{fault}-{model}",
                    prompt=observe_prompt(fault, LEADS[lead], lead),
                    context={"fault": fault},
                    recall=False,
                )
                for mid in dict.fromkeys(run.remembered):
                    content = store.get(mid).content
                    if parse(content) == lead:
                        by_fault[fault].append((lead, content))
                        produced += 1
                        break
            finally:
                store.close()
        print(f"  {model:<14} {produced}/{len(faults)} usable "
              f"({time.perf_counter()-started:.0f}s)", flush=True)
    return by_fault


def main(argv: Sequence[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="Multi-agent disagreement, live")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--trials", type=int, default=10)
    args = parser.parse_args(argv)

    trials = 3 if args.quick else args.trials
    client = OllamaClient()
    try:
        available = client.available()
    except OllamaError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    observers = [m for m in (OllamaClient.resolve(m, available) for m in OBSERVER_MODELS) if m]
    reader = OllamaClient.resolve(READER_MODEL, available)
    if len(observers) < 2 or not reader:
        print("need at least two observer models and a reader", file=sys.stderr)
        return 2

    print("Multi-agent disagreement, live")
    print(f"observers={observers}")
    print(f"reader={reader}  trials={trials}")
    print("two observers get the wrong lead, one gets the right one -> "
          "the majority is wrong\n")

    rng = random.Random(0)
    faults = [f"E{i:02d}" for i in range(31, 31 + trials)]
    embedder = OllamaEmbedder(client)

    truths = {f: ACTIONS[i % len(ACTIONS)] for i, f in enumerate(faults)}
    wrongs = {f: rng.choice([a for a in ACTIONS if a != truths[f]]) for f in faults}

    print("writing observer memories (one model at a time)...")
    observations = generate_observations(
        faults, truths, wrongs, observers, client, embedder
    )
    print()

    results: dict[str, ArmStats] = {arm: ArmStats(arm) for arm in ARMS}
    for index, fault in enumerate(faults):
        truth, wrong = truths[fault], wrongs[fault]
        shared = observations[fault]
        if not any(lead == truth for lead, _ in shared) or not any(
            lead == wrong for lead, _ in shared
        ):
            print(f"  {fault} skipped - observers did not produce both sides")
            continue
        for arm in ARMS:
            started = time.perf_counter()
            trial, shared = run_trial(
                fault, truth, wrong, arm, observers, reader, client, embedder, shared
            )
            results[arm].trials.append(trial)
            flag = "CONF-WRONG" if trial.confidently_wrong else (
                "hedged" if trial.hedged else "ok")
            print(f"  {fault} {arm:<9} answered={str(trial.answered):<18} "
                  f"{flag:<11} ({time.perf_counter()-started:.0f}s)", flush=True)

    print(f"\n{'arm':<10} {'confidently wrong':>26} {'hedged':>22} "
          f"{'followed majority':>20} {'correct':>10}")
    print("-" * 92)
    for arm in ARMS:
        cell = results[arm]
        print(f"{arm:<10} {stats.fmt_ci(cell.confidently_wrong):>26} "
              f"{stats.fmt_ci(cell.hedged):>22} "
              f"{stats.mean(cell.followed_majority):>19.0%} "
              f"{stats.mean(cell.correct):>9.0%}")

    collapse, preserve = results["collapse"], results["preserve"]
    diffs = [p - c for p, c in zip(preserve.confidently_wrong, collapse.confidently_wrong)]
    low, high = stats.bootstrap_ci(diffs)
    print("\n=== Does preserving the disagreement stop confident error? ===")
    print(f"  collapse: confidently wrong {stats.mean(collapse.confidently_wrong):.0%}")
    print(f"  preserve: confidently wrong {stats.mean(preserve.confidently_wrong):.0%}")
    print(f"  difference {stats.mean(diffs):+.2f} [{low:+.2f}, {high:+.2f}] "
          "(negative = preserving helps)")

    print("\n=== A reader's words under each arm ===")
    for arm in ARMS:
        sample = results[arm].trials[0]
        print(f"\n  [{arm}] {sample.text[:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
