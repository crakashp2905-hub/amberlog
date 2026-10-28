"""Frozen synthetic ECV1 corpus. Gold comes from latent records, never a text parser.

Development and holdout have disjoint seeds, identifiers and surface templates.
This is independently generated gold, not independent third-party replication.
"""
from __future__ import annotations

import hashlib
import json
import random
from typing import Any

SPLITS = {"dev": (11, 23, 37, 41, 53), "test": (101, 127, 149, 163, 181)}
CONFIG = {"version": "ecv1-data/1", "records": 48, "budget": 12,
          "fields": ["kind", "status"], "queries": [["sensor", "open"], ["door", "closed"]]}


def generate(seed: int, split: str) -> dict[str, Any]:
    if seed not in SPLITS[split]:
        raise ValueError("seed does not belong to the frozen split")
    rng = random.Random(seed)
    records = []
    for i in range(CONFIG["records"]):
        kind, status = rng.choice(("sensor", "door", "pump")), rng.choice(("open", "closed"))
        rid = f"{split}-{seed}-{i}"
        # Independent authoring style: holdout varies wrappers and punctuation,
        # while retaining a common key/value evidence contract.
        text = (f"Record {rid}: kind={kind}; status={status}." if split == "dev" else
                f"Inspection [{rid}]\nstatus = {status}\nkind = {kind}\nEnd inspection.")
        mode = i % 4
        fields = {"kind": kind, "status": status} if mode == 0 else (
            {"kind": kind} if mode == 1 else ({"status": status} if mode == 2 else {}))
        records.append({"rid": rid, "text": text, "fields": fields,
                        "truth": {"kind": kind, "status": status}})
    queries = [{"kind": k, "status": s} for k, s in CONFIG["queries"]]
    return {"records": records, "queries": queries,
            "gold": [[r["rid"] for r in records if all(r["truth"][k] == v for k, v in q.items())]
                     for q in queries]}


def digest(split: str) -> str:
    payload = {"config": CONFIG, "seeds": SPLITS[split],
               "data": [generate(s, split) for s in SPLITS[split]]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
