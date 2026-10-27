"""One manifest of every recorded result, with what it can and cannot vouch for (masterplan E0, MF-032).

    python tools/results_manifest.py           # print a summary
    python tools/results_manifest.py --write   # rewrite research/results/MANIFEST.json

For each `research/results/*.json` it records the fields the masterplan asks
every result to carry (`experiment_id`, `git_sha`, `dataset_digest`,
`model_id`, `prompt_hash`, `seed`, `config`, `cost`, `verdict`) as far as the
file states them, and `null` where it does not. Nothing is inferred: a commit
named only in the companion `.md` is taken from there and marked as such; a
field no file states stays `null`, so a gap is visible rather than filled.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "research" / "results"
PREREG = ROOT / "research" / "prereg"
OUT = RESULTS / "MANIFEST.json"


def _prereg(stem: str) -> str | None:
    """The registration this result belongs to: the longest registration name it starts with,
    else the longest experiment id (the name's first part) it starts with. Ties break by name,
    so the answer never depends on directory order."""
    def best(key: Callable[[Path], str]) -> Path | None:
        found = [p for p in sorted(PREREG.glob("*.md"))
                 if stem == key(p) or stem.startswith(key(p) + "-")]
        return max(found, key=lambda p: (len(key(p)), p.name), default=None)

    path = best(lambda p: p.stem) or best(lambda p: p.stem.split("-")[0])
    return f"research/prereg/{path.name}" if path else None


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) not in (None, "", [], {}):
            return data[key]
    return None


def entry(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        data: Any = json.loads(raw)
    except ValueError:
        data = None
    d = data if isinstance(data, dict) else {}
    sha, sha_from = _first(d, "commit", "git_sha"), "json" if _first(d, "commit", "git_sha") else None
    md = path.with_suffix(".md")
    if sha is None and md.exists():
        found = re.search(r"commit `([0-9a-f]{7,40})`", md.read_text(encoding="utf-8"))
        if found:
            sha, sha_from = found[1], "md"
    verdict = _first(d, "verdict", "decision", "pass")
    model = _first(d, "model", "model_id")
    return {
        "experiment_id": path.stem,
        "file": f"research/results/{path.name}",
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "prereg": _prereg(path.stem),
        "git_sha": sha,
        "git_sha_source": sha_from,
        "dataset_digest": _first(d, "dataset_digest", "dataset_sha256"),
        "model_id": model if isinstance(model, str) else (json.dumps(model, sort_keys=True) if model else None),
        "prompt_hash": _first(d, "prompt_hash", "prompt_sha256"),
        "seed": _first(d, "seeds", "seed"),
        "config": _first(d, "config", "run", "budget"),
        "cost": _first(d, "cost", "usage", "cost_usd"),
        "verdict": verdict,
        "parsable": data is not None,
    }


def build() -> dict[str, Any]:
    rows = [entry(p) for p in sorted(RESULTS.glob("*.json")) if p.name != OUT.name]
    missing = {k: sum(1 for r in rows if r[k] is None)
               for k in ("git_sha", "prereg", "dataset_digest", "model_id", "prompt_hash", "seed", "cost", "verdict")}
    return {"generated_by": "tools/results_manifest.py", "results": len(rows),
            "missing_field_counts": missing, "rows": rows}


def render() -> str:
    return json.dumps(build(), indent=1, sort_keys=False, default=str) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--write" in argv:
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
    else:
        m = json.loads(text)
        print(json.dumps({"results": m["results"], "missing": m["missing_field_counts"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
