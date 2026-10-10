"""Point the project's own detector at the repository.

Two jobs at once: it guards what gets committed, and it is a standing smoke
test of the detector against a large body of real text. Both of the false
positives in the allowlist below were found that way.

It found a third, worth recording because it is a property of the detector
rather than of this repository: the `credit_card` rule fires on long digit runs
that satisfy the Luhn check, and full-precision float repr produces them freely
— `173.18333333333334` is a fourteen-digit run. A saved experiment record
tripped it 110 times. The fix was to round the floats on the way in rather than
to exempt the file, because a blanket exemption on a results directory would
also stop the scanner finding a real key in one.

    python tools/scan_secrets.py            # fail on anything unexpected
    python tools/scan_secrets.py --report   # list everything it sees
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory_fabric.governance.sensitive import SensitiveDataDetector

SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "dist", "build", ".github"}
SKIP_SUFFIXES = {".db", ".pyc", ".whl"}

# Fixtures the governance layer exists to catch. Each is a documented
# placeholder, not a credential: AWS's own example key, the standard test card,
# an example SSN, and synthetic tokens in the auth tests.
ALLOWED_VALUES = {
    "AKIAIOSFODNN7EXAMPLE",
    "4242424242424242",
    "123-45-6789",
}
ALLOWED_PREFIXES = ("ghp_aaa", "ghp_bbb", "ghp_ccc", "ghp_ddd", "ghp_eee",
                    "sk-ant-xxx", "test-token-", "demo-token-", "packaging-check")

# Declared file-and-kind pairs. Deliberately *not* a blanket exemption for
# `tests/`: a credential committed to a new test file should still fail. Each
# pair below is a file whose job involves carrying synthetic secrets, plus the
# specific kind it is allowed to carry.
ALLOWED_LINES = {
    # Our own detector's false positives, kept visible rather than silenced:
    # a statistical constant whose digits satisfy the Luhn check, and
    # `token=args.token`, which is code rather than an assignment of a secret.
    ("memory_fabric/estimators.py", "credit_card"),
    ("memory_fabric/cli.py", "password_assignment"),

    # These test the auth layer and the detector itself, so synthetic
    # credentials are the subject matter.
    ("tests/test_auth.py", "password_assignment"),
    ("tests/test_governance.py", "password_assignment"),
    ("tests/test_governance.py", "private_key"),
    ("tests/test_governance.py", "ssn_us"),
    ("tests/test_governance.py", "credit_card"),

    # This file names the fixtures it allows, so it matches its own patterns.
    ("tools/scan_secrets.py", "password_assignment"),
    ("tools/scan_secrets.py", "credit_card"),
    ("tools/scan_secrets.py", "aws_access_key"),
    ("tools/scan_secrets.py", "ssn_us"),
}


def is_allowed(path: str, kind: str, raw: str) -> bool:
    if (path, kind) in ALLOWED_LINES:
        return True
    stripped = raw.strip()
    if stripped in ALLOWED_VALUES:
        return True
    return any(stripped.startswith(p) for p in ALLOWED_PREFIXES)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan the repo for secrets")
    parser.add_argument("--report", action="store_true", help="list every finding")
    args = parser.parse_args()

    # Entropy off: it flags every hash, ULID and base64 blob in the repository,
    # which is noise at this scale. Pattern rules carry the signal.
    detector = SensitiveDataDetector(check_entropy=False)
    root = Path(__file__).resolve().parent.parent
    unexpected: list[tuple[str, int, str, str]] = []
    seen = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        relative = path.relative_to(root).as_posix()
        for finding in detector.scan(text):
            if finding.severity != "high":
                continue
            seen += 1
            raw = text[finding.start : finding.end]
            line = text[: finding.start].count("\n") + 1
            if args.report:
                print(f"  {relative}:{line}  {finding.kind}  {finding.excerpt}")
            if not is_allowed(relative, finding.kind, raw):
                unexpected.append((relative, line, finding.kind, finding.excerpt))

    print(f"scanned: {seen} high-severity findings, {len(unexpected)} unexpected")
    for relative, line, kind, excerpt in unexpected:
        print(f"  UNEXPECTED {relative}:{line}  {kind}  {excerpt}")
    if unexpected:
        print("\nIf one of these is a deliberate test fixture, add it to "
              "ALLOWED_* in tools/scan_secrets.py with a reason.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
