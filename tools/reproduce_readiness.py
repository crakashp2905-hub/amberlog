"""Collect portable zero-dependency replication evidence, never certify independence.

Run from a clean frozen checkout. No model endpoints, customer data or uploads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--quick", action="store_true", help="omit process/network and historical rollback drills")
    args = parser.parse_args()
    def git(*parts: str) -> str:
        return subprocess.check_output(["git", *parts], cwd=ROOT, text=True).strip()
    if git("status", "--porcelain", "--untracked-files=no"):
        parser.error("tracked source changes exist; use a clean checkout so the source SHA is meaningful")
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("output directory must be empty; preserve previous evidence instead of overwriting it")
    out.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    steps = [
        ("branding", [py, "tools/check_branding.py"]),
        ("secret-scan", [py, "tools/scan_secrets.py"]),
        ("regressions", [py, "-m", "unittest", "tests.test_three_agent", "tests.test_gov_conformance",
                         "tests.test_chains", "tests.test_security_regression", "tests.test_no_budget_rehearsal"]),
        ("three-agent", [py, "-m", "benchmarks.three_agent", "--out", str(out / "three-agent.json")]),
        ("conformance", [py, "tools/conformance_audit.py", "--out", str(out / "conformance.json")]),
    ]
    if not args.quick:
        steps += [("network-processes", [py, "-m", "experiments.multihost", "--latency-ms", "50",
                                         "--out", str(out / "network-processes.json")]),
                  ("rollback", [py, "-m", "experiments.rollback_drill", "--old-ref", "v0.11.0"])]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONHOME"}
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    manifest = {"source_commit": git("rev-parse", "HEAD"), "tracked_tree_clean": True,
                "python": platform.python_version(), "platform": platform.platform(),
                "profile": "quick" if args.quick else "full", "steps": [],
                "command_path_substitution": {"{OUTPUT}": "bundle output directory"},
                "independence": "NOT_ESTABLISHED", "external_review": "NOT_RUN",
                "physical_hosts": "NOT_ESTABLISHED", "customer_pilots": "NOT_RUN",
                "release_decision": "INCONCLUSIVE", "paid_model_calls": 0,
                "scope": "reproduction execution only; no automatic external acceptance"}
    for name, command in steps:
        started = time.perf_counter()
        try:
            done = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=900)
            code, log = done.returncode, done.stdout + done.stderr
        except subprocess.TimeoutExpired:
            code, log = 124, "Timed out after 900 seconds; no passing result inferred.\n"
        (out / f"{name}.log").write_text(log, encoding="utf-8")
        manifest["steps"].append({"name": name, "command": ["python", *(part.replace(str(out), "{OUTPUT}") for part in command[1:])],
                                  "exit_code": code, "elapsed_s": round(time.perf_counter() - started, 3)})
        print(f"{name}: {'PASS' if code == 0 else 'FAIL'}", flush=True)
    # Compare deterministic outcome counts, not platform-dependent timing.
    observed = out / "three-agent.json"
    reference = ROOT / "research/results/local-three-agent.json"
    match = False
    if observed.exists():
        def project(data: dict) -> list:
            return sorted((row["seed"], row["arm"], json.dumps(row["counts"], sort_keys=True))
                          for row in data["rows"])
        match = project(json.loads(observed.read_text())) == project(json.loads(reference.read_text()))
    manifest["frozen_reference_sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
    manifest["deterministic_outcomes_match"] = match
    manifest["execution_status"] = "PASS" if match and all(step["exit_code"] == 0 for step in manifest["steps"]) else "FAIL"
    manifest["files"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in sorted(out.iterdir()) if path.is_file()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return int(manifest["execution_status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
