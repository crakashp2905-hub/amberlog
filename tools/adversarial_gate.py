"""The adversarial release gate: every attack family, every run, fail on any regression.

Each family names the tests that hold its invariant. The gate runs them all,
writes a per-family report and exits non-zero if any family fails, errors,
or has no tests at all: a family whose tests were deleted fails instead of
going quiet. CI runs it on every push (`.github/workflows/ci.yml`, job
`adversarial-gate`), and the release checklist requires it green on the
exact release commit.

    python tools/adversarial_gate.py [--report gate.json]

What it does not do, stated: it replays recorded attacks and model-free
checks. Attacks that need a model (G4, G4b, T2b's arms) are research runs
with pre-registrations, run against two local model families, not on every
push.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAMILIES: dict[str, tuple[str, ...]] = {
    "injection": ("tests.test_injection_patterns", "tests.test_directive"),
    "delayed_and_progressive_poisoning": ("tests.test_authority.DelayedActivation",
                                          "tests.test_poisonworld"),
    "laundering_through_summaries_tools_federation": (
        "tests.test_authority.TheBoundarySurvivesEveryTransformation",),
    "false_corroboration": ("tests.test_independence",),
    "cross_tenant_access_and_metadata_leakage": ("tests.test_identity",
                                                 "tests.test_metadata_leakage"),
    "stale_authorization_and_replay": ("tests.test_authority.ExactActionGrants",
                                       "tests.test_action_fence"),
    "authority_and_elevation": ("tests.test_authority.Elevation",
                                "tests.test_authority.OutcomesDoNotConferAuthority"),
    "offline_peers_and_recovery": ("tests.test_verified_recovery", "tests.test_source_notice",
                                   "tests.test_retraction_protocol", "tests.test_multihop_http",
                                   "tests.test_remote_offer"),
    "key_rotation_and_retired_keys": ("tests.test_key_rotation_drill",),
    "plain_false_claims": ("tests.test_validation",),
    "authorization_across_access_paths": ("tests.test_access_matrix",
                                          "tests.test_visibility_at_action"),
    "actions_under_crashes_and_timeouts": ("tests.test_action_crash",),
    "log_and_chain_rewrite_detection": ("tests.test_checkpoint_rewrite",),
    "production_cryptography": ("tests.test_crypto_profile",),
    "log_tampering": ("tests.test_integrity_chain", "tests.test_chains"),
    "privacy": ("tests.test_privacy_federation", "tests.test_receipts"),
    "resource_exhaustion": ("tests.test_limits",),
    "privilege_separation": ("tests.test_permissions",),
    "backup_tamper_and_restore": ("tests.test_backup_custody",),
    "objective_filters_never_drop_safety_evidence": (
        "tests.test_objective_v2.HardSoftUncertain",
        "tests.test_objective_v2.IrrelevantIsNotDeletable"),
}


def run_family(names: tuple[str, ...]) -> dict[str, object]:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    missing: list[str] = []
    for name in names:
        try:
            suite.addTests(loader.loadTestsFromName(name))
        except (ImportError, AttributeError) as exc:
            missing.append(f"{name}: {exc}")
    result = unittest.TestResult()
    started = time.perf_counter()
    suite.run(result)
    return {
        "tests": result.testsRun,
        "failures": [str(t) for t, _ in result.failures],
        "errors": [str(t) for t, _ in result.errors] + missing,
        "seconds": round(time.perf_counter() - started, 2),
        "passed": result.testsRun > 0 and result.wasSuccessful() and not missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    report = {family: run_family(names) for family, names in FAMILIES.items()}
    failed = [f for f, r in report.items() if not r["passed"]]
    for family, r in report.items():
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"{mark}  {family:48s} {r['tests']:4d} tests  {r['seconds']:6.2f}s")
        for line in [*r["failures"], *r["errors"]][:5]:  # type: ignore[misc]
            print(f"        {line}")
    if args.report:
        args.report.write_text(json.dumps({"families": report, "failed": failed}, indent=2),
                               encoding="utf-8")
    print(f"\n{'release gate FAILED: ' + ', '.join(failed) if failed else 'release gate passed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
