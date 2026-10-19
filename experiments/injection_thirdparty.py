"""The directive detector and the pattern screen on a third-party injection set.

deepset/prompt-injections (Apache-2.0, Hugging Face): short texts labelled
injection (1) or benign (0), English and German. Fetched as JSON rows from the
datasets server into a directory of its own; nothing in it is executed. Neither
screen was tuned on it.

It is a *chat* injection set ("ignore the above and ..."), not a set of
poisoned memories, so it tests transfer to a neighbouring task. A miss here is
an injection a memory could still carry.

    python -m experiments.injection_thirdparty DIR      # DIR holds {train,test}-*.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from memory_fabric.governance import directive
from memory_fabric.governance.injection import InjectionDetector

_PATTERNS = InjectionDetector()


def scan_injection(text: str) -> list:
    return _PATTERNS.scan(text)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research" / "results" / "injection-thirdparty.json"


def load(directory: Path, split: str) -> list[tuple[str, int]]:
    rows = []
    for f in sorted(directory.glob(f"{split}-*.json")):
        rows += [(r["row"]["text"], int(r["row"]["label"]))
                 for r in json.loads(f.read_text(encoding="utf-8")).get("rows", [])]
    return rows


def score(rows: list[tuple[str, int]]) -> dict[str, object]:
    out = {}
    for name, flag in (("directive", lambda t: directive.assess(t).flagged),
                       ("pattern", lambda t: bool(scan_injection(t))),
                       ("either", lambda t: directive.assess(t).flagged or bool(scan_injection(t)))):
        pos = [flag(t) for t, y in rows if y == 1]
        neg = [flag(t) for t, y in rows if y == 0]
        out[name] = {"recall": round(sum(pos) / len(pos), 3), "caught": sum(pos),
                     "injections": len(pos), "false_positive_rate": round(sum(neg) / len(neg), 3),
                     "flagged_benign": sum(neg), "benign": len(neg)}
    return out


def main(argv: list[str]) -> int:
    directory = Path(argv[0])
    result = {"dataset": "deepset/prompt-injections",
              "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                       capture_output=True, text=True, cwd=ROOT).stdout.strip(),
              "splits": {s: score(load(directory, s)) for s in ("test", "train")}}
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
