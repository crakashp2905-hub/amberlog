"""PUB-02 (tau-knowledge) pilot: tau2-bench banking_knowledge with Memory Fabric behind `KB_search` (local model, descriptive).

    python -m benchmarks.tau2_knowledge --tau2 DIR --arm fabric --model ollama/qwen2.5:3b --num-tasks 15
    python -m benchmarks.tau2_knowledge --summarise RESULTS_DIR

Arms share tau2's own agent, user simulator, tasks and grader; only the
knowledge tool differs:

- `no_knowledge`, `bm25`, `golden_retrieval`: tau2's own retrieval configs
  (golden is the oracle: the documents each task needs).
- `fabric`: the `bm25` config with `KB_search` replaced by a MemoryFabric
  holding every banking_knowledge document (lexical retrieval, same top-k).

The agent and the simulated user are the same small local model, and the
communicate-info scorer is tau2's substring scorer (its default is a model
judge). Both make absolute scores much lower than published ones; the arms are
comparable with each other only. Descriptive pilot, no threshold.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
K = 10
TAU2_ARMS = {"no_knowledge": "no_knowledge", "bm25": "bm25", "golden_retrieval": "golden_retrieval",
             "fabric": "bm25"}


def document_texts(docs_dir: Path) -> Iterator[tuple[str, str]]:
    for path in sorted(p for p in docs_dir.rglob("*") if p.is_file()):
        raw = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".json":
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                raw = "\n".join(f"{k}: {v}" for k, v in data.items() if isinstance(v, (str, int, float)))
        yield path.stem, raw


def install_fabric(docs_dir: Path) -> int:
    from memory_fabric import MemoryFabric
    from tau2.domains.banking_knowledge import retrieval_mixins

    fabric = MemoryFabric(":memory:", auto_activate=True, encrypt_content=False, recognise_copies=False,
                          retrieval="lexical")
    title: dict[str, str] = {}
    for name, text in document_texts(docs_dir):
        title[fabric.remember("kb", text or " ", scope="team")] = name

    def kb_search(self: Any, query: str) -> str:
        hits = fabric.retrieve("agent", query, k=K, min_relevance=0.0).exposed
        if not hits:
            return "No relevant documents found."
        return "\n\n".join(f"[{i + 1}] {title.get(m.id, m.id)}\n{m.content}" for i, m in enumerate(hits))

    kb_search.__doc__ = retrieval_mixins.KBSearchMixin.KB_search.__doc__
    retrieval_mixins.KBSearchMixin.KB_search = kb_search  # type: ignore[method-assign]
    return len(title)


def run(args: argparse.Namespace) -> int:
    if args.arm == "fabric":
        n = install_fabric(args.tau2 / "data" / "tau2" / "domains" / "banking_knowledge" / "documents")
        print(f"fabric KB_search installed over {n} documents", flush=True)
    from tau2.cli import main as tau2_main

    sys.argv = ["tau2", "run", "--benchmark", "none", "--domain", "banking_knowledge",
                "--retrieval-config", TAU2_ARMS[args.arm], "--agent-llm", args.model, "--user-llm", args.model,
                "--communicate-scorer", "substring", "--num-tasks", str(args.num_tasks), "--num-trials", "1",
                "--seed", "1", "--max-concurrency", "1", "--max-steps", "40", "--save-to", f"pub02-{args.arm}"]
    try:
        tau2_main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def rewards(x: Any) -> Iterator[tuple[str, float]]:
    """(task id, reward) for every simulation in a tau2 results file, wherever it nests."""
    if isinstance(x, dict):
        info = x.get("reward_info")
        if isinstance(info, dict) and isinstance(info.get("reward"), (int, float)) and "task_id" in x:
            yield str(x["task_id"]), float(info["reward"])
            return
        for v in x.values():
            yield from rewards(v)
    elif isinstance(x, list):
        for v in x:
            yield from rewards(v)


def summarise(results: Path) -> int:
    from benchmarks.manifest import Manifest, head
    from benchmarks.manifest import write as write_manifest

    arms: dict[str, dict[str, float]] = {}
    for f in sorted(results.rglob("*.json")):
        arm = next((a for a in TAU2_ARMS if f"pub02-{a}" in str(f)), None)
        if arm:
            arms.setdefault(arm, {}).update(dict(rewards(json.loads(f.read_text(encoding="utf-8")))))
    common = set.intersection(*(set(v) for v in arms.values())) if arms else set()
    table = {a: {"tasks": len(v), "pass_rate_common": round(sum(v[t] for t in common) / len(common), 4)
                 if common else None} for a, v in sorted(arms.items())}
    commit = head()[:12]
    data = {"commit": commit, "common_tasks": len(common), "arms": table, "seeds": [1]}
    print("=== PUB02 JSON ===")
    print(json.dumps(data))
    print("=== PUB02 END ===")
    (ROOT / "research" / "results" / "pub02-tau2-knowledge-local.json").write_text(
        json.dumps(data, indent=1) + "\n", encoding="utf-8")
    write_manifest(Manifest(
        run_id="pub02-tau2-knowledge-local", suite="PUB-02", arm=",".join(sorted(arms)), decision="DESCRIPTIVE",
        repo_commit=commit, reason="pilot; local 3B agent and user simulator, substring communicate scorer",
        dataset={"name": "tau2-bench banking_knowledge (MIT)"}, model={"provider": "ollama", "id": "qwen2.5:3b"},
        seeds=[1], counts={"attempted": len(common), "completed": len(common), "solved": 0, "skipped": 0, "failed": 0},
        results={"primary_metric": "pass rate on common tasks",
                 **{a: v["pass_rate_common"] for a, v in table.items()}},
        cost={"model_usd": 0.0}, verification={"baseline_registered": True, "oracle_sanity_passed": False,
                                                "holdout_frozen": True, "independent_replicated": False}))
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tau2", type=Path)
    p.add_argument("--arm", choices=list(TAU2_ARMS))
    p.add_argument("--model", default="ollama/qwen2.5:3b")
    p.add_argument("--num-tasks", type=int, default=15)
    p.add_argument("--summarise", type=Path)
    args = p.parse_args(argv)
    return summarise(args.summarise) if args.summarise else run(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
