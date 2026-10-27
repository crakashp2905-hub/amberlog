"""The benchmark registry (MF-031): every named suite, its source, licence state and run status.

    python -m benchmarks.registry validate --offline   # schema + arithmetic checks, no network

Validation is offline: it checks every field is present, every status is one
of the decision outputs, and recomputes each vendor table's stated token
reduction from its displayed totals, flagging a disagreement (masterplan
§7A.1 B: "never silently reproduce an inconsistent percentage").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "registry.json"
STATUSES = ("RUN", "NOT_RUN", "BLOCKED")
REQUIRED = ("id", "name", "url", "version", "license", "access", "run_status", "reason", "vendor_reported")


def load(path: Path = REGISTRY) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def token_reduction(before: float, after: float) -> float:
    return round(100 * (1 - after / before), 2)


def arithmetic(suite: dict[str, Any]) -> list[str]:
    """Disagreements between a vendor's stated token reduction and its own displayed totals."""
    vr = suite.get("vendor_reported") or {}
    stated = vr.get("stated_token_reduction_pct")
    arms = list((vr.get("arms") or {}).values())
    totals = [a.get("total_tokens_m") for a in arms]
    if stated is None or len(totals) != 2 or None in totals:
        return []
    computed = token_reduction(totals[0], totals[1])
    # A stated "64%" is rounded to a whole point; "61.38%" claims two decimals.
    # Allow the rounding the stated figure carries, and at least 0.05 points for
    # the rounding of the displayed totals.
    decimals = len(str(stated).split(".")[1]) if "." in str(stated) else 0
    if abs(computed - stated) > max(0.5 * 10 ** -decimals, 0.05):
        return [f"{suite['id']}: stated {stated}% token reduction, displayed totals "
                f"{totals[0]}M -> {totals[1]}M give {computed}%"]
    return []


def validate(data: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for suite in data.get("suites", []):
        sid = suite.get("id", "?")
        missing = [k for k in REQUIRED if k not in suite]
        if missing:
            problems.append(f"{sid}: missing {', '.join(missing)}")
        if suite.get("run_status") not in STATUSES:
            problems.append(f"{sid}: run_status must be one of {STATUSES}")
        if sid in seen:
            problems.append(f"{sid}: duplicate id")
        seen.add(sid)
        if suite.get("run_status") == "NOT_RUN" and not suite.get("reason"):
            problems.append(f"{sid}: NOT_RUN without a reason")
    return problems


def notes(data: dict[str, Any]) -> list[str]:
    return [n for s in data.get("suites", []) for n in arithmetic(s)]


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "validate":
        print(__doc__)
        return 2
    data = load()
    problems = validate(data)
    for p in problems:
        print(f"ERROR {p}")
    for n in notes(data):
        print(f"NOTE  {n}")
    print(f"{len(data['suites'])} suites; {sum(s['run_status'] == 'RUN' for s in data['suites'])} run")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
