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

from amberlog.governance import directive
from amberlog.governance.injection import InjectionDetector

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


def score(rows: list[tuple[str, int]], screen: object = None) -> dict[str, object]:
    out = {}
    screens = [("directive", lambda t: directive.assess(t).flagged),
               ("pattern", lambda t: bool(scan_injection(t))),
               ("either", lambda t: directive.assess(t).flagged or bool(scan_injection(t)))]
    if screen is not None:
        screens += [("model", lambda t: screen.assess(t).flagged),
                    ("text_or_model", lambda t: directive.assess(t).flagged
                     or bool(scan_injection(t)) or screen.assess(t).flagged)]
    for name, flag in screens:
        pos = [flag(t) for t, y in rows if y == 1]
        neg = [flag(t) for t, y in rows if y == 0]
        out[name] = {"recall": round(sum(pos) / len(pos), 3), "caught": sum(pos),
                     "injections": len(pos), "false_positive_rate": round(sum(neg) / len(neg), 3),
                     "flagged_benign": sum(neg), "benign": len(neg)}
    return out


def main(argv: list[str]) -> int:
    directory = Path(argv[0])
    model = argv[1] if len(argv) > 1 else None
    screen = None
    if model:
        from amberlog.adapters.claude_chat import make_client
        from amberlog.governance.model_screen import ModelScreen

        screen = ModelScreen(make_client(model), model)
    own = json.loads((ROOT / "research/bench/injection_heldout/heldout.json").read_text(encoding="utf-8"))
    own_rows = [(t, 1) for t in own["injections"]] + [(t, 0) for t in own["benign_hard_negatives"]]
    result = {"dataset": "deepset/prompt-injections", "model": model,
              "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                       capture_output=True, text=True, cwd=ROOT).stdout.strip(),
              "splits": {"test": score(load(directory, "test"), screen),
                         "own_heldout": score(own_rows, screen)}}
    if not model:
        result["splits"]["train"] = score(load(directory, "train"))
    out = OUT if not model else OUT.with_name(f"injection-thirdparty-{model.replace(':', '-')}.json")
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
