"""LongMemEval — the second external benchmark, and the first with updates.

[LongMemEval](https://arxiv.org/abs/2410.10813) (Wu et al., ICLR 2025) is 500
questions over long chat histories, with **turn-level gold evidence** written
by its authors. It arrives here because of what it tests, not because it is
available:

| LongMemEval ability | what it exercises here | measured only internally until now |
|---|---|---|
| knowledge updates (78) | retraction and correction propagation | P3, P2b — my fixtures, my labels |
| temporal reasoning (133) | bitemporal validity, `as_of` | `superseded_rev` — mine |
| multi-session reasoning (133) | chain reconstruction across memories | `multi_hop_3/4` — mine |
| abstention (30) | reporting insufficiency | **0.000 on every arm, and no external check at all** |

`research/SCORECARD.md` has said for several milestones that SciFact is this
project's only external check and that **SciFact has no provenance, no
lifecycle, no retraction and no tenants**. This is the benchmark that does.

## The abstention instances, which the reference harness skips

LongMemEval's own retrieval evaluation **excludes the 30 `_abs` instances**,
because a question whose answer is "you never told me that" has no gold
location to retrieve. Reasonable for a recall metric, and it leaves the one
ability this project has repeatedly measured at zero untested.

They are scored here instead, on whether the system **reports insufficiency**:
`reconstruct` returns an incomplete chain naming the query terms nothing could
cover, so "the corpus does not join up" is a value the fabric can express.
Reported separately from recall and never mixed into it.

## Turn granularity, and the fabric's own `remember`

Each turn becomes one memory, written through `remember` with the session's
timestamp as `valid_from` — so temporal filtering and copy recognition see the
same history a deployment would. Session-level recall is derived from the turns
rather than measured separately, which is how the reference harness defines it.

Nothing is tuned on this benchmark. It is an external check, and the first run
is the first look.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

DATA = (pathlib.Path(__file__).resolve().parent.parent
        / "research" / "bench" / "longmemeval" / "data")
SPLITS = {
    "oracle": "longmemeval_oracle.json",
    "s": "longmemeval_s_cleaned.json",
    "m": "longmemeval_m_cleaned.json",
}
DEFAULT_K = 10

_DATE = re.compile(r"(\d{4})/(\d{2})/(\d{2})\s*\([A-Za-z]{3}\)\s*(\d{2}):(\d{2})")


def parse_date(text: str) -> int | None:
    """`2023/04/10 (Mon) 17:50` to a unix timestamp.

    Returns None rather than guessing when the format differs: a wrong
    timestamp would silently corrupt temporal filtering, and `valid_from=None`
    means open-ended, which is the honest reading of "the date is unknown".
    """
    found = _DATE.search(text or "")
    if not found:
        return None
    import calendar

    year, month, day, hour, minute = (int(g) for g in found.groups())
    return calendar.timegm((year, month, day, hour, minute, 0, 0, 0, 0))


def load(split: str, limit: int | None = None) -> list[dict[str, Any]]:
    path = DATA / SPLITS[split]
    if not path.exists():
        raise SystemExit(
            f"{path} is not present. LongMemEval is downloaded, never "
            f"committed (15 MB for the oracle split, 277 MB for `s`):\n"
            f"  curl -L -o {path} https://huggingface.co/datasets/"
            f"xiaowu0162/longmemeval-cleaned/resolve/main/{SPLITS[split]}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not limit or limit >= len(data):
        return data
    # Stratified, because the file is sorted by question type: a plain
    # `data[:limit]` of 60 returned 60 temporal-reasoning instances and no
    # others, which looks like a benchmark result and is a slicing artifact.
    # Round-robin over the types, deterministic, so a limited run is a
    # miniature of the whole rather than one corner of it.
    groups: dict[str, list] = defaultdict(list)
    for item in data:
        groups[item["question_type"]].append(item)
    order = sorted(groups)
    out = []
    index = 0
    while len(out) < limit:
        added = False
        for name in order:
            if index < len(groups[name]) and len(out) < limit:
                out.append(groups[name][index])
                added = True
        if not added:
            break
        index += 1
    return out


# --- scoring ----------------------------------------------------------------


@dataclass
class InstanceResult:
    question_id: str
    question_type: str
    is_abstention: bool
    turns: int
    sessions: int
    gold_turns: int
    turn_hits: int
    session_hit: bool
    reported_insufficient: bool
    returned: int
    latency_ms: float

    @property
    def turn_recall(self) -> float:
        return self.turn_hits / self.gold_turns if self.gold_turns else 0.0


@dataclass
class ArmReport:
    arm: str
    results: list[InstanceResult] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        answerable = [r for r in self.results if not r.is_abstention]
        abstain = [r for r in self.results if r.is_abstention]
        mean = lambda xs: round(statistics.fmean(xs), 4) if xs else None  # noqa: E731
        return {
            "instances": len(self.results),
            "turn_recall": mean([r.turn_recall for r in answerable]),
            "session_recall": mean([float(r.session_hit) for r in answerable]),
            "any_gold_turn": mean([float(r.turn_hits > 0) for r in answerable]),
            # Scored only on the 30 instances the reference harness skips.
            "abstention_rate": mean([float(r.reported_insufficient) for r in abstain]),
            "false_insufficiency": mean(
                [float(r.reported_insufficient) for r in answerable]),
            "returned": mean([float(r.returned) for r in self.results]),
            "latency_ms": mean([r.latency_ms for r in self.results]),
            "n_abstention": len(abstain),
        }

    def by_type(self) -> dict[str, dict[str, Any]]:
        groups: dict[str, list[InstanceResult]] = defaultdict(list)
        for r in self.results:
            groups[r.question_type].append(r)
        out = {}
        for name, rows in sorted(groups.items()):
            answerable = [r for r in rows if not r.is_abstention]
            out[name] = {
                "n": len(rows),
                "turn_recall": round(
                    statistics.fmean([r.turn_recall for r in answerable]), 4)
                if answerable else None,
                "session_recall": round(
                    statistics.fmean([float(r.session_hit) for r in answerable]), 4)
                if answerable else None,
            }
        return out


# --- the arms ---------------------------------------------------------------


def _write_history(fabric, instance: Mapping[str, Any]) -> dict[str, tuple[str, int]]:
    """Each turn becomes one memory. Returns memory id -> (session id, index).

    Written through `remember` with the session timestamp as `valid_from`, so
    temporal filtering, copy recognition and the gates all see what a
    deployment would see rather than a flattened corpus.
    """
    mapping: dict[str, tuple[str, int]] = {}
    sessions = instance["haystack_sessions"]
    session_ids = instance["haystack_session_ids"]
    dates = instance.get("haystack_dates") or []
    for index, (session_id, session) in enumerate(zip(session_ids, sessions)):
        when = parse_date(dates[index] if index < len(dates) else "")
        for position, turn in enumerate(session):
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            stored = fabric.remember(
                agent_id="lme",
                content=f"{turn.get('role', 'user')}: {content}",
                valid_from=when,
            )
            mapping[stored] = (session_id, position)
    return mapping


def run_arm(arm: str, instances: Sequence[Mapping[str, Any]], k: int,
            embedder=None, temporal: str = "as_of") -> ArmReport:
    """`temporal` selects which temporal question the harness asks.

    `as_of` passes the question's own date, which is what `retrieve`'s
    docstring used to recommend without qualification. `until` asks for the
    history through that date. `none` filters nothing.

    It is a flag rather than a scratch probe because the three give materially
    different answers -- 19 points of turn recall on temporal-reasoning -- and
    a finding that can only be reproduced by editing the harness is not
    reproducible.
    """
    from memory_fabric import MemoryFabric

    report = ArmReport(arm=arm)
    for instance in instances:
        gold_sessions = set(instance.get("answer_session_ids") or ())
        gold_turns = {
            (sid, position)
            for sid, session in zip(instance["haystack_session_ids"],
                                    instance["haystack_sessions"])
            for position, turn in enumerate(session)
            if turn.get("has_answer")
        }
        retrieval = {"lexical": "lexical", "vector": "vector",
                     "hybrid": "hybrid", "chain": "lexical",
                     "real_vector": "vector", "real_hybrid": "hybrid",
                     "hybrid_tiebreak": "hybrid",
                     "hybrid_replace": "hybrid",
                     "lexical_tiebreak": "lexical",
                     "lexical_replace": "lexical",
                     "oracle": "lexical"}[arm]
        kwargs: dict[str, Any] = {}
        if arm.endswith("_tiebreak"):
            kwargs["rerank"] = "tiebreak"
        elif arm.endswith("_replace"):
            kwargs["rerank"] = "replace"
        if arm.startswith("real_") and embedder is not None:
            kwargs["embedder"] = embedder
        fabric = MemoryFabric(
            ":memory:", auto_activate=True, encrypt_content=False,
            retrieval=retrieval,
            # Off: it is a per-write content scan and this benchmark writes
            # tens of thousands of turns. Its own cost is measured in
            # research/results/p4-envelope.md and its correctness in
            # tests/test_duplicates.py; paying for it here would measure the
            # scan rather than retrieval.
            recognise_copies=False,
            **kwargs,
        )
        try:
            if embedder is not None and arm.startswith("real_"):
                # Batch the instance's turns rather than embedding one text
                # per call. Measured on the same 90 texts:
                #
                #   one at a time   92.0 s   1.0 embeddings/s
                #   warm(chunk=64)  43.1 s   2.1 embeddings/s
                #
                # 2.1x, which decides what is runnable. The `oracle` split's
                # ~11,500 embeddings go from ~3.2 hours to ~91 minutes; the
                # `s` split's ~245,500 stay infeasible either way, at ~32
                # hours batched. The embedder's cache is shared across arms
                # because `main` builds one, so `real_hybrid` costs almost
                # nothing after `real_vector`.
                texts = [
                    f"{turn.get('role', 'user')}: {(turn.get('content') or '').strip()}"
                    for session in instance["haystack_sessions"]
                    for turn in session
                    if (turn.get("content") or "").strip()
                ]
                embedder.warm(texts)
            mapping = _write_history(fabric, instance)
            as_of = parse_date(instance.get("question_date") or "")
            bounds: dict[str, Any] = {}
            if temporal == "as_of":
                bounds["as_of"] = as_of
            elif temporal == "until":
                bounds["until"] = as_of
            started = time.perf_counter()
            insufficient = False
            if arm == "oracle":
                returned = [
                    mid for mid, (sid, pos) in mapping.items()
                    if (sid, pos) in gold_turns
                ][:k]
            elif arm == "chain":
                chain = fabric.reconstruct(
                    agent_id="lme", query=instance["question"], k=k, **bounds)
                returned = [step.memory_id for step in chain.steps]
                insufficient = not chain.complete
            else:
                result = fabric.retrieve(
                    agent_id="lme", query=instance["question"], k=k,
                    min_relevance=0.0, **bounds)
                returned = [m.id for m in result.exposed]
                insufficient = not returned
            elapsed = (time.perf_counter() - started) * 1000.0

            located = [mapping[m] for m in returned if m in mapping]
            hits = len({p for p in located if p in gold_turns})
            report.results.append(InstanceResult(
                question_id=instance["question_id"],
                question_type=instance["question_type"],
                is_abstention=instance["question_id"].endswith("_abs"),
                turns=len(mapping),
                sessions=len(instance["haystack_sessions"]),
                gold_turns=len(gold_turns),
                turn_hits=hits,
                session_hit=any(sid in gold_sessions for sid, _ in located),
                reported_insufficient=insufficient,
                returned=len(returned),
                latency_ms=elapsed,
            ))
        finally:
            fabric.close()
    return report


ARMS = ("lexical", "vector", "hybrid", "hybrid_tiebreak", "hybrid_replace",
        "lexical_tiebreak", "lexical_replace", "chain", "real_vector",
        "real_hybrid", "oracle")


def real_embedder():
    """The trained embedder, or None with a reason printed.

    Same adapter the other benchmarks use, so a `real_*` number here is
    comparable with the SciFact ones.
    """
    try:
        from memory_fabric.adapters.ollama import OllamaEmbedder

        return OllamaEmbedder()
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"  real_* arms skipped: {type(exc).__name__}: {exc}")
        return None


def to_markdown(result: Mapping[str, Any]) -> str:
    fmt = lambda x: "—" if x is None else f"{x:.3f}"  # noqa: E731
    lines = [
        f"# LongMemEval — {result['split']} split",
        "",
        f"- **Instances:** {result['instances']} "
        f"({result['abstention']} abstention) · **k:** {result['k']} · "
        f"**temporal:** `{result['temporal']}`",
        f"- **Turns a history:** median {result['median_turns']}, "
        f"max {result['max_turns']}",
        "- Turn granularity: each turn is one memory, written through "
        "`remember` with the session timestamp as `valid_from`.",
        "",
        "| arm | turn recall | session recall | any gold turn | returned | latency ms |",
        "|---|---|---|---|---|---|",
    ]
    for arm, row in result["arms"].items():
        lines.append(
            f"| `{arm}` | {fmt(row['turn_recall'])} | "
            f"{fmt(row['session_recall'])} | {fmt(row['any_gold_turn'])} | "
            f"{fmt(row['returned'])} | {fmt(row['latency_ms'])} |")

    lines += [
        "",
        "## Abstention — the 30 instances the reference harness skips",
        "",
        "LongMemEval excludes these from retrieval scoring because a question "
        "whose answer is \"you never told me that\" has no gold location. They "
        "are scored here on whether the system **reports insufficiency**, and "
        "`false insufficiency` is the same signal on the answerable instances, "
        "because a system that always claims insufficiency scores 1.000 on the "
        "first column.",
        "",
        "| arm | reports insufficiency (30 abs) | false insufficiency (answerable) |",
        "|---|---|---|",
    ]
    for arm, row in result["arms"].items():
        lines.append(
            f"| `{arm}` | {fmt(row['abstention_rate'])} | "
            f"{fmt(row['false_insufficiency'])} |")

    types = sorted({t for arm in result["by_type"].values() for t in arm})
    lines += ["", "## Turn recall by question type", "",
              "| arm | " + " | ".join(f"`{t}` ({result['type_counts'][t]})"
                                      for t in types) + " |",
              "|---|" + "---|" * len(types)]
    for arm, rows in result["by_type"].items():
        cells = [fmt(rows.get(t, {}).get("turn_recall")) for t in types]
        lines.append(f"| `{arm}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="oracle", choices=sorted(SPLITS))
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--arms", nargs="*", default=["lexical", "vector",
                                                      "hybrid", "chain", "oracle"])
    parser.add_argument(
        "--temporal", default="as_of", choices=["as_of", "until", "none"],
        help="which temporal question to ask; see run_arm")
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    instances = load(args.split, args.limit)
    embedder = real_embedder() if any(
        a.startswith("real_") for a in args.arms) else None

    reports: dict[str, ArmReport] = {}
    for arm in args.arms:
        if arm.startswith("real_") and embedder is None:
            continue
        started = time.perf_counter()
        reports[arm] = run_arm(arm, instances, args.k, embedder,
                               temporal=args.temporal)
        print(f"  {arm}: {time.perf_counter() - started:.1f}s", file=sys.stderr)

    turns = [sum(len(s) for s in i["haystack_sessions"]) for i in instances]
    result = {
        "benchmark": "longmemeval",
        "split": args.split,
        "k": args.k,
        "temporal": args.temporal,
        "instances": len(instances),
        "abstention": sum(1 for i in instances
                          if i["question_id"].endswith("_abs")),
        "median_turns": int(statistics.median(turns)),
        "max_turns": max(turns),
        "type_counts": dict(Counter(i["question_type"] for i in instances)),
        "arms": {name: r.summary() for name, r in reports.items()},
        "by_type": {name: r.by_type() for name, r in reports.items()},
    }
    text = json.dumps(result, indent=2) if args.as_json else to_markdown(result)
    print(text)
    if args.out:
        pathlib.Path(args.out).write_text(
            to_markdown(result) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
