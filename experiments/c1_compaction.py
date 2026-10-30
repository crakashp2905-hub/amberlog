"""C1 -- does governed session compaction help a later session under a context budget?

Model-free and deterministic. Per seed, 8 past sessions. Each session states
6 facts (equipment, parameter, value) as turn-level notes: each fact
restated 2-3 times with different wording, plus filler turns with no value.
Across the history, one fact is **corrected** after its session ended (the
old note is withdrawn with `correction.apply`, and the new value written as
a fresh note), and one fact is **disputed** (a second source gives another
value).

A later session asks about every fact, with a context budget of B words.
Each arm fills the budget from retrieval, in rank order:

| arm | store contents |
|---|---|
| `raw` | the turn-level notes only |
| `compacted` | notes plus one `compact_session` summary per session (governed: lineage, disputes kept) |
| `naive_summary` | notes plus one plain summary per session: no lineage, first value wins on a dispute |
| `full_context` | every note, no budget (the degenerate case 8c says to report, not to beat) |
| `oracle` | exactly the current note for the fact, within the same budget |

Metrics per question: **sufficient** (the current value is in the context),
**stale** (the corrected-away value is in the context), **dispute shown**
(both values of the disputed fact are present), and words used.

    python -m experiments.c1_compaction --split dev
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
from pathlib import Path
from typing import Any

from memory_fabric import MemoryFabric, correction
from memory_fabric.compaction import compact_session
from memory_fabric.model import ProvenanceMethod

ROOT = Path(__file__).resolve().parents[1]
SPLITS = {"dev": range(200, 203), "test": range(300, 310)}
BUDGETS = (40, 80, 160, 320)
PRIMARY_BUDGET = 80
ARMS = ("raw", "raw_episode", "compacted", "naive_summary", "full_context", "oracle")
PARAMS = [("purge time", "s"), ("restart pressure", "bar"), ("setpoint", "C"),
          ("trip current", "A"), ("belt speed", "m/min"), ("torque limit", "Nm")]
TEMPLATES = ["The {p} for {e} is {v} {u}.", "Note: {e} {p} {v} {u}.",
             "Confirmed again today that {e} runs with a {p} of {v} {u}."]
FILLER = ["Shift handover went smoothly.", "Checked the logbook, nothing unusual.",
          "Waiting on parts from stores.", "Coffee machine in bay 2 is fixed."]


def build(seed: int, arm: str) -> tuple[MemoryFabric, list[dict[str, Any]]]:
    rng = random.Random(seed)
    f = MemoryFabric(":memory:", auto_activate=True, seed=seed)
    facts, episodes = [], []
    for s in range(8):
        ep = f.start_episode("agent", f"shift-{s}").id
        episodes.append(ep)
        for n in range(6):
            p, u = PARAMS[n]
            e = f"{['P', 'V', 'C', 'F', 'B', 'M'][n]}{rng.randint(100, 999)}"
            v = rng.randint(2, 99)
            ids = []
            for t in rng.sample(TEMPLATES, rng.randint(2, 3)):
                ids.append(f.remember("agent", t.format(p=p, e=e, v=v, u=u),
                                      source_episodes=[ep], scope="team"))
                if rng.random() < 0.6:
                    f.remember("agent", rng.choice(FILLER), source_episodes=[ep], scope="team")
            facts.append({"e": e, "p": p, "u": u, "v": v, "ids": ids, "episode": ep,
                          "session": f"shift-{s}", "q": f"What is the {p} for {e}?"})
    disputed = facts[rng.randrange(len(facts))]
    other = disputed["v"] + 7
    disputed["dispute"] = other
    f.remember("vendor", f"The {disputed['p']} for {disputed['e']} is {other} {disputed['u']}.",
               source_episodes=[disputed["episode"]], scope="team")
    corrected = rng.choice([x for x in facts if x is not disputed])
    if arm in ("compacted", "naive_summary"):
        for ep in episodes:
            if arm == "compacted":
                compact_session(f, ep, agent_id="compactor")
            else:
                # Findable by session exactly as the governed summary is, so
                # the only difference between the two arms is governance.
                f.remember("summariser", _naive(f, ep), scope="team",
                           method=ProvenanceMethod.CONSOLIDATED,
                           context={"naive_summary_of": ep})
    # The correction arrives after the sessions (and their summaries) exist.
    for mid in corrected["ids"]:
        correction.apply(f, mid, reason="re-measured", actor="lead")
    corrected["stale"] = corrected["v"]
    corrected["v"] = corrected["v"] + 11
    corrected["ids"] = [f.remember("lead", f"The {corrected['p']} for {corrected['e']} is "
                                           f"{corrected['v']} {corrected['u']}.", scope="team")]
    if arm == "compacted":
        # What the background manager's `compaction` task does next.
        from memory_fabric.compaction import recompact

        recompact(f, agent_id="manager")
    return f, facts


def _naive(f: MemoryFabric, episode: str) -> str:
    from memory_fabric.compaction import session_memories

    seen, lines = set(), []
    for m in session_memories(f, episode):
        nums = re.findall(r"\b([A-Z]\d{3})\b", m.content)
        if nums and nums[0] in seen:
            continue  # first value wins: a dispute is silently resolved
        if nums:
            seen.add(nums[0])
            lines.append(m.content)
    from memory_fabric.compaction import session_label

    return f"Session summary ({session_label(f, episode)}): " + " ".join(lines)


def context(f: MemoryFabric, arm: str, fact: dict[str, Any], budget: int | None) -> str:
    if arm == "oracle":
        texts = [f.get(fact["ids"][-1]).content]
        if "dispute" in fact:
            texts += [m.content for m in f.state.memories.values()
                      if m.provenance.created_by == "vendor"]
    else:
        k = 200 if arm == "full_context" else 20
        texts = [m.content for m in f.retrieve("asker", fact["q"], k=k,
                                               group_by_source_root=False).exposed]
    out, used = [], 0
    for t in texts:
        n = len(t.split())
        if budget is not None and used + n > budget:
            continue
        out.append(t)
        used += n
    return " ".join(out)


def states(text: str, equipment: str, value: int) -> bool:
    """Whether one clause of the context gives this equipment this value.

    Per clause, not per context: counting a number anywhere in a large
    context matched unrelated facts by coincidence (the dev pilot's
    full-context arm read 0.33 "stale" with every stale note withdrawn).
    """
    for clause in re.split(r"[.;]", text):
        if equipment in clause and re.search(rf"(?<!\d){value}(?!\d)", clause):
            return True
    return False


def raw_episode_texts(f: MemoryFabric, episode: str, facts: list[dict[str, Any]]) -> list[str]:
    """The session's own usable notes, ranked by the session's parameters."""
    from memory_fabric.compaction import session_memories
    from memory_fabric.model import EXPOSABLE_STATES

    mine = {m.id for m in session_memories(f, episode)
            if m.lifecycle_state in EXPOSABLE_STATES
            and "compaction_of" not in (m.context or {})}
    mine |= {x["ids"][-1] for x in facts}  # a correction written later belongs to it too
    ranked = [m for m in f.retrieve("asker", " ".join(x["p"] for x in facts), k=400,
                                    group_by_source_root=False, min_relevance=0.0).exposed
              if m.id in mine]
    return [m.content for m in ranked]


def handoff_context(f: MemoryFabric, arm: str, session: str, episode: str,
                    facts: list[dict[str, Any]], budget: int | None) -> str:
    """Context for "what did <session> establish?", filled to the budget in rank order."""
    from memory_fabric.compaction import session_memories
    from memory_fabric.model import EXPOSABLE_STATES

    q = f"What was recorded during {session}? Session summary {session}"
    if arm == "oracle":
        texts = [f.get(x["ids"][-1]).content for x in facts]
    elif arm in ("compacted", "naive_summary"):
        key = "compaction_of" if arm == "compacted" else "naive_summary_of"
        summary = [m for m in f.state.memories.values()
                   if (m.context or {}).get(key) == episode
                   and m.lifecycle_state in EXPOSABLE_STATES]
        texts = [m.content for m in summary[-1:]] + raw_episode_texts(f, episode, facts)
    elif arm == "raw_episode":
        texts = raw_episode_texts(f, episode, facts)
    elif arm == "full_context":
        # Every usable note, unranked and unbudgeted: retrieval returns nothing
        # for a query with no lexical overlap, which zeroed this arm at first.
        texts = [m.content for m in f.state.memories.values()
                 if m.lifecycle_state in EXPOSABLE_STATES]
    else:
        texts = [m.content for m in f.retrieve("asker", q, k=20, group_by_source_root=False,
                                               min_relevance=0.0).exposed]
    out, used = [], 0
    for text in texts:
        n = len(text.split())
        if budget is not None and used + n > budget:
            continue
        out.append(text)
        used += n
    return " ".join(out)


def run(seeds: range) -> dict[str, Any]:
    rows = []
    for seed in seeds:
        for arm in ARMS:
            f, facts = build(seed, arm)
            for fact in facts:
                for budget in BUDGETS:
                    b = None if arm == "full_context" else budget
                    text = context(f, arm, fact, b)
                    vals = set(re.findall(r"\b\d+\b", text))
                    rows.append({"seed": seed, "arm": arm, "budget": budget, "e": fact["e"],
                                 "sufficient": int(str(fact["v"]) in vals and fact["e"] in text),
                                 "stale": int("stale" in fact and str(fact["stale"]) in vals
                                              and fact["e"] in text),
                                 "corrected": int("stale" in fact),
                                 "disputed": int("dispute" in fact),
                                 "dispute_shown": int("dispute" in fact and str(fact["v"]) in vals
                                                      and str(fact["dispute"]) in vals),
                                 "words": len(text.split())})
            for session in sorted({x["session"] for x in facts}):
                mine = [x for x in facts if x["session"] == session]
                for budget in BUDGETS:
                    b = None if arm == "full_context" else budget
                    text = handoff_context(f, arm, session, mine[0]["episode"], mine, b)
                    vals = set(re.findall(r"\b\d+\b", text))
                    covered = [int(states(text, x["e"], x["v"])) for x in mine]
                    stale = [x for x in mine if "stale" in x]
                    rows.append({"seed": seed, "arm": arm, "budget": budget, "kind": "handoff",
                                 "coverage": sum(covered) / len(covered),
                                 "stale": int(bool(stale) and states(text, stale[0]["e"],
                                                                     stale[0]["stale"])),
                                 "corrected": int(bool(stale)), "words": len(text.split())})
            f.close()

    def hrate(arm: str, budget: int, key: str, where: str | None = None) -> float:
        sel = [r for r in rows if r.get("kind") == "handoff" and r["arm"] == arm
               and r["budget"] == budget and (where is None or r[where])]
        return round(sum(r[key] for r in sel) / len(sel), 4) if sel else float("nan")

    def rate(arm: str, budget: int, key: str, where: str | None = None) -> float:
        sel = [r for r in rows if r.get("kind") != "handoff" and r["arm"] == arm
               and r["budget"] == budget and (where is None or r[where])]
        return round(sum(r[key] for r in sel) / len(sel), 4) if sel else float("nan")

    table = {arm: {b: {"sufficiency": rate(arm, b, "sufficient"),
                       "stale_after_correction": rate(arm, b, "stale", "corrected"),
                       "dispute_shown": rate(arm, b, "dispute_shown", "disputed"),
                       "mean_words": round(sum(r["words"] for r in rows if r["arm"] == arm
                                               and r["budget"] == b)
                                           / max(1, sum(1 for r in rows if r["arm"] == arm
                                                        and r["budget"] == b)), 1)}
                   for b in BUDGETS} for arm in ARMS}
    handoff = {arm: {b: {"coverage": hrate(arm, b, "coverage"),
                         "stale_after_correction": hrate(arm, b, "stale", "corrected")}
                     for b in BUDGETS} for arm in ARMS}
    return {"single_fact": table, "handoff": handoff, "rows": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=sorted(SPLITS), default="dev")
    args = parser.parse_args()
    result = run(SPLITS[args.split])
    result["split"] = args.split
    result["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                      capture_output=True, text=True, cwd=ROOT).stdout.strip()
    out = ROOT / "research" / "results" / f"c1-compaction-{args.split}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for arm, by_b in result["handoff"].items():
        print("handoff", arm, json.dumps(by_b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
