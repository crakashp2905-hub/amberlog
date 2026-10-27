"""One run manifest schema for every suite (MF-032), with the decision outputs of §7A.12.

A manifest is written for every run, including runs that did not happen:
`NOT_RUN` and `BLOCKED` carry their reason, so a missing result is a recorded
fact rather than an absence. `validate` refuses a manifest that claims more
than it shows: a PASS without a registered baseline or a passed oracle sanity
check, a result without a commit, a cost per safe success with no safe
success.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "mf-run-manifest/1"
DECISIONS = ("PASS", "FAIL", "INCONCLUSIVE", "INVALID", "NOT_RUN", "BLOCKED", "DESCRIPTIVE")
ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "research" / "results" / "bench_runs"


def head() -> str:
    done = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT)
    return done.stdout.strip() if done.returncode == 0 else ""


@dataclass
class Manifest:
    run_id: str
    suite: str
    arm: str
    decision: str
    repo_commit: str = ""
    reason: str = ""
    dataset: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] = field(default_factory=lambda: {"provider": None, "id": None})
    budget: dict[str, Any] = field(default_factory=dict)
    seeds: list[int] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"attempted": 0, "completed": 0, "solved": 0,
                                                             "skipped": 0, "failed": 0})
    results: dict[str, Any] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, bool] = field(default_factory=lambda: {
        "baseline_registered": False, "oracle_sanity_passed": False, "holdout_frozen": False,
        "independent_replicated": False})
    prereg: str | None = None
    schema: str = SCHEMA

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def validate(m: Manifest | dict[str, Any]) -> list[str]:
    d = m.to_json() if isinstance(m, Manifest) else m
    problems = []
    if d.get("schema") != SCHEMA:
        problems.append("unknown schema")
    if d.get("decision") not in DECISIONS:
        problems.append(f"decision must be one of {DECISIONS}")
    ran = d.get("decision") not in ("NOT_RUN", "BLOCKED")
    if not ran and not d.get("reason"):
        problems.append(f"{d.get('decision')} needs a reason")
    if ran and not d.get("repo_commit"):
        problems.append("a run must name the commit it ran on")
    if d.get("decision") == "PASS":
        v = d.get("verification", {})
        if not v.get("baseline_registered") or not v.get("oracle_sanity_passed"):
            problems.append("PASS needs a registered baseline and a passed oracle sanity check")
        if not d.get("prereg"):
            problems.append("PASS needs a preregistration")
    c = d.get("counts", {})
    if c.get("solved", 0) > c.get("attempted", 0):
        problems.append("more solved than attempted")
    cps = d.get("cost", {}).get("cost_per_safe_success")
    if cps is not None and not d.get("counts", {}).get("safe_solved", c.get("solved", 0)):
        problems.append("cost per safe success with no safe success")
    return problems


def write(m: Manifest, directory: Path = RUNS) -> Path:
    problems = validate(m)
    if problems:
        raise ValueError("; ".join(problems))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{m.run_id}.json"
    path.write_text(json.dumps(m.to_json(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_all(directory: Path = RUNS) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"), key=lambda p: p.name)]
