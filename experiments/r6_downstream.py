"""R6 — does better retrieval change what a real model answers?

Every number in R1–R5 is a retrieval metric. nDCG is not task success, and this
project has been caught by that gap before: Phase A measured governed memory
*losing* to an ungoverned vector store by 34 points, and the mechanism was that
success tracked one thing — whether a correct memory reached the prompt — at
93–98% conversion in every arm.

Registered in `research/prereg/r6-downstream-retrieval.md` **before this ran**,
including the arms, the thresholds as a share of measured headroom, the seeds,
and three predictions recorded in order to be wrong.

Grading is a declared substring key per case, not a model judging a model.
PA′'s first analyser scored every withdrawal rule "100% justified" because it
compared actions without comparing faults; an LLM judge here would be the same
error with more steps. Cases whose correct answer is "both, unresolved" get no
key and are not graded on correctness — inventing one to widen coverage is how
a benchmark comes to measure the wrong thing.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments.relevance_bench import (  # noqa: E402
    ARMS,
    apply_gates,
    arm_oracle,
    load,
)
from experiments.stats import bootstrap_ci, report_ceiling  # noqa: E402

DEFAULT_MODEL = "qwen2.5:7b"
CEILING = "oracle_memory"

SYSTEM = (
    "You answer from the supplied memories only. If they do not contain the "
    "answer, say you cannot tell from the available information. Be brief: one "
    "or two sentences."
)


def _client_and_model(model: str):
    from amberlog.adapters.ollama import OllamaClient

    client = OllamaClient()
    resolved = client.resolve(model, client.available())
    if resolved is None:
        raise RuntimeError(f"{model} is not installed; `ollama pull {model}`")
    return client, resolved


# --- the arms ---------------------------------------------------------------
#
# Each returns the memory ids that will go into the prompt, already gated. The
# gate runs on every arm including the oracle, so no arm can win by exposing
# something it must not.


def _gated(case: Mapping[str, Any], ranked: Sequence[str], k: int) -> list[str]:
    allowed, _refused = apply_gates(case, ranked)
    return allowed[:k]


def arm_no_memory(case: Mapping[str, Any], k: int) -> list[str]:
    """The floor, and the only arm that can show memory actively hurting."""
    return []


def arm_all_memory(case: Mapping[str, Any], k: int) -> list[str]:
    """Everything, truncated to the budget.

    The "just give the model the corpus" baseline, and the arm that decides
    whether this benchmark needs retrieval at all. Prediction 1 in the
    registration is that it beats plain retrieval, because 18–20 memories is
    something a modern model simply reads — in which case the corpora are too
    small to need selection and the finding is about the benchmark.
    """
    return _gated(case, [m["id"] for m in case["corpus"]], len(case["corpus"]))


def _store_arm(name: str) -> Callable[[Mapping[str, Any], int], list[str]]:
    def arm(case: Mapping[str, Any], k: int) -> list[str]:
        return _gated(case, ARMS[name](case, k), k)

    return arm


def arm_oracle_memory(case: Mapping[str, Any], k: int) -> list[str]:
    """The labelled relevant set — same budget, same `k`, same gates.

    It does not reach 100%: on `unauthorized` and `retracted` cases the gate
    removes memories the labels call relevant, which is correct and is headroom
    no retriever may take (principle 8b).
    """
    return _gated(case, arm_oracle(case, k), k)


ARM_FUNCTIONS: dict[str, Callable[[Mapping[str, Any], int], list[str]]] = {
    "no_memory": arm_no_memory,
    "all_memory": arm_all_memory,
    "store_plain": _store_arm("store_plain"),
    "store_all": _store_arm("store_all"),
    CEILING: arm_oracle_memory,
}


# --- prompting and grading --------------------------------------------------


def build_prompt(
    case: Mapping[str, Any], memory_ids: Sequence[str], rng: random.Random
) -> str:
    by_id = {m["id"]: m for m in case["corpus"]}
    chosen = list(memory_ids)
    # Shuffled per seed: a model that favours the first item would otherwise
    # flatter whichever arm happens to rank well, and that is a property of the
    # model's position bias rather than of the retrieval.
    rng.shuffle(chosen)
    task = case["task"]
    lines = ["Memories:"]
    if chosen:
        for memory_id in chosen:
            lines.append(f"- {by_id[memory_id]['content']}")
    else:
        lines.append("- (none)")
    lines.append("")
    if task.get("constraints"):
        lines.append("Constraints: " + "; ".join(task["constraints"]))
    lines.append(f"Question: {task['task_text']}")
    return "\n".join(lines)


ABSTENTION_MARKERS = (
    "cannot tell", "can't tell", "cannot determine", "not enough",
    "no information", "do not have", "don't have", "unable to",
    "not specified", "not available", "insufficient",
)


@dataclass
class CaseOutcome:
    case_id: str
    family: str
    arm: str
    seed: int
    exposed: tuple[str, ...]
    answer: str
    graded: bool
    correct: bool
    abstained: bool
    expect_abstain: bool
    critical_present: bool
    gate_violation: bool
    prompt_tokens: int


def grade(case: Mapping[str, Any], answer: str) -> tuple[bool, bool]:
    """`(graded, correct)`.

    Substring over declared alternatives, lower-cased. Crude on purpose: a
    rule a reader can check beats a judge whose agreement with the labels is
    itself unmeasured.
    """
    key = case["labels"].get("answer_contains")
    if not key:
        return (False, False)
    lowered = answer.lower()
    return (True, any(alternative.lower() in lowered for alternative in key))


def abstained(answer: str) -> bool:
    lowered = answer.lower()
    return any(marker in lowered for marker in ABSTENTION_MARKERS)


def run_arm(
    cases: Sequence[Mapping[str, Any]],
    arm: str,
    client: Any,
    model: str,
    seed: int,
    k: int,
) -> list[CaseOutcome]:
    rng = random.Random(seed)
    outcomes: list[CaseOutcome] = []
    for case in cases:
        exposed = ARM_FUNCTIONS[arm](case, k)
        prompt = build_prompt(case, exposed, rng)
        before = len(client.calls)
        result = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            num_predict=120,
        )
        answer = (result.get("message") or {}).get("content", "") or ""
        tokens = int(client.calls[before].prompt_tokens) if len(client.calls) > before else 0
        graded, correct = grade(case, answer)
        forbidden = set(case["labels"]["must_not_expose"])
        critical = set(case["labels"]["critical"])
        outcomes.append(
            CaseOutcome(
                case_id=case["case_id"],
                family=case["family"],
                arm=arm,
                seed=seed,
                exposed=tuple(exposed),
                answer=answer.strip()[:400],
                graded=graded,
                correct=correct,
                abstained=abstained(answer),
                expect_abstain=bool(case["labels"]["expect_abstain"]),
                critical_present=bool(critical) and critical <= set(exposed),
                gate_violation=bool(forbidden & set(exposed)),
                prompt_tokens=tokens,
            )
        )
    return outcomes


def summarise(outcomes: Sequence[CaseOutcome]) -> dict[str, Any]:
    graded = [o for o in outcomes if o.graded]
    unanswerable = [o for o in outcomes if o.expect_abstain]
    answerable = [o for o in outcomes if not o.expect_abstain]
    mean = lambda rows, attr: (  # noqa: E731
        sum(bool(getattr(r, attr)) for r in rows) / len(rows) if rows else 0.0
    )
    return {
        "graded_cases": len(graded),
        "correctness": round(mean(graded, "correct"), 4),
        "critical_present": round(mean(answerable, "critical_present"), 4),
        "abstention_precision": round(mean(unanswerable, "abstained"), 4),
        "false_abstention": round(mean(answerable, "abstained"), 4),
        "gate_violations": sum(1 for o in outcomes if o.gate_violation),
        "mean_prompt_tokens": round(
            sum(o.prompt_tokens for o in outcomes) / len(outcomes), 1
        ) if outcomes else 0.0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--arms", nargs="*", default=list(ARM_FUNCTIONS),
                        choices=list(ARM_FUNCTIONS))
    parser.add_argument("--out", help="write the raw outcomes here as JSON")
    args = parser.parse_args(argv)

    client, model = _client_and_model(args.model)
    cases = load(args.split)

    per_arm: dict[str, list[CaseOutcome]] = {arm: [] for arm in args.arms}
    per_seed: dict[str, list[float]] = {arm: [] for arm in args.arms}
    for seed in range(args.seeds):
        for arm in args.arms:
            outcomes = run_arm(cases, arm, client, model, seed, args.k)
            per_arm[arm].extend(outcomes)
            seed_summary = summarise(outcomes)
            per_seed[arm].append(seed_summary["correctness"])
            print(
                f"  seed {seed} {arm:14s} correct={seed_summary['correctness']:.3f} "
                f"crit={seed_summary['critical_present']:.3f} "
                f"viol={seed_summary['gate_violations']} "
                f"tok={seed_summary['mean_prompt_tokens']:.0f}",
                flush=True,
            )

    print()
    print(f"# R6 — {args.split}, model {model}, {args.seeds} seeds, k={args.k}")
    print(f"# {len(cases)} cases, "
          f"{sum(1 for c in cases if c['labels'].get('answer_contains'))} graded on correctness")
    print()
    print("| arm | correctness | 95% CI | critical present | gate violations | "
          "abstain precision | false abstain | prompt tokens |")
    print("|---|---|---|---|---|---|---|---|")
    summaries = {}
    for arm in args.arms:
        summary = summarise(per_arm[arm])
        summaries[arm] = summary
        low, high = bootstrap_ci(per_seed[arm], seed=0)
        print(
            f"| `{arm}` | {summary['correctness']:.3f} | "
            f"[{low:.3f}, {high:.3f}] | {summary['critical_present']:.3f} | "
            f"**{summary['gate_violations']}** | "
            f"{summary['abstention_precision']:.3f} | "
            f"{summary['false_abstention']:.3f} | "
            f"{summary['mean_prompt_tokens']:.0f} |"
        )

    print()
    scores = {a: s["correctness"] for a, s in summaries.items()}
    held = True
    if CEILING in scores:
        held = report_ceiling(scores, CEILING)
        baseline = max(
            (s for a, s in scores.items() if a in ("store_plain", "all_memory")),
            default=0.0,
        )
        headroom = scores[CEILING] - baseline
        print(f"  best simple arm: {baseline:.3f} · ceiling {scores[CEILING]:.3f} "
              f"· headroom {headroom:+.3f}")
        if headroom <= 0.05:
            print("  HEADROOM <= 0.05: the comparison is ABANDONED, not "
                  "reinterpreted (registration section 4).")

    violations = {a: s["gate_violations"] for a, s in summaries.items()
                  if s["gate_violations"]}
    if violations:
        print(f"\n  GATE VIOLATIONS, which fail the run regardless: {violations}")

    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(
                {
                    "split": args.split, "model": model, "seeds": args.seeds,
                    "k": args.k, "summaries": summaries,
                    "per_seed_correctness": per_seed,
                    "usage": client.usage(),
                    "outcomes": [vars(o) | {"exposed": list(o.exposed)}
                                 for arm in args.arms for o in per_arm[arm]],
                },
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
        print(f"\n  wrote {args.out}")

    return 0 if held and not violations else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
