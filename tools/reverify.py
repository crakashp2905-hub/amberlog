"""Re-run every recorded deterministic, model-free result at HEAD and compare (masterplan E0).

    python tools/reverify.py              # all entries; writes research/results/REVERIFY.{md,json}
    python tools/reverify.py s1 p3b       # some
    python tools/reverify.py p9 --at REV  # some, at an older commit (bisecting a difference)

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
import re
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

TIMING = re.compile(r"(_ms|_s|_ms_p\d+|_s_p\d+|_per_s|_wait_\w+)$")

# id: (recorded result, command; "{out}" is a JSON path inside the worktree when the
# harness takes --out, else the harness writes research/results/<recorded>.json itself)
ENTRIES: dict[str, tuple[str, list[str]]] = {
    "s1": ("s1-correction-sim", ["-m", "experiments.s1_correction_sim", "--seeds", "20", "--out", "{out}"]),
    "s2": ("s2-launder-sim", ["-m", "experiments.s2_launder_sim", "--split", "test", "--tau", "overlap@0.9",
                                 "--out", "{out}"]),
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

# Each remaining difference traced to its commit (`--at` bisection) and explained.
# A new difference has no note and shows as unexplained until someone writes one.
EXPLAINED: dict[str, str] = {
    "s1": "Baseline arm `delete_and_reshare` only (the method arm `versioned` is identical). Since 0d42e4a "
          "claim validation is on by default; when the origin deletes and re-writes a fact as a *new* memory "
          "whose value it had withdrawn earlier, the write is `reasserts_corrected` and held, so recipients "
          "miss it (confirmed: with that signal off, seed 2 returns to 982 correct, 0 missing). Intended: a "
          "new memory restating a withdrawn value is what the check exists to hold; revising the same memory "
          "(`versioned`) is not held (fixed in 3b2b35b).",
    "s5": "Not deterministic by construction: receipts use fresh random keys and nonces, so the per-feature "
          "distinguisher advantages move run to run. It differs the same way at its own recorded commit "
          "ab3861a. Every advantage stays within the registered bound.",
    "s6": "Timing-dependent: real threads race, so which actions land inside an overrun changes per run (two "
          "runs at the same commit gave 384 and 392 differences). Wait times and throughput are machine "
          "measurements.",
    "c1-dev": "Since 0d42e4a (claim validation on by default) the planted conflicting write is held for review "
              "instead of being stored as a visible dispute, so `dispute_shown` falls to 0 and one fact in 160 "
              "is missing from every arm alike. Registered verdicts are unchanged: stale exposure stays 0 for "
              "the governed arm; at 80 words compacted 0.973 against raw_episode 0.929 (non-inferiority holds).",
    "c1-test": "Same cause and same verdicts as c1-dev.",
    "c2": "The record is the run that found the `min_independent_sources` defect (its page says so); the "
          "defect was fixed before 125f838 and the counterfactual now finds every dependent decision "
          "(recall 1.0). The registered replication after the fix, c2r, is IDENTICAL.",
    "v2": "`fixed.risk_two_codes` fell from 1.0 to 0.02 and `before_fix.honest_other_parameter` to 0: the "
          "claim parser that reached main in 3d0f614 (PR #7) no longer takes the first of two codes as the "
          "subject, the risk this family measured. The V2 verdicts (detection 1.0, false alarms 0) are "
          "unchanged.",
    "v2-amend1": "Same cause as v2.",
}

def leaves(x: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(x, dict):
        for k, v in x.items():
            if k not in VOLATILE and not TIMING.search(k):
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
            if abs(x - y) <= 1e-9 * max(1.0, abs(x)) or (x != x and y != y):
                continue
        elif x == y or (isinstance(x, float) and isinstance(y, float) and x != x and y != y):
            continue
        diffs.append(f"{key}: {x!r} -> {y!r}")
    return diffs


def run(ids: list[str], rev: str = "HEAD") -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="reverify-"))
    wt = tmp / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(wt), rev], cwd=ROOT, check=True)
    head = subprocess.run(["git", "rev-parse", "--short", rev], cwd=ROOT, capture_output=True,
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
                # Keys only the fresh run has (a harness that grew a field) are counted
                # apart: they cannot have changed a recorded number.
                added = [d for d in diffs if ": '<absent>' -> " in d]
                changed = [d for d in diffs if d not in added]
                status = "IDENTICAL" if not changed else ("EXPLAINED" if eid in EXPLAINED else "DIFFERS")
                entry.update(status=status, differences=changed[:40], n_differences=len(changed),
                             n_added_fields=len(added))
            report["entries"][eid] = entry
            print(f"{eid:12s} {entry['status']:10s} {entry.get('n_differences', '')} "
              f"(+{entry.get('n_added_fields', 0)} new fields)", flush=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT)
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def render(report: dict[str, Any]) -> str:
    lines = ["# Re-verification at HEAD", "",
             f"Generated by `tools/reverify.py` at commit `{report['commit']}`: every recorded deterministic, "
             "model-free result re-run in a throwaway worktree and compared leaf by leaf with its record "
             "(run metadata and timings ignored; fields a harness added since are counted apart). A "
             "difference is bisected with `--at` and explained below; DIFFERS means not yet explained.", "",
             "| entry | result | recorded at | status | differences |", "|---|---|---|---|---|"]
    for eid, e in report["entries"].items():
        lines.append(f"| {eid} | [{e['result']}]({e['result']}.md) | `{e['recorded_commit']}` | "
                     f"{e['status']} | {e.get('n_differences', '—')} |")
    for eid, e in report["entries"].items():
        if e["status"] != "IDENTICAL":
            lines += ["", f"## {eid}", ""]
            if eid in EXPLAINED:
                lines += [EXPLAINED[eid], ""]
            lines += [f"- `{d}`" for d in e.get("differences", [])[:12]] or [f"```\n{e.get('detail', '')}\n```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    rev = argv[argv.index("--at") + 1] if "--at" in argv else "HEAD"
    ids = [a for a in argv if a in ENTRIES] or list(ENTRIES)
    report = run(ids, rev)
    if rev == "HEAD" and not [a for a in argv if a in ENTRIES]:
        OUT_JSON.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        OUT_MD.write_text(render(report), encoding="utf-8")
    else:
        print(json.dumps(report, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
