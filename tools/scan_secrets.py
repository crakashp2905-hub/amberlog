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

    # The adversarial corpus for the detector. Every value in it is invented,
    # shaped like a credential and not one -- which is the whole point of the
    # file: `SECURITY.md` records that the screen had never been tested
    # adversarially, and a corpus that tests it has to contain the shapes it
    # looks for. Allow-listed per kind rather than wholesale, so a *new* class
    # appearing there still has to be declared here.
    ("tests/test_sensitive_patterns.py", "private_key"),
    ("tests/test_sensitive_patterns.py", "aws_access_key"),
    ("tests/test_sensitive_patterns.py", "github_token"),
    ("tests/test_sensitive_patterns.py", "slack_token"),
    ("tests/test_sensitive_patterns.py", "anthropic_key"),
    ("tests/test_sensitive_patterns.py", "openai_key"),
    ("tests/test_sensitive_patterns.py", "jwt"),
    ("tests/test_sensitive_patterns.py", "google_api_key"),
    ("tests/test_sensitive_patterns.py", "google_oauth_secret"),
    ("tests/test_sensitive_patterns.py", "stripe_key"),
    ("tests/test_sensitive_patterns.py", "gitlab_token"),
    ("tests/test_sensitive_patterns.py", "huggingface_token"),
    ("tests/test_sensitive_patterns.py", "npm_token"),
    ("tests/test_sensitive_patterns.py", "sendgrid_key"),
    ("tests/test_sensitive_patterns.py", "twilio_sid"),
    ("tests/test_sensitive_patterns.py", "slack_webhook"),
    ("tests/test_sensitive_patterns.py", "connection_string"),
    ("tests/test_sensitive_patterns.py", "azure_storage_key"),
    ("tests/test_sensitive_patterns.py", "iban"),
    ("tests/test_sensitive_patterns.py", "ni_number_uk"),
    ("tests/test_sensitive_patterns.py", "password_assignment"),
    ("tests/test_sensitive_patterns.py", "credit_card"),
    ("tests/test_sensitive_patterns.py", "ssn_us"),
    ("tests/test_sensitive_patterns.py", "password_in_prose"),

    # Tests of the agent API and dashboard operators, whose subject is tokens:
    # the same reason test_auth.py is listed. Values are generated or repeated
    # characters, never real credentials.
    ("tests/test_agent_api.py", "password_assignment"),
    ("tests/test_operator_access.py", "password_assignment"),
    # Builds database URLs around a random per-run password to prove the CLI
    # never prints one. The value is generated at test time; the fixture is
    # the URL shape.
    ("tests/test_postgres.py", "password_assignment"),
    ("tests/test_postgres.py", "connection_string"),

    # The obfuscation red team: invented values deliberately disguised -- split,
    # encoded, look-alike characters -- so the detector's variant scan can be
    # shown to catch them. A corpus that tests evasion has to contain evasions.
    ("tests/test_sensitive_redteam.py", "aws_access_key"),
    ("tests/test_sensitive_redteam.py", "password_in_prose"),
    ("tests/test_sensitive_redteam.py", "private_key"),

    # This file names the fixtures it allows, so it matches its own patterns.
    ("tools/scan_secrets.py", "password_assignment"),
    ("tools/scan_secrets.py", "credit_card"),
    ("tools/scan_secrets.py", "aws_access_key"),
    ("tools/scan_secrets.py", "ssn_us"),
}


# Narrower than ALLOWED_LINES: a (path, kind, substring) triple exempts only
# lines containing that substring. Added for Phase 3, where `ExposureToken` is
# a first-class domain object — the roadmap's own term — and the
# `password_assignment` rule fires on `token: ExposureToken` and
# `token = self.enforcer.issue(...)`. Exempting `password_assignment` for the
# whole of fabric.py would leave a real hole in a 1,200-line module, and
# renaming the concept to dodge a detector would be worse naming for a cosmetic
# reason.
ALLOWED_SNIPPETS = {
    # A placeholder for a stubbed HTTP transport: the SDK requires *some*
    # credential to build a client, and no request leaves the process.
    ("tests/test_claude_contract.py", "password_assignment", "api_key=STUB_KEY"),
    ("memory_fabric/enforcement.py", "password_assignment", "ExposureToken"),
    ("memory_fabric/enforcement.py", "password_assignment", "token.expired"),
    ("memory_fabric/fabric.py", "password_assignment", "ExposureToken"),
    ("memory_fabric/fabric.py", "password_assignment", "self.enforcer.issue"),
    ("memory_fabric/fabric.py", "password_assignment", "token=token, memory=memory"),
    ("tests/test_enforcement.py", "password_assignment", "enforcer.issue"),
    ("memory_fabric/transport.py", "password_assignment", "retraction.sign"),
    ("memory_fabric/sdk.py", "password_assignment", "ExposureToken"),
    ("memory_fabric/sdk.py", "password_assignment", "read.token"),
    # Named dashboard operators: the code parses and passes tokens by name.
    ("memory_fabric/observability/auth.py", "password_assignment", "token=token,"),
    ("memory_fabric/observability/auth.py", "password_assignment", "name, sep, token = line.partition"),
    ("memory_fabric/observability/auth.py", "password_assignment", "name, token = name.strip()"),
    ("memory_fabric/observability/server.py", "password_assignment", "token='<your-token>'"),
}


def is_allowed(path: str, kind: str, raw: str, line_text: str = "") -> bool:
    if (path, kind) in ALLOWED_LINES:
        return True
    for allowed_path, allowed_kind, snippet in ALLOWED_SNIPPETS:
        if path == allowed_path and kind == allowed_kind and snippet in line_text:
            return True
    stripped = raw.strip()
    if stripped in ALLOWED_VALUES:
        return True
    return any(stripped.startswith(p) for p in ALLOWED_PREFIXES)


def _gitignored(root: Path) -> set[str]:
    """Paths git will not commit, so the scan does not audit them.

    This exists because of a false positive that was really a scope error.
    Downloading LongMemEval produced **ten high-severity findings inside a
    chat corpus** -- simulated conversations in which people discuss passwords
    and tokens, and one containing a `-----BEGIN` block. All real matches, all
    in a 277 MB file that is gitignored and can never be committed.

    The scan's purpose is "nothing secret reaches the repository", and a file
    git will not take cannot. Auditing it buries the findings that matter: ten
    lines of noise against 59 allow-listed fixtures, and a reader who learns to
    skim this output has lost the tool.

    Falls back to scanning everything if git is unavailable, because the safe
    failure for a secret scanner is to look at more rather than less.
    """
    import subprocess

    try:
        done = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--ignored",
             "--exclude-standard", "--directory"],
            capture_output=True, text=True, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError):
        return set()
    out: set[str] = set()
    for line in done.stdout.splitlines():
        entry = line.strip().rstrip("/")
        if not entry:
            continue
        candidate = root / entry
        if candidate.is_dir():
            for child in candidate.rglob("*"):
                if child.is_file():
                    out.add(child.relative_to(root).as_posix())
        else:
            out.add(entry)
    return out


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

    ignored = _gitignored(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.relative_to(root).as_posix() in ignored:
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
            line_start = text.rfind(chr(10), 0, finding.start) + 1
            line_end = text.find(chr(10), finding.end)
            line_text = text[line_start : line_end if line_end != -1 else len(text)]
            if not is_allowed(relative, finding.kind, raw, line_text):
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
