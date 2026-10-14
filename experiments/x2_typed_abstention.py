"""X2 — can a typed decision model tell answerable from unanswerable?

Registered in `research/prereg/x2-typed-confidence.md`, written before the
model finished installing.

The retrieval stage carries an abstention signal that is real and far too weak
to act on: `research/results/abstention-signals.md` measures pooled AUC 0.682
with a best achievable F1 of **0.206**, and rejects the family on that
operating point rather than on its discrimination. Three of the four cheapest
hypotheses were eliminated outright.

A [System One](https://github.com/jaredpalmer/kev) model answers **typed**
questions and returns a probability over a closed option set. *"Can this
question be answered from this context?"* is one yes/no question, which makes
this the cheapest honest test of the idea that a calibrated probability is the
missing signal.

## The arms, and the one that must be re-measured

| arm | signal |
|---|---|
| `mean_top10` | mean of the top 10 retrieval scores — the registered baseline |
| `top1` | the best single retrieval score |
| `coverage` | share of the question's distinctive terms present in the top 10 |
| **`typed`** | **the mechanism**: P(answerable) from one `noul` question |
| `oracle` | knows the label; bounds everything at F1 1.0 |

**The three baselines are re-measured in this run, not quoted.** X1's
registration took its baseline from another document's table — a different
metric at a different budget — and the primary was invalid before any arm ran
([principle 8d](../../AGENTS.md)). Here every arm sees the same retrieval, the
same k and the same population, and the baseline numbers in the result come
from the same process that produced the mechanism's.

## What is reported, and why ECE is not optional

The reason to want this class of model is **calibration**, so the result
reports ECE and Brier beside F1. Kev's own model cards give Brier on sources it
never trained on — 0.481 for the 0.8B checkpoint, 0.269 for 4B — and this
project is a new source, so the comparison is direct.

Confidence on the **wrong** answers is reported separately from confidence
overall, because the failure mode to detect is *confident and wrong*: Kev's
sibling Laya is reported at 0 accuracy with 0.952 confidence on Khmer. An
average hides exactly that, and for a system whose measured value is
correctness under correction, a confidently wrong withholding decision is the
one failure that undoes the rest.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import checks as harness_checks  # noqa: E402
from experiments import x1_abstention_premise as premise  # noqa: E402
from memory_fabric.adapters.systemone import (  # noqa: E402
    SystemOneClient, brier_score, expected_calibration_error, noul,
)
from memory_fabric.vectors import LexicalIndex  # noqa: E402

QUESTION = (
    "The user asks the question below about their own past conversations. "
    "The numbered excerpts are everything that was retrieved from those "
    "conversations. Can the question be answered from these excerpts alone?"
)
YES = "the excerpts contain the specific fact the question asks for"
NO = ("the excerpts are about the right topic but do not contain the specific "
      "fact asked for, so the honest answer is that it was never mentioned")

BASELINES = ("mean_top10", "top1", "coverage")


@dataclass
class Row:
    question_id: str
    question_type: str
    unanswerable: bool
    top1: float
    mean_top10: float
    coverage: float
    p_answerable: float | None = None
    seconds: float = 0.0
    error: str | None = None

    def signal(self, arm: str) -> float:
        """Each arm's score, oriented so that **lower means unanswerable**.

        `typed` returns P(answerable), which already points that way, so no arm
        needs its sign flipped -- the mistake `abstention-signals.md` made when
        it reported an AUC as its own complement.
        """
        if arm == "typed":
            return float(self.p_answerable or 0.0)
        return float(getattr(self, arm))


def context_of(instance: Mapping[str, Any], k: int = 10
               ) -> tuple[list[str], float, float, float]:
    """The retrieved excerpts, and the three baseline signals over them.

    One retrieval, shared by every arm. Anything else would make the comparison
    partly about which arm got the better context.
    """
    texts = premise.turns_of(instance)
    question = instance["question"]
    index = LexicalIndex()
    for position, text in enumerate(texts):
        index.add(str(position), text)
    ranked = index.search(question, k=k)

    top1 = ranked[0][1] if ranked else 0.0
    mean_top10 = (statistics.mean(s for _i, s in ranked[:10])
                  if ranked else 0.0)
    wanted = set(premise.content_terms(question))
    seen: set[str] = set()
    for memory_id, _score in ranked:
        seen |= set(LexicalIndex._tokens(texts[int(memory_id)]))
    coverage = len(wanted & seen) / len(wanted) if wanted else 0.0

    excerpts = [texts[int(i)] for i, _s in ranked]
    return excerpts, top1, mean_top10, coverage


def ask(client: SystemOneClient, instance: Mapping[str, Any],
        excerpts: Sequence[str]) -> tuple[float | None, float, str | None]:
    state = {
        "question": instance["question"],
        "excerpts": [f"{n + 1}. {t}" for n, t in enumerate(excerpts)],
    }
    started = time.perf_counter()
    try:
        answers = client.ask(state, {"answerable": noul(QUESTION, YES, NO)})
    except Exception as exc:  # pragma: no cover - environment
        return None, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"[:90]
    return answers["answerable"].p_true, time.perf_counter() - started, None


# --- scoring -----------------------------------------------------------------


def best_f1(rows: Sequence[Row], arm: str) -> dict[str, Any]:
    """Best F1 over every threshold, abstaining when the signal is LOW.

    Chosen on this data, so an upper bound -- for every arm equally, which is
    what makes the comparison fair and the absolute number a ceiling.
    """
    positive = [r.signal(arm) for r in rows if r.unanswerable]
    negative = [r.signal(arm) for r in rows if not r.unanswerable]
    return premise.best_f1(positive, negative)


def auc_of(rows: Sequence[Row], arm: str) -> float | None:
    return premise.auc([r.signal(arm) for r in rows if r.unanswerable],
                       [r.signal(arm) for r in rows if not r.unanswerable])


def calibration(rows: Sequence[Row]) -> dict[str, Any]:
    """ECE, Brier, and confidence on the errors specifically.

    `typed` only: the baselines are retrieval scores, not probabilities, and
    calling a lexical score a probability would be the category error this
    whole experiment is testing the alternative to.
    """
    scored = [r for r in rows if r.p_answerable is not None]
    if not scored:
        return {}
    # Positive class = answerable, so the model's P(answerable) is compared
    # against whether the instance actually was.
    pairs = [(r.p_answerable, not r.unanswerable) for r in scored]
    decided = [(r, (r.p_answerable >= 0.5) == (not r.unanswerable))
               for r in scored]
    wrong = [r for r, ok in decided if not ok]

    def mean_conf(group: Sequence[Row]) -> float | None:
        if not group:
            return None
        # Distance from indifference: how sure it was, either way.
        return round(statistics.mean(
            abs(r.p_answerable - 0.5) * 2 for r in group), 4)

    return {
        "n": len(scored),
        "ece": round(expected_calibration_error(pairs) or 0.0, 4),
        "brier": round(brier_score(pairs) or 0.0, 4),
        "accuracy_at_half": round(
            sum(1 for _r, ok in decided if ok) / len(decided), 4),
        "mean_confidence_all": mean_conf(scored),
        "mean_confidence_on_errors": mean_conf(wrong),
        "errors": len(wrong),
        "mean_p_answerable_when_answerable": round(statistics.mean(
            [r.p_answerable for r in scored if not r.unanswerable]), 4),
        "mean_p_answerable_when_unanswerable": round(statistics.mean(
            [r.p_answerable for r in scored if r.unanswerable]), 4),
    }


def _stratified(instances: Sequence[Mapping[str, Any]],
                limit: int | None) -> set[str]:
    """Which instances the model scores, keeping both classes represented.

    A prefix will not do, and the reason is on the record. `premise.sample`
    returns the 30 unanswerable instances **first**, so `instances[:12]` is
    twelve unanswerable ones and no answerable ones -- AUC undefined, F1
    degenerate, and a pilot that looks like it ran. This is the same error
    `abstention-signals.md` paid for once already, where a stride over a
    file sorted by question type produced d=0.68 from a comparison between
    question kinds rather than between classes.

    So a limited run takes a proportional share of each class, by alternating,
    and the baselines are later scored on exactly this subset.
    """
    if limit is None or limit >= len(instances):
        return {i["question_id"] for i in instances}
    unanswerable = [i for i in instances if i["question_id"].endswith("_abs")]
    answerable = [i for i in instances if not i["question_id"].endswith("_abs")]
    out: list[str] = []
    while len(out) < limit and (unanswerable or answerable):
        for pool in (unanswerable, answerable):
            if pool and len(out) < limit:
                out.append(pool.pop(0)["question_id"])
    return set(out)


def load_cache(path: pathlib.Path, model: str) -> dict[str, float]:
    """Model answers from an earlier run of the same model.

    Keyed on model and question id. A cache shared between checkpoints would
    make the result a property of whichever ran first, which is the same key
    discipline `x1_extraction.py` needed.
    """
    if not path.exists():
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    if stored.get("model") != model:
        return {}
    return {str(k): float(v) for k, v in (stored.get("answers") or {}).items()}


def save_cache(path: pathlib.Path, model: str,
               answers: Mapping[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"model": model, "answers": dict(answers)},
                              indent=1), encoding="utf-8")
    # Replace rather than write in place: a crash during the write would
    # otherwise leave a truncated cache, which is worse than none because it
    # loads and looks complete.
    tmp.replace(path)


def run(split: str = "s", answerable: int = 500, k: int = 10,
        host: str | None = None, model: str = "kev-latest",
        limit_typed: int | None = None,
        trace: str | None = None,
        cache: str | None = None) -> dict[str, Any]:
    client = SystemOneClient(host=host or "http://127.0.0.1:8009", model=model)
    if trace:
        from memory_fabric.adapters.tracing import JsonlSink

        client.add_sink(JsonlSink(trace))
    served = client.available()

    instances = premise.sample(split, answerable)
    typed_on = _stratified(instances, limit_typed)

    # Resume. Two runs of this experiment have been lost whole: one to a
    # formatting error after 500 instances, one to the server going away at
    # 175 of 500 after 100 minutes of CPU. The first was fixed by writing
    # `--out` before formatting, which does not help the second, because the
    # run itself had nothing on disk until it finished. At 35 s a call a
    # 500-instance run is five hours, and anything that long needs to survive
    # being interrupted.
    cache_path = pathlib.Path(cache) if cache else None
    answered: dict[str, float] = (
        load_cache(cache_path, model) if cache_path else {})
    reused = len(answered)
    rows: list[Row] = []
    started = time.perf_counter()
    for position, instance in enumerate(instances):
        excerpts, top1, mean_top10, coverage = context_of(instance, k)
        row = Row(
            question_id=instance["question_id"],
            question_type=instance["question_type"],
            unanswerable=instance["question_id"].endswith("_abs"),
            top1=round(top1, 4), mean_top10=round(mean_top10, 4),
            coverage=round(coverage, 4),
        )
        if instance["question_id"] in typed_on:
            cached = answered.get(instance["question_id"])
            if cached is not None:
                row.p_answerable, row.seconds = cached, 0.0
            else:
                row.p_answerable, row.seconds, row.error = ask(
                    client, instance, excerpts)
                if row.p_answerable is not None and cache_path:
                    answered[instance["question_id"]] = row.p_answerable
                    save_cache(cache_path, model, answered)
        rows.append(row)
        if (position + 1) % 25 == 0:
            done = sum(1 for r in rows if r.p_answerable is not None)
            print(f"  {position + 1}/{len(instances)} "
                  f"({done} typed) {time.perf_counter() - started:.0f}s",
                  file=sys.stderr)

    scored = [r for r in rows if r.p_answerable is not None]
    arms = list(BASELINES) + (["typed"] if scored else [])
    # The typed arm answers for a subset when --limit-typed is given, so the
    # baselines are scored on that same subset: comparing an arm on 100
    # instances against a baseline on 500 would be comparing populations.
    population = scored if (scored and len(scored) < len(rows)) else rows

    results: dict[str, Any] = {}
    for arm in arms:
        results[arm] = {
            "auc": premise._round(auc_of(population, arm)),
            **best_f1(population, arm),
        }
    # Degenerate arm, reported every run as principle 8c requires.
    unanswerable = sum(1 for r in population if r.unanswerable)
    recall, precision = 1.0, unanswerable / len(population)
    results["always_abstain"] = {
        "auc": 0.5,
        "f1": round(2 * precision * recall / (precision + recall), 4),
        "precision": round(precision, 4), "recall_tpr": 1.0, "fpr": 1.0,
    }
    results["oracle"] = {"auc": 1.0, "f1": 1.0, "precision": 1.0,
                         "recall_tpr": 1.0, "fpr": 0.0}

    baseline_f1 = max(results[a].get("f1") or 0.0 for a in BASELINES)
    bar = baseline_f1 + 0.40 * (1.0 - baseline_f1)
    typed_f1 = (results.get("typed") or {}).get("f1")

    # The shared checks rather than four hand-rolled comparisons. The
    # direction check is the one that matters here: this experiment's own
    # baseline is the signal `abstention-signals.md` reported as its own
    # complement, so an AUC convention error would reproduce the published
    # fault in the experiment built to correct it.
    audit = harness_checks.verify(
        ceiling=harness_checks.ceiling(results, "f1"),
        baseline_max=harness_checks.baseline_max(
            results, "f1", list(BASELINES)),
        direction=harness_checks.direction(
            [r.signal("typed") for r in population if r.unanswerable],
            [r.signal("typed") for r in population if not r.unanswerable])
        if scored else {"ok": True, "note": "no typed arm in this run"},
        class_collapse=harness_checks.class_collapse(
            {"answered": len(scored),
             "error": sum(1 for r in rows if r.error)}),
    )

    return {
        "experiment": "x2-typed-abstention",
        "split": split, "k": k, "model": model, "served": served,
        "instances": len(rows), "typed_on": len(scored),
        "reused_from_cache": reused,
        "unanswerable": unanswerable,
        "arms": results,
        "registered": {
            "B_best_baseline_f1": round(baseline_f1, 4),
            "C_oracle_f1": 1.0,
            "bar_40pc_of_headroom": round(bar, 4),
            "typed_f1": typed_f1,
            "supported": bool(typed_f1 is not None and typed_f1 >= bar),
            "share_of_headroom": (
                round((typed_f1 - baseline_f1) / (1.0 - baseline_f1), 4)
                if typed_f1 is not None else None),
            "any_arm_beat_the_oracle": (
                audit["ceiling"].get("arms_above_ceiling") or {}),
        },
        "checks": audit,
        "calibration": calibration(rows),
        "cost": client.usage(),
        "errors": [r.error for r in rows if r.error][:5],
        "rows": [r.__dict__ for r in rows],
    }


def to_markdown(result: Mapping[str, Any]) -> str:
    reg = result["registered"]
    lines = [
        f"# X2 — a typed decision model for abstention · `{result['split']}` split",
        "",
        f"- `{result['model']}`, {result['typed_on']} of {result['instances']} "
        f"instances scored by the model, {result['unanswerable']} unanswerable",
        f"- Registered bar: **{reg['bar_40pc_of_headroom']}** "
        f"= B {reg['B_best_baseline_f1']} + 0.40 × (1.000 - B)",
        "",
        "| arm | AUC | best F1 | precision | TPR | FPR |",
        "|---|---|---|---|---|---|",
    ]
    for arm, row in result["arms"].items():
        lines.append(
            f"| `{arm}` | {row.get('auc')} | {row.get('f1')} | "
            f"{row.get('precision')} | {row.get('recall_tpr')} | "
            f"{row.get('fpr')} |")
    verdict = "SUPPORTED" if reg["supported"] else "NOT SUPPORTED"
    lines += [
        "",
        f"**{verdict}** — typed F1 {reg['typed_f1']} against a bar of "
        f"{reg['bar_40pc_of_headroom']}, "
        f"{reg['share_of_headroom']} of the available headroom.",
    ]
    cal = result.get("calibration") or {}
    if cal:
        lines += [
            "",
            "## Calibration — the reason to want this class of model",
            "",
            "| | |",
            "|---|---|",
            f"| ECE | **{cal['ece']}** |",
            f"| Brier | **{cal['brier']}** (Kev-0.8B's card: 0.481 on new sources) |",
            f"| accuracy at p=0.5 | {cal['accuracy_at_half']} |",
            f"| mean confidence, all | {cal['mean_confidence_all']} |",
            f"| mean confidence, **on errors** | **{cal['mean_confidence_on_errors']}** |",
            f"| mean P(answerable) when answerable | {cal['mean_p_answerable_when_answerable']} |",
            f"| mean P(answerable) when **un**answerable | {cal['mean_p_answerable_when_unanswerable']} |",
            "",
            "Confidence on errors is reported separately because the failure "
            "mode to detect is *confident and wrong*, and an average over all "
            "instances hides it.",
        ]
    audit = result.get("checks") or {}
    if not audit.get("ok", True):
        lines += ["", f"**Checks failed: {audit.get('failed')}.** "
                      f"See the `checks` block in the JSON."]
    if reg["any_arm_beat_the_oracle"]:
        lines += ["", f"**An arm beat the oracle: "
                      f"{reg['any_arm_beat_the_oracle']}. The ceiling is "
                      f"wrong (principle 8b).**"]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="s", choices=["s", "oracle", "m"])
    parser.add_argument("--answerable", type=int, default=500)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--host")
    parser.add_argument("--model", default="kev-latest")
    parser.add_argument("--limit-typed", type=int,
                        help="score only the first N instances with the "
                             "model; the baselines are then scored on that "
                             "same subset so the populations match")
    parser.add_argument("--trace")
    parser.add_argument("--cache",
                        help="path to a resumable answer cache, written after "
                             "every model call so an interrupted run resumes")
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.split, args.answerable, args.k, args.host, args.model,
                 args.limit_typed, args.trace, args.cache)
    # Persist before formatting. A 32-minute X2 run was lost when
    # `to_markdown` hit a Unicode minus sign against a cp1252 console and
    # raised before `--out` was written: the display path must never be able to
    # discard the measurement. Writing first also means a failed `print` costs
    # the summary rather than the run.
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
    text = json.dumps(result, indent=2) if args.as_json else to_markdown(result)
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
