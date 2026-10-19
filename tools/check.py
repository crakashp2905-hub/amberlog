"""Run the checks CI's quick jobs run, before you push.

    python tools/check.py           # regenerate docs, lint, type-check, doc tests, gate
    python tools/check.py --full    # also the whole unit suite

Generated documents are regenerated first (STABILITY.md tiers, cited test
counts), because a forgotten regeneration is the commonest CI failure in
this repository's history. Exits non-zero on the first failing step.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

STEPS = [
    ("regenerate STABILITY.md", [PY, "tools/gen_stability.py"]),
    ("regenerate API and CLI references", [PY, "tools/gen_reference.py"]),
    ("regenerate cited test counts", [PY, "tools/count_tests.py", "--write"]),
    ("ruff", [PY, "-m", "ruff", "check"]),
    ("mypy", [PY, "-m", "mypy"]),
    ("secret scan", [PY, "tools/scan_secrets.py"]),
    ("document tests", [PY, "-m", "unittest", "tests.test_stability", "tests.test_suite_hygiene",
                        "tests.test_doc_links", "tests.test_doc_index", "tests.test_doc_examples",
                        "tests.test_reference_docs", "tests.test_troubleshooting",
                        "tests.test_examples_run", "tests.test_user_docs_no_research",
                        "tests.test_data_access_paths"]),
    ("adversarial gate", [PY, "tools/adversarial_gate.py"]),
]


def main(argv: list[str]) -> int:
    steps = STEPS + ([("unit suite", [PY, "-m", "unittest", "discover", "-s", "tests", "-t", "."])]
                     if "--full" in argv else [])
    for name, cmd in steps:
        print(f"--> {name}", flush=True)
        done = subprocess.run(cmd, cwd=ROOT)
        if done.returncode != 0:
            print(f"FAILED: {name}")
            return done.returncode
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
