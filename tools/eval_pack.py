"""Write a reproduction pack for an outside evaluator: every registered experiment, its command and its result hash.

    python tools/eval_pack.py --out dist/eval-pack

Writes `<out>/MANIFEST.json` and `<out>/REPRODUCE.md`: the commit, Python,
and for each pre-registered experiment the registration file, the exact
command that produced each committed result, and the sha256 of that result.
An evaluator reruns the commands on a clean checkout of the same commit and
compares the hashes (deterministic, seeded runs) or the numbers (runs that
call a local model). Nothing here is judged by this project; the pack only
makes re-running unambiguous.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPERIMENTS = [
    {"name": "GME matrix v1 (registered)", "prereg": "research/prereg/gme-matrix.md",
     "runs": [("python -m experiments.gme_matrix --seeds 1 2 3 4 5 --out OUT",
               "research/results/gme-matrix.json")],
     "deterministic": False,
     "note": "Rerun on the commit that produced it; later commits changed the product it measures."},
    {"name": "GME matrix v2", "prereg": "research/prereg/gme-matrix-v2.md",
     "runs": [("python -m experiments.gme_matrix --seeds 11 12 13 14 15 --budget 60 --out OUT",
               "research/results/gme-matrix-v2-b60.json"),
              ("python -m experiments.gme_matrix --seeds 11 12 13 14 15 --budget 400 --out OUT",
               "research/results/gme-matrix-v2-b400.json")],
     "deterministic": True, "note": ""},
    {"name": "Decay view (confirmation)", "prereg": "research/prereg/decay-view.md",
     "runs": [("python -m experiments.decay_eval --seeds 6 7 8 9 10 --out OUT",
               "research/results/decay-view-confirm.json")],
     "deterministic": True, "note": ""},
    {"name": "Decay view with a local model", "prereg": "research/prereg/decay-view.md",
     "runs": [("python -m experiments.decay_eval --seeds 11 12 13 14 15 --model qwen2.5:7b --out OUT",
               "research/results/decay-view-model.json")],
     "deterministic": False,
     "note": "Needs Ollama with qwen2.5:7b; temperature 0, but model builds differ, so compare numbers."},
    {"name": "Staging run", "prereg": None,
     "runs": [("MF_STAGING_POSTGRES_URL=postgresql://... python -m experiments.staging_run "
               "--model llama3.1:8b --out OUT", "research/results/staging-run.json")],
     "deterministic": False,
     "note": "Needs Ollama and PostgreSQL; operational, not pre-registered."},
    {"name": "Product benchmark", "prereg": None,
     "runs": [("python -m experiments.product_bench --out OUT",
               "research/results/product-bench.json")],
     "deterministic": False, "note": "Latency is machine-dependent; compare quality exactly."},
]


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "eval-pack")
    args = parser.parse_args(argv)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    entries = []
    for e in EXPERIMENTS:
        entries.append({**e, "runs": [{"command": cmd, "result": res,
                                       "sha256": sha256(ROOT / res)} for cmd, res in e["runs"]]})
    manifest = {"commit": commit, "python": platform.python_version(),
                "platform": platform.platform(), "experiments": entries}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    lines = [f"# Reproduction pack for `{commit[:12]}`", "",
             f"Check out this commit, `pip install -e .`, then run each command with `OUT` "
             f"replaced by a new file, and compare.", ""]
    for e in entries:
        lines += [f"## {e['name']}", ""]
        if e["prereg"]:
            lines.append(f"Registration: `{e['prereg']}`.")
        if e["note"]:
            lines.append(e["note"])
        lines.append("")
        for r in e["runs"]:
            lines += ["```bash", r["command"], "```",
                      f"Committed result `{r['result']}`, sha256 `{r['sha256']}`"
                      + (" (compare the file)" if e["deterministic"] else " (compare the numbers)"),
                      ""]
    (args.out / "REPRODUCE.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"pack: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
