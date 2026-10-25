"""Temporary diagnostic: why R3's LongMemEval arm scores 0.033 for lexical."""

from __future__ import annotations

import sys
from collections import Counter

from experiments import longmemeval_bench as lme
from memory_fabric import MemoryFabric

insts = lme.load("s", limit=12)
rep = lme.run_arm("lexical", insts, 10)
print("bench run_arm lexical turn_recall:",
      sum(r.turn_recall for r in rep.results) / len(rep.results))
for inst in insts[:6]:
    gold = {(sid, pos) for sid, s in zip(inst["haystack_session_ids"], inst["haystack_sessions"])
            for pos, t in enumerate(s) if t.get("has_answer")}
    f = MemoryFabric(":memory:", auto_activate=True, encrypt_content=False,
                     recognise_copies=False, retrieval="lexical")
    mapping = lme._write_history(f, inst)
    states = Counter(f.lifecycle_of(m).value for m in mapping)
    gstates = Counter(f.lifecycle_of(m).value for m, p in mapping.items() if p in gold)
    as_of = lme.parse_date(inst.get("question_date") or "")
    r1 = f.retrieve(agent_id="lme", query=inst["question"], k=10, min_relevance=0.0, as_of=as_of)
    r2 = f.retrieve(agent_id="lme", query=inst["question"], k=10, min_relevance=0.0)
    print(inst["question_type"], "turns", len(mapping), "states", dict(states),
          "gold", len(gold), dict(gstates), "as_of", as_of,
          "dates", (inst.get("haystack_dates") or [])[:2], inst.get("question_date"),
          "ret_asof", len(r1.exposed), "withheld", len(r1.withheld),
          "ret_none", len(r2.exposed), flush=True)
    f.close()
sys.exit(0)
