"""Reject retired product spellings in the current tracked tree, not Git history."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    # Code points let the acceptance rule itself satisfy the removal contract.
    retired = re.compile("".join(map(chr, (97, 109, 98, 101, 114, 108, 111, 103))), re.IGNORECASE)
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
    print(f"Memory Fabric branding: {len(set(violations))} files with retired spellings")
    for name in sorted(set(violations)):
        print(f"  {name}")
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
