"""Re-run every recorded deterministic, model-free result at HEAD and compare (masterplan E0).

    python tools/reverify.py              # all entries; writes research/results/REVERIFY.{md,json}
    python tools/reverify.py s1 p3b       # some

Each experiment runs in a throwaway `git worktree` of HEAD, so whatever a
harness writes into its own `research/results/` lands in that copy, never in
this one (a re-run must not overwrite the record it is checked against). The
fresh JSON is compared with the recorded one leaf by leaf: every number and
string under the same path, ignoring run metadata (commit, timings, machine).
A difference is reported with its paths; it is not judged here. Two registered
results regressed silently before this existed (S1 convergence, P3b success).

Model-backed results are not re-run (they would need the model and spend).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "research" / "results" / "REVERIFY.md"
OUT_JSON = ROOT / "research" / "results" / "REVERIFY.json"
VOLATILE = {"commit", "wall_s", "seconds", "elapsed_s", "machine", "python", "platform", "run",
            "latency_ms", "p50_ms", "p95_ms", "p99_ms", "built_at", "note", "base_ref", "time_s",
            "duration_s", "throughput", "ops_per_s", "hold_suspicious"}

# id: (recorded result, command; "{out}" is a JSON path inside the worktree when the
# harness takes --out, else the harness writes research/results/<recorded>.json itself)
ENTRIES: dict[str, tuple[str, list[str]]] = {
    "s1": ("s1-correction-sim", ["-m", "experiments.s1_correction_sim", "--seeds", "20", "--out", "{out}"]),
    "s2": ("s2-launder-sim", ["-m", "experiments.s2_launder_sim", "--split", "test", "--out", "{out}"]),
    "s2-dev": ("s2-launder-sim-dev", ["-m", "experiments.s2_launder_sim", "--split", "dev", "--out", "{out}"]),
    "s4": ("s4-transfer-sim", ["-m", "experiments.s4_transfer_sim", "--split", "test", "--out", "{out}"]),
    "s5": ("s5-receipt-leakage-after-f13", ["-m", "experiments.s5_receipt_leakage", "--out", "{out}"]),
    "s6": ("s6-race-sim", ["-m", "experiments.s6_race_sim", "--out", "{out}"]),
    "t1": ("t1-staleness", ["-m", "experiments.t1_staleness", "--split", "test", "--out", "{out}"]),
    "c1-dev": ("c1-compaction-dev", ["-m", "experiments.c1_compaction", "--split", "dev"]),
    "c1-test": ("c1-compaction-test", ["-m", "experiments.c1_compaction", "--split", "test"]),
    "c2": ("c2-dependence", ["-m", "experiments.c2_dependence"]),
    "c2r": ("c2r-dependence", ["-m", "experiments.c2_dependence", "6", "7", "8", "9", "10"]),
    "l1": ("l1-long-running", ["-m", "experiments.l1_long_running"]),
    "l1p": ("l1p-long-running", ["-m", "experiments.l1_long_running", "--amended"]),
    "o1": ("o1-typed-claims", ["-m", "experiments.o1_typed_claims"]),
    "p1b": ("p1b-links", ["-m", "experiments.p1b_links"]),
    "p1c": ("p1c-strength", ["-m", "experiments.p1c_strength"]),
    "p2b": ("p2b-budget", ["-m", "experiments.p2b_budget"]),
    "p9": ("p9-incidents", ["-m", "experiments.p9_incidents"]),
    "p10": ("p10-audit", ["-m", "experiments.p10_audit"]),
    "paraphrase": ("paraphrase-links", ["-m", "experiments.paraphrase_links"]),
    "v1-dev": ("v1-claim-validation-dev", ["-m", "experiments.v1_claim_validation", "--split", "dev"]),
    "v1-test": ("v1-claim-validation-test", ["-m", "experiments.v1_claim_validation", "--split", "test"]),
    "v2": ("v2-codes", ["-m", "experiments.v2_codes", "--out", "v2-codes"]),
    "v2-amend1": ("v2-codes-amend1", ["-m", "experiments.v2_codes", "--seeds", "700", "705", "--out", "v2-codes-amend1"]),
    "e1": ("e1-exhaustive-enumeration", ["-m", "benchmarks.enumeration"]),
    "int01": ("int01-memoryworld2", ["-m", "benchmarks.memoryworld2"]),
    "int04": ("int04-compaction-drilldown", ["-m", "benchmarks.compaction"]),
}


def leaves(x: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(x, dict):
        for k, v in x.items():
            if k not in VOLATILE:
                yield from leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from leaves(v, f"{path}[{i}]")
    else:
        yield path, x


def compare(recorded: Any, fresh: Any) -> list[str]:
    a, b = dict(leaves(recorded)), dict(leaves(fresh))
    diffs = []
    for key in sorted(set(a) | set(b)):
        x, y = a.get(key, "<absent>"), b.get(key, "<absent>")
        if isinstance(x, float) and isinstance(y, (int, float)) and not isinstance(y, bool):
            if abs(x - y) <= 1e-9 * max(1.0, abs(x)):
                continue
        elif x == y:
            continue
        diffs.append(f"{key}: {x!r} -> {y!r}")
    return diffs


def run(ids: list[str]) -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="reverify-"))
    wt = tmp / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(wt), "HEAD"], cwd=ROOT, check=True)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    report: dict[str, Any] = {"commit": head, "entries": {}}
    try:
        for eid in ids:
            name, cmd = ENTRIES[eid]
            out = tmp / f"{eid}.json"
            argv = [sys.executable, *[str(out) if c == "{out}" else c for c in cmd]]
            started = time.time()
            done = subprocess.run(argv, cwd=wt, capture_output=True, text=True, timeout=3600)
            fresh_path = out if out.exists() else wt / "research" / "results" / f"{name}.json"
            recorded = json.loads((ROOT / "research" / "results" / f"{name}.json").read_text(encoding="utf-8"))
            entry: dict[str, Any] = {"result": name, "seconds": round(time.time() - started, 1),
                                     "recorded_commit": recorded.get("commit")}
            if not fresh_path.exists():
                entry.update(status="ERROR", detail=(done.stderr or done.stdout)[-600:])
            else:
                diffs = compare(recorded, json.loads(fresh_path.read_text(encoding="utf-8")))
                entry.update(status="IDENTICAL" if not diffs else "DIFFERS", differences=diffs[:40],
                             n_differences=len(diffs))
            report["entries"][eid] = entry
            print(f"{eid:12s} {entry['status']:10s} {entry.get('n_differences', '')}", flush=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT)
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def render(report: dict[str, Any]) -> str:
    lines = ["# Re-verification at HEAD", "",
             f"Generated by `tools/reverify.py` at commit `{report['commit']}`: every recorded deterministic, "
             "model-free result re-run in a throwaway worktree and compared leaf by leaf with its record "
             "(run metadata ignored). A difference is a finding to explain, not a verdict.", "",
             "| entry | result | recorded at | status | differences |", "|---|---|---|---|---|"]
    for eid, e in report["entries"].items():
        lines.append(f"| {eid} | [{e['result']}]({e['result']}.md) | `{e['recorded_commit']}` | "
                     f"{e['status']} | {e.get('n_differences', '—')} |")
    for eid, e in report["entries"].items():
        if e["status"] != "IDENTICAL":
            lines += ["", f"## {eid}", ""]
            lines += [f"- `{d}`" for d in e.get("differences", [])] or [f"```\n{e.get('detail', '')}\n```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    ids = [a for a in argv if a in ENTRIES] or list(ENTRIES)
    report = run(ids)
    if not [a for a in argv if a in ENTRIES]:
        OUT_JSON.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        OUT_MD.write_text(render(report), encoding="utf-8")
    else:
        print(json.dumps(report, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
