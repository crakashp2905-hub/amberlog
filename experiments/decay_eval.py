"""Decay view evaluation: how much current knowledge a bounded session-start view carries.

    python -m experiments.decay_eval --pilot       # seed 0: recency baseline and oracle only
    python -m experiments.decay_eval               # registered seeds, every arm

Pre-registration: research/prereg/decay-view.md. A plant's memory grows over
time: each asset gets a fact, later restatements, chatter, some corrections
(revisions) and some withdrawals with a replacement fact. At the end a
query-independent view of the store is built under a token budget, and a fixed
reader answers "what is the current value for <asset>?" from the view alone.

| arm | view |
|---|---|
| R | recency: the newest admissible records that fit |
| X | decay view, extractive summaries (no model) |
| S | decay view, agent summaries from a rule-based stand-in (see below) |
| oracle | one line per asset with its current value, newest first, same budget |

S's "agent" is **not a language model** (none is available here): for each
node the view asks to be summarised, it writes "<tag> <value> <unit>" for the
latest statement of each asset in the node. It passes the same submission
check as any agent. It stands for an agent that summarises well; a real
model's summaries are untested.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from pathlib import Path
from typing import Any

from memory_fabric import MemoryFabric
from memory_fabric.context_map import estimate_tokens
from memory_fabric.decay import DecayView, SummaryRejected

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research" / "results" / "decay-view.json"
BUDGET = 300
ARMS = ("R", "X", "S", "oracle")
_VALUE = re.compile(r"(\d+)\s*bar\b")


def build(seed: int, n_assets: int = 32, steps: int = 160) -> tuple[MemoryFabric, dict[str, Any]]:
    rng = random.Random(seed)
    f = MemoryFabric(":memory:", auto_activate=True, hold_suspicious=False, seed=seed)
    tags = [f"P{i}-{rng.choice(['ROT', 'GDA', 'LEE', 'POR'])}" for i in range(n_assets)]
    truth: dict[str, int] = {}
    fact_id: dict[str, str] = {}
    order = list(range(n_assets))
    rng.shuffle(order)
    for step in range(steps):
        tag = tags[order[step % n_assets]] if step < n_assets else rng.choice(tags)
        roll = rng.random()
        if tag not in truth:
            truth[tag] = rng.randint(10, 90)
            fact_id[tag] = f.remember("ops", f"Pump {tag} runs at {truth[tag]} bar.", scope="team")
        elif roll < 0.35:
            f.remember("crew", f"Measured again: {tag} runs at {truth[tag]} bar.", scope="team")
        elif roll < 0.55:
            f.remember("crew", f"Shift handover: {tag} inspected, logbook signed.", scope="team")
        elif roll < 0.75:
            truth[tag] += rng.choice([-4, 3, 5])
            f.revise(fact_id[tag], f"Pump {tag} runs at {truth[tag]} bar.", agent_id="ops",
                     reason="recalibrated")
        elif roll < 0.85:
            f.quarantine(fact_id[tag], reason="sensor fault", actor="lead", basis="contradicted")
            truth[tag] += rng.choice([-9, 8, 11])
            fact_id[tag] = f.remember("audit", f"Pump {tag} runs at {truth[tag]} bar.",
                                      scope="team")
        else:
            f.remember("crew", f"Spare seal for {tag} ordered.", scope="team")
    return f, {"tags": tags, "truth": truth}


def read(texts: list[str], tag: str) -> str:
    """First text naming the tag with a value: the reader every arm shares."""
    # Within one sentence or clause. The registered run searched to the end
    # of the text, so in a summary "P6 inspected. P19 runs at 35 bar" read as
    # P6 = 35: a reader defect that only multi-note texts could trigger
    # (research/results/decay-view.md).
    for text in texts:
        for part in re.split(r"[.;]\s+", text):
            low = part.lower()
            i = low.find(tag.lower())
            if i >= 0:
                m = _VALUE.search(part[i:])
                if m:
                    return m.group(1)
    return "none"


def stand_in_agent(view: DecayView, budget: int) -> int:
    """Answer every pending summary request with '<tag> <value> bar' lines. Returns how many stored."""
    stored = 0
    for _ in range(4):  # summarising changes the view, which may ask for more
        pending = view.pending(budget)
        if not pending:
            break
        for item in pending:
            latest: dict[str, str] = {}
            for text in item["records"]:
                m = re.search(r"(P\d+-[A-Z]+)\D*?(\d+)\s*bar", text)
                if m:
                    latest[m.group(1)] = m.group(2)
            if not latest:
                continue
            summary = "; ".join(f"{t} {v} bar" for t, v in latest.items())
            lo, hi = map(int, item["node"].split("-"))
            try:
                view.submit(lo, hi, summary[:400])
                stored += 1
            except SummaryRejected:
                continue
    return stored


def view_texts(arm: str, f: MemoryFabric, world: dict[str, Any], budget: int) -> list[str]:
    if arm == "R":
        out, used = [], 0
        recent = sorted((m for m in f.state.memories.values()
                         if f.use(m.id, agent_id="reader", audit=False).usable),
                        key=lambda m: (-m.created_at, m.id))
        for m in recent:
            cost = estimate_tokens(m.content)
            if used + cost > budget:
                break
            out.append(m.content)
            used += cost
        return out
    if arm in ("X", "S"):
        view = DecayView(f, "reader")
        return [p.text for p in reversed(view.wake(budget))]  # newest first for the reader
    if arm == "oracle":
        out, used = [], 0
        for tag in world["tags"]:
            line = f"{tag} {world['truth'][tag]} bar"
            if used + estimate_tokens(line) > budget:
                break
            out.append(line)
            used += estimate_tokens(line)
        return out
    raise ValueError(arm)


def run_seed(seed: int, arms: tuple[str, ...], budget: int) -> dict[str, Any]:
    out: dict[str, Any] = {"seed": seed}
    for arm in arms:
        f, world = build(seed)
        stored = stand_in_agent(DecayView(f, "reader"), budget) if arm == "S" else 0
        texts = view_texts(arm, f, world, budget)
        stale = 0
        correct = 0
        for tag in world["tags"]:
            answer = read(texts, tag)
            correct += answer == str(world["truth"][tag])
            stale += answer not in ("none", str(world["truth"][tag]))
        n = len(world["tags"])
        out[arm] = {"current_recall": round(correct / n, 4), "stale_answer_rate": round(stale / n, 4),
                    "tokens": sum(estimate_tokens(t) for t in texts), "summaries_stored": stored}
        f.close()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--seeds", type=int, nargs="*", default=[1, 2, 3, 4, 5])
    parser.add_argument("--budget", type=int, default=BUDGET)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    seeds = [0] if args.pilot else args.seeds
    arms = ("R", "oracle") if args.pilot else ARMS
    runs = [run_seed(s, arms, args.budget) for s in seeds]
    summary = {arm: {k: round(statistics.mean(r[arm][k] for r in runs), 4)
                     for k in runs[0][arm]} for arm in arms}
    beats = [a for a in arms if a != "oracle"
             and summary[a]["current_recall"] > summary["oracle"]["current_recall"]]
    result = {"experiment": "decay-view", "budget": args.budget, "seeds": seeds,
              "runs": runs, "summary": summary, "any_arm_beats_oracle": beats}
    print(json.dumps({"summary": summary, "any_arm_beats_oracle": beats}, indent=1))
    out = args.out or (None if args.pilot else OUT)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
