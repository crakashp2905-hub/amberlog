"""Is "nothing asserts anything about the subject" even the right question?

`research/prereg/x1-extraction-at-ingest.md` prediction 3 says the abstention
candidate will not work, and gives a reason rather than a hunch:

> *the LongMemEval abstention cases are **partially** answerable -- "you
> mentioned the fence but not the cows" -- so memories asserting things about
> the subject **do** exist, and "nothing asserts anything" is the wrong
> question.*

That reason is a claim about the **fixture**, not about a model, so it can be
checked without extracting anything. Which matters, because the extraction the
signal needs costs 54.5 s a statement on this hardware and LongMemEval's `s`
split holds hundreds of thousands of turns: the signal itself is unmeasurable
here, and its premise is not.

## What is measured

For each instance, the question is scored against every turn of its haystack
with the project's own `LexicalIndex`, and two things are recorded:

* **top-1 relevance** -- how much the single best turn looks like the question;
* **content-term coverage** -- the share of the question's distinctive
  (high-IDF, non-stopword) terms that the top-10 turns contain at all.

Then the **30 `_abs` instances are compared against answerable ones**. The
prediction is confirmed if the two distributions overlap: an unanswerable
question whose haystack contains turns about its subject cannot be detected by
asking whether anything in the context is about the subject.

This is **not** the registered abstention metric and does not substitute for
it. It decides whether that metric was ever going to measure what it claimed.

## Sampling

Stratified, and for a reason this project has already paid for once: the
LongMemEval file is **sorted by question type**, so `data[:60]` returned 60
temporal-reasoning instances and nothing else -- a slicing artifact that looked
like a result until the full-population number contradicted it
(`research/results/abstention-signals.md`). Every `_abs` instance is taken,
because there are only 30; the answerable comparison group is drawn round-robin
over the question types.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import longmemeval_bench as lb  # noqa: E402
from memory_fabric.vectors import LexicalIndex  # noqa: E402


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


@dataclass
class Scored:
    question_id: str
    question_type: str
    is_abstention: bool
    turns: int
    top1: float
    coverage: float
    mean_top10: float = 0.0
    """`abstention-signals.md`'s own signal, reproduced here to check it.

    That result reports **AUC 0.319** for the mean of the top 10 retrieval
    scores -- *below* chance, "with the effect reversed" -- and, two paragraphs
    earlier, a best operating point of **TPR 0.53 at FPR 0.23**. Those cannot
    both be true: a point above the ROC diagonal does not come from a signal
    below chance. It also names no harness file, so the number cannot be
    re-derived by reading it. Recomputed here, same split, same population.
    """


def content_terms(text: str) -> list[str]:
    """The question's distinctive terms.

    The product's own tokeniser, which already strips its stopword list. Reused
    rather than reimplemented: a second stopword list written here would be a
    tunable, and the one thing this measurement must not have is a knob that
    could be set differently for the two groups.
    """
    return [t for t in LexicalIndex._tokens(text) if len(t) > 1]


def turns_of(instance: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for session in instance.get("haystack_sessions") or ():
        for turn in session or ():
            if isinstance(turn, Mapping):
                text = turn.get("content") or ""
            else:
                text = str(turn)
            if text.strip():
                out.append(text)
    return out


def score(instance: Mapping[str, Any], k: int = 10) -> Scored:
    texts = turns_of(instance)
    question = instance["question"]
    index = LexicalIndex()
    for position, text in enumerate(texts):
        index.add(str(position), text)
    ranked = index.search(question, k=k)
    top1 = ranked[0][1] if ranked else 0.0
    mean_top10 = (statistics.mean(score for _id, score in ranked[:10])
                  if ranked else 0.0)

    wanted = set(content_terms(question))
    seen: set[str] = set()
    for memory_id, _score in ranked:
        seen |= set(LexicalIndex._tokens(texts[int(memory_id)]))
    coverage = len(wanted & seen) / len(wanted) if wanted else 0.0

    return Scored(
        question_id=instance["question_id"],
        question_type=instance["question_type"],
        is_abstention=instance["question_id"].endswith("_abs"),
        turns=len(texts),
        top1=round(top1, 4),
        coverage=round(coverage, 4),
        mean_top10=round(mean_top10, 4),
    )


def sample(split: str, answerable: int) -> list[Mapping[str, Any]]:
    data = lb.load(split)
    abstention = [i for i in data if i["question_id"].endswith("_abs")]
    groups: dict[str, list] = defaultdict(list)
    for instance in data:
        if not instance["question_id"].endswith("_abs"):
            groups[instance["question_type"]].append(instance)
    order = sorted(groups)
    chosen: list[Mapping[str, Any]] = []
    position = 0
    while len(chosen) < answerable and any(
            position < len(groups[name]) for name in order):
        for name in order:
            if position < len(groups[name]) and len(chosen) < answerable:
                chosen.append(groups[name][position])
        position += 1
    return abstention + chosen


def best_f1(positive: Sequence[float], negative: Sequence[float]
            ) -> dict[str, Any]:
    """The best a single global threshold can do, abstaining on LOW scores.

    Reported because it is the number `abstention-signals.md` gives (F1 0.206,
    TPR 0.53, FPR 0.23) and because it is in the units a product decision is
    made in. `positive` is the unanswerable group, which is the class a
    detector would try to catch.
    """
    best: dict[str, Any] = {"f1": 0.0}
    for threshold in sorted(set(list(positive) + list(negative))):
        caught = sum(1 for p in positive if p <= threshold)
        wrong = sum(1 for n in negative if n <= threshold)
        if caught + wrong == 0:
            continue
        precision = caught / (caught + wrong)
        recall = caught / len(positive)
        if precision + recall == 0:
            continue
        f1 = 2 * precision * recall / (precision + recall)
        if f1 > best["f1"]:
            best = {
                "f1": round(f1, 4), "threshold": round(threshold, 4),
                "precision": round(precision, 4),
                "recall_tpr": round(recall, 4),
                "fpr": round(wrong / len(negative), 4),
            }
    return best


def auc(positive: Sequence[float], negative: Sequence[float]) -> float | None:
    """Probability a random `_abs` instance scores below a random answerable
    one -- the Mann-Whitney statistic, ties counted as half.

    Reported **beside** Cohen's d and trusted over it, because this project has
    already been fooled by exactly the pair of numbers below: a signal with
    d=0.68 on a sample turned out to have AUC 0.319 on the full population, and
    the d was a slicing artifact (`research/results/abstention-signals.md`). A
    standardised mean difference says the centres differ; only AUC says whether
    a threshold could separate the two groups. 0.5 is a coin flip.
    """
    if not positive or not negative:
        return None
    wins = sum((1.0 if n > p else 0.5 if n == p else 0.0)
               for p in positive for n in negative)
    return wins / (len(positive) * len(negative))


def cohens_d(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Standardised difference, so "the distributions overlap" is a number.

    None when either group has fewer than two values or no variance: an effect
    size computed from a constant is a division by zero dressed as a finding.
    """
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = statistics.variance(a), statistics.variance(b)
    pooled = ((len(a) - 1) * va + (len(b) - 1) * vb) / (len(a) + len(b) - 2)
    if pooled <= 0:
        return None
    return (statistics.mean(a) - statistics.mean(b)) / math.sqrt(pooled)


