"""Execute mapped GOV tests; existence alone is not conformance evidence.

Names can match several classes: run every match and report qualified IDs.
Declared PARTIAL/BLOCKED statuses are never upgraded by local passing tests.
"""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def flatten(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main() -> int:
    from benchmarks.manifest import head
    from tests.test_gov_conformance import GOV

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    loader = unittest.TestLoader()
    all_tests = list(flatten(loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))))
    by_name: dict[str, list[unittest.TestCase]] = {}
    for test in all_tests:
        by_name.setdefault(test.id().rsplit(".", 1)[-1], []).append(test)
    names = {name for _, mapped, _ in GOV.values() for name in mapped}
    missing = sorted(names - by_name.keys())
    selected = {test.id(): test for name in names for test in by_name.get(name, [])}
    result = unittest.TestResult()
    unittest.TestSuite(selected.values()).run(result)
    # Subtest IDs append parameters to their parent; the assertion must inherit
    # that failure rather than being labelled passed because IDs differ.
    failures = {test.id().split(" (")[0] for test, _ in result.failures + result.errors}
    skips = {test.id(): reason for test, reason in result.skipped}
    assertions = {}
    for gid, (declared, mapped, reason) in GOV.items():
        ids = sorted({test.id() for name in mapped for test in by_name.get(name, [])})
        outcome = "FAIL" if any(i in failures for i in ids) else (
            "INCOMPLETE" if any(n in missing for n in mapped) or any(i in skips for i in ids)
            else "LOCAL_TESTS_PASSED")
        assertions[gid] = dict(declared=declared, reason=reason, tests=ids, execution=outcome)
    data = dict(commit=head(), decision="FAIL" if failures or missing or loader.errors else "DESCRIPTIVE",
                scope="local mapped test execution; not independent review or physical-host qualification",
                discovery_errors=loader.errors, missing=missing, run=result.testsRun,
                failures=sorted(failures), skipped=skips, assertions=assertions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2)+"\n", encoding="utf-8")
    return int(bool(failures or missing or loader.errors))


if __name__ == "__main__":
    raise SystemExit(main())
