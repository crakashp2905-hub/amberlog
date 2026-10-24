"""X6's registered secondaries that the harness did not print, from its cache.

    python -m experiments.x6_secondary --cache x6_cache.json --out x6-secondary.json

No model calls: every number here is recomputed from the per-episode records
`experiments/x6_cross_model.py` cached during the registered run. Three
secondaries in the registration (§5) were not in the harness's own output:

* **Retrieval by writer, and overlap.** Retrieval does not depend on the
  reader -- the query and the index are the same -- so `right_in_context` must
  be identical across readers for a given writer. That is checked, not
  assumed, and a mismatch fails the run. Overlap is the share of (seed,
  episode) units on which two writers' corpora agree about whether a correct
  lesson was retrieved.
* **Conversion**: P(success | a correct lesson in context), per cell. This is
  what separates prediction 4's *retrieval differs* from *reading differs*.
* **Cost by reader, and reading time by corpus**, in wall seconds per cell,
  with medians beside totals: one cell ran across a machine sleep and its wall
  time is not a cost. A cell times *reading* only. The time each writer spent
  writing its corpus was not cached by the harness, so per-writer writing cost
  -- the registered figure -- cannot be recovered and is reported missing.
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence


def analyse(cache: dict[str, Any]) -> dict[str, Any]:
    cells = cache["cells"]
    keys = [tuple(k.split("|")) for k in cells]
    seeds = sorted({int(s) for s, _, _ in keys})
    readers = sorted({r for _, r, _ in keys})
    writers = sorted({w for _, _, w in keys})
    models = [w for w in writers if w != "oracle"]

    # Retrieval must not depend on the reader.
    retrieval: dict[str, list[int]] = {}
    mismatches = []
    for w in writers:
        series = []
        for s in seeds:
            rows = {r: cells[f"{s}|{r}|{w}"]["right_in_context"] for r in readers}
            first = next(iter(rows.values()))
            if any(v != first for v in rows.values()):
                mismatches.append(f"seed {s} writer {w}")
            series.extend(first)
        retrieval[w] = series

    overlap = {}
    for a, b in itertools.combinations(models, 2):
        agree = sum(x == y for x, y in zip(retrieval[a], retrieval[b]))
        overlap[f"{a}|{b}"] = round(agree / len(retrieval[a]), 4)

    conversion = {}
    for r in readers:
        for w in writers:
            hit = succ = 0
            for s in seeds:
                cell = cells[f"{s}|{r}|{w}"]
                for got, ok in zip(cell["right_in_context"], cell["success"]):
                    if got:
                        hit += 1
                        succ += ok
            conversion[f"{r}<-{w}"] = round(succ / hit, 4) if hit else None

    def seconds(pred) -> dict[str, float]:
        xs = [cells[k]["seconds"] for k in cells if pred(tuple(k.split("|")))]
        return {"total_s": round(sum(xs), 1), "median_s": round(statistics.median(xs), 1),
                "max_s": round(max(xs), 1), "cells": len(xs)}

    return {
        "experiment": "x6-secondary",
        "seeds": seeds,
        "units": len(retrieval[writers[0]]),
        "retrieval_independent_of_reader": not mismatches,
        "retrieval_mismatches": mismatches,
        "right_in_context_by_writer": {
            w: round(sum(v) / len(v), 4) for w, v in retrieval.items()},
        "retrieval_agreement": overlap,
        "conversion": conversion,
        "cost_by_reader": {r: seconds(lambda k, r=r: k[1] == r) for r in readers},
        "read_time_by_corpus": {w: seconds(lambda k, w=w: k[2] == w) for w in writers},
        "writing_cost": None,  # not cached by the harness; see docstring
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = analyse(json.loads(Path(args.cache).read_text(encoding="utf-8")))
    text = json.dumps(result, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["retrieval_independent_of_reader"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