def run(split: str = "s", answerable: int = 30, k: int = 10) -> dict[str, Any]:
    rows = [score(instance, k) for instance in sample(split, answerable)]
    absent = [r for r in rows if r.is_abstention]
    present = [r for r in rows if not r.is_abstention]

    def describe(group: Sequence[Scored]) -> dict[str, Any]:
        if not group:
            return {}
        top1 = [r.top1 for r in group]
        cover = [r.coverage for r in group]
        return {
            "n": len(group),
            "turns_median": statistics.median(r.turns for r in group),
            "top1_mean": round(statistics.mean(top1), 4),
            "top1_median": round(statistics.median(top1), 4),
            "coverage_mean": round(statistics.mean(cover), 4),
            "coverage_median": round(statistics.median(cover), 4),
            "mean_top10_mean": round(
                statistics.mean(r.mean_top10 for r in group), 4),
        }

    return {
        "experiment": "x1-abstention-premise",
        "split": split, "k": k,
        "abstention": describe(absent),
        "answerable": describe(present),
        "effect_size_d": {
            "top1": _round(cohens_d([r.top1 for r in absent],
                                    [r.top1 for r in present])),
            "coverage": _round(cohens_d([r.coverage for r in absent],
                                        [r.coverage for r in present])),
        },
        "auc": {
            "top1": _round(auc([r.top1 for r in absent],
                               [r.top1 for r in present])),
            "coverage": _round(auc([r.coverage for r in absent],
                                   [r.coverage for r in present])),
            "mean_top10": _round(auc([r.mean_top10 for r in absent],
                                     [r.mean_top10 for r in present])),
        },
        "best_f1": {
            name: best_f1([getattr(r, name) for r in absent],
                          [getattr(r, name) for r in present])
            for name in ("top1", "coverage", "mean_top10")
        },
        "rows": [r.__dict__ for r in rows],
    }


def to_markdown(result: Mapping[str, Any]) -> str:
    absent, present = result["abstention"], result["answerable"]
    d = result["effect_size_d"]
    lines = [
        f"# X1 — is the abstention question the right question? · "
        f"`{result['split']}` split",
        "",
        "| group | n | median turns | top-1 relevance (mean) | "
        "content-term coverage (mean) |",
        "|---|---|---|---|---|",
    ]
    for name, row in (("unanswerable (`_abs`)", absent),
                      ("answerable", present)):
        if row:
            lines.append(
                f"| {name} | {row['n']} | {row['turns_median']:.0f} | "
                f"{row['top1_mean']:.4f} | {row['coverage_mean']:.4f} |")
    lines += [
        "",
        "| signal | AUC | best F1 | TPR | FPR |",
        "|---|---|---|---|---|",
    ]
    for name in ("top1", "coverage", "mean_top10"):
        f = result["best_f1"][name]
        lines.append(
            f"| `{name}` | {result['auc'][name]} | {f.get('f1')} | "
            f"{f.get('recall_tpr')} | {f.get('fpr')} |")
    a = result["auc"]
    lines += [
        "",
        f"Cohen's d, unanswerable minus answerable: "
        f"**top-1 {d['top1']}**, **coverage {d['coverage']}**.",
        f"AUC — can a threshold separate them at all: "
        f"**top-1 {a['top1']}**, **coverage {a['coverage']}** (0.5 is a coin "
        f"flip). Trusted over d; see `auc()`.",
        "",
        "An unanswerable question whose haystack contains turns about its "
        "subject cannot be detected by asking whether anything in the context "
        "is about the subject. Overlapping distributions confirm prediction 3 "
        "of the registration, and do so without extracting anything.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="s", choices=sorted(lb.SPLITS))
    parser.add_argument("--answerable", type=int, default=30)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.split, args.answerable, args.k)
    print(json.dumps(result, indent=2) if args.as_json
          else to_markdown(result))
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
