"""A real Claude model using the fabric over MCP, scored from the event log.

The P3 gate asked for the agent loop against a live provider. `claude.py` needs
an API key this environment does not have; Claude Code does not, so this drives
a headless Claude Code process whose **only** tools are the fabric's MCP server.
The model decides on its own when to recall, verify and remember.

Two arms, `--trials` runs each, a fresh store per run:

* **control** — a validated memory says what to do about fault E01. The model
  should recall it, verify it, and recommend it.
* **retracted** — the same, but a watcher process quarantines the memory
  through the real CLI the moment the model's recall is logged. The model's
  `verify` must come back unusable, and the model must not recommend it.

Scoring is from the store's own log, never from what the model says it did
(AGENTS.md: outcomes are never self-reported):

* `recalled`  — an ExposureDecided event exposed the seed memory to the agent
* `refused`   — an AccessDenied event for the seed memory (the verify refusal)
* `remembered`— a MemoryCreated event attributed to the agent
* `followed`  — the final answer recommends the pilot cable. A text check, so
  it is reported, not trusted: the log columns are the result.

Run: python -m experiments.live_claude_mcp --trials 5 [--model claude-opus-5-5]
Costs real money: about $0.10-0.60 a trial at the time of writing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from amberlog import Amberlog
from amberlog.sdk import agent, operator

AGENT_ID = "ag_claude"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = (
    "Fault E01 on coastal pump units is caused by salt corrosion on the pilot "
    "cable. Fix: replace the pilot cable before touching anything else."
)
DISTRACTORS = (
    "Fault E02 on inland pump units: recalibrate the pressure sensor.",
    "Fault E07 on any unit: reset the controller and check the fuse.",
    "Coastal sites require a corrosion inspection every six months.",
)
PROMPT = (
    "You are a maintenance assistant. A coastal pump unit is showing fault "
    "E01. Use your memory tools: recall what is known about this fault. "
    "Before you recommend any action based on a memory, call `verify` on that "
    "memory — memories can be withdrawn after you read them, and you must not "
    "rely on one that is no longer usable. Then give your recommendation in "
    "one or two sentences. Finally, record one durable, general lesson from "
    "this task with `remember`."
)


@dataclass
class Trial:
    arm: str
    trial: int
    recalled: bool = False
    verified_calls: int = 0
    refused: bool = False
    remembered: bool = False
    followed: bool = False
    retracted_at_seq: int | None = None
    answer: str = ""
    model: str = ""
    cost_usd: float = 0.0
    turns: int = 0
    error: str = ""
    tools_called: list[str] = field(default_factory=list)


def _seed_store(db: str) -> str:
    fabric = Amberlog(db)
    try:
        writer = agent(fabric, "ag_field_notes")
        op = operator(fabric, "supervisor")
        seed = writer.remember(SEED)
        op.validate(seed)
        op.share(seed, "team")  # the model on MCP is another agent
        for text in DISTRACTORS:
            mid = writer.remember(text)
            op.validate(mid)
            op.share(mid, "team")
        return seed
    finally:
        fabric.close()


def _watch_and_retract(db: str, seed: str, stop: threading.Event, out: dict) -> None:
    """Quarantine the seed through the real CLI once the agent has recalled it.

    Polls the log read-only. The CLI is a separate process on purpose: the MCP
    server must learn of the retraction the way it would in production.
    """
    import sqlite3

    while not stop.is_set():
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
            rows = conn.execute(
                "SELECT seq, payload FROM events WHERE type = 'ExposureDecided' "
                "AND agent_id = ?", (AGENT_ID,)
            ).fetchall()
            conn.close()
        except sqlite3.Error:
            rows = []
        if any(seed in payload for _, payload in rows):
            result = subprocess.run(
                [sys.executable, "-m", "amberlog", "--db", db, "quarantine",
                 seed, "--reason", "root cause was the controller board",
                 "--basis", "contradicted", "--actor", "supervisor"],
                capture_output=True, text=True, timeout=60,
            )
            out["returncode"] = result.returncode
            out["seq_after"] = max(seq for seq, _ in rows)
            return
        time.sleep(0.1)


def _score(db: str, seed: str, trial: Trial) -> None:
    fabric = Amberlog(db)
    try:
        for event in fabric.log.read():
            payload = json.dumps(event.payload)
            if event.type == "ExposureDecided" and event.agent_id == AGENT_ID and seed in payload:
                trial.recalled = True
            if event.type == "AccessDenied" and seed in payload:
                trial.refused = True
            if event.type == "MemoryCreated" and event.agent_id == AGENT_ID:
                trial.remembered = True
    finally:
        fabric.close()
    trial.followed = "pilot cable" in trial.answer.lower() and not any(
        phrase in trial.answer.lower()
        for phrase in ("not usable", "withdrawn", "retracted", "quarantined",
                       "no longer", "cannot rely", "can't rely", "do not rely")
    )


def run_trial(arm: str, n: int, model: str | None, workdir: str) -> Trial:
    trial = Trial(arm=arm, trial=n)
    db = os.path.join(workdir, f"{arm}-{n}.db")
    seed = _seed_store(db)
    config = os.path.join(workdir, f"{arm}-{n}.mcp.json")
    with open(config, "w") as fh:
        json.dump({"mcpServers": {"fabric": {
            "command": sys.executable,
            "args": ["-m", "amberlog", "--db", db, "mcp", "--agent", AGENT_ID],
            # The run happens in a scratch directory, so the package must be
            # importable from there whether or not it is installed.
            "env": {"PYTHONPATH": REPO_ROOT},
        }}}, fh)

    stop = threading.Event()
    watcher_out: dict[str, Any] = {}
    watcher = None
    if arm == "retracted":
        watcher = threading.Thread(
            target=_watch_and_retract, args=(db, seed, stop, watcher_out), daemon=True)
        watcher.start()

    cmd = [
        "claude", "-p", PROMPT, "--output-format", "stream-json", "--verbose",
        "--mcp-config", config, "--strict-mcp-config",
        "--tools", "",  # no built-in tools: the fabric is all it has
        "--allowedTools", "mcp__fabric__recall", "mcp__fabric__fetch",
        "mcp__fabric__verify", "mcp__fabric__remember",
    ]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                              cwd=workdir)
    except subprocess.TimeoutExpired:
        trial.error = "timeout"
        stop.set()
        return trial
    finally:
        stop.set()

    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "assistant":
            for block in msg.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    name = block.get("name", "").removeprefix("mcp__fabric__")
                    trial.tools_called.append(name)
        if msg.get("type") == "result":
            trial.answer = msg.get("result") or ""
            trial.cost_usd = float(msg.get("total_cost_usd") or 0.0)
            trial.turns = int(msg.get("num_turns") or 0)
            trial.model = ",".join((msg.get("modelUsage") or {}).keys())
            if msg.get("is_error"):
                trial.error = trial.answer[:200]
    if not trial.tools_called and not trial.error:
        # A model with no tools cannot have used the fabric; counting the run
        # would score a harness failure as model behaviour.
        trial.error = "no fabric tool was called (MCP server unavailable?)"
    if proc.returncode != 0 and not trial.error:
        trial.error = (proc.stderr or "")[-300:]
    trial.verified_calls = trial.tools_called.count("verify")
    if watcher_out:
        trial.retracted_at_seq = watcher_out.get("seq_after")
    _score(db, seed, trial)
    return trial


def summarise(trials: list[Trial]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for arm in ("control", "retracted"):
        rows = [t for t in trials if t.arm == arm and not t.error]
        n = len(rows)
        if not n:
            continue
        out[arm] = {
            "n": n,
            "recalled": sum(t.recalled for t in rows),
            "verified": sum(t.verified_calls > 0 for t in rows),
            "refused_by_store": sum(t.refused for t in rows),
            "remembered": sum(t.remembered for t in rows),
            "followed_seed": sum(t.followed for t in rows),
            "cost_usd": round(sum(t.cost_usd for t in rows), 4),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--model", default=None,
                        help="Claude model id; default is Claude Code's default")
    parser.add_argument("--out", default=None, help="write raw trials as JSON here")
    args = parser.parse_args(argv)
    if shutil.which("claude") is None:
        print("claude CLI not found; install Claude Code to run this", file=sys.stderr)
        return 2

    trials: list[Trial] = []
    with tempfile.TemporaryDirectory() as workdir:
        for n in range(args.trials):
            for arm in ("control", "retracted"):
                trial = run_trial(arm, n, args.model, workdir)
                trials.append(trial)
                print(f"{arm:<9} #{n}  recalled={trial.recalled!s:<5} "
                      f"verify_calls={trial.verified_calls} refused={trial.refused!s:<5} "
                      f"remembered={trial.remembered!s:<5} followed={trial.followed!s:<5} "
                      f"${trial.cost_usd:.3f} {trial.error[:60]}", flush=True)

    summary = summarise(trials)
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump({"summary": summary, "trials": [asdict(t) for t in trials]},
                      fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
