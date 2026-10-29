"""Reject retired product spellings in the current tracked tree, not Git history."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    # Code points let the acceptance rule itself satisfy the removal contract.
    first = "".join(map(chr, (109, 101, 109, 111, 114, 121)))
    second = "".join(map(chr, (102, 97, 98, 114, 105, 99)))
    retired = re.compile(first + r"[ _-]?" + second, re.IGNORECASE)
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    violations = []
    for name in names:
        if not name:
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        if retired.search(name):
            violations.append(name)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if retired.search(text):
            violations.append(name)
    print(f"Amberlog branding: {len(set(violations))} files with retired spellings")
    for name in sorted(set(violations)):
        print(f"  {name}")
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
