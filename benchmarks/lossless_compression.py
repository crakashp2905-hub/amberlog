"""Descriptive five-seed exact reconstruction and content-byte accounting; no token claim."""
from __future__ import annotations

import json
from pathlib import Path
import random
import time

from benchmarks.manifest import head
from amberlog import Amberlog
from amberlog.compaction import compact_session
from amberlog.lossless_compaction import dictionary_summary

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (503, 509, 521, 523, 541)


def run_seed(seed: int) -> dict:
    from amberlog.lossless_compaction import decode_records

    rng = random.Random(seed)
    f = Amberlog(":memory:", recognise_copies=False)
    try:
        episode = f.start_episode("writer", "inspection")
        source = [f"Unit P{i} limit is {rng.randint(3, 80)} bar. "
                  "It must not be restarted before independent verification."
                  for i in range(30)]
        ids = [f.remember("writer", text, scope="team", auto_activate=True,
                         source_episodes=[episode.id]) for text in source]
        started = time.perf_counter()
        report = compact_session(f, episode.id, "writer", summarise=dictionary_summary)
        stored = f.state.memories[report.summary_id].content
        encode_ms = round(1000 * (time.perf_counter() - started), 3)
        prefix = "Session summary (inspection): "
        payload = stored[len(prefix):]
        restored = decode_records(payload)
        raw_bytes = len(" ".join(source).encode("utf-8"))
        summary_bytes = len(stored.encode("utf-8"))
        f.erase_content(ids[0], reason="qualification erasure")
        return {"seed": seed, "source_content_bytes": raw_bytes,
                "summary_content_bytes": summary_bytes, "saved_content_bytes": raw_bytes - summary_bytes,
                "roundtrip_exact": restored == source, "encode_ms": encode_ms,
                "summary_erased": report.summary_id in f.state.erased,
                "pipeline_bytes_including_retained_sources": raw_bytes + summary_bytes}
    finally:
        f.close()


def main() -> int:
    rows = [run_seed(seed) for seed in SEEDS]
    result = {"commit": head(), "seeds": SEEDS, "rows": rows,
              "decision": "DESCRIPTIVE", "actual_model_tokens": None,
              "cost": {"model_calls": 0, "model_usd": 0, "hardware_usd": None},
              "limitations": ["repetitive synthetic English fixture, no independent QA or model study",
                              "sources retained: total stored content grows despite smaller summary",
                              "UTF-8 content bytes exclude log/encryption/index overhead",
                              "dictionary must be decoded or understood by the consuming client"]}
    output = ROOT / "research/results/lossless-compression-qualification.json"
    output.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return any(not r["roundtrip_exact"] or not r["summary_erased"] or r["saved_content_bytes"] <= 0 for r in rows)


if __name__ == "__main__":
    raise SystemExit(main())
