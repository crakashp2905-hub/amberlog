"""A real Claude model as a client of the agent HTTP API.

The second live integration. The first (`live_claude_mcp.py`) gave the model
the fabric's MCP tools. This one gives it nothing but `curl` and the
documented HTTP API of a separately launched `amberlog agent-api`
process, which is the deployment for agents in another language or on another
machine. The credential reaches the model's shell through an environment
variable, never through the prompt text.

Same two arms and same scoring as the MCP run, from the store's own log and
never from what the model says it did:

* **control**: a validated memory says what to do about fault E01.
* **retracted**: a watcher quarantines that memory through the real CLI, in
  another process, the moment the model's recall is logged. The model's
  `verify` must come back unusable, and it must not recommend the fix.

    python -m experiments.live_claude_http --trials 3

Costs real money through Claude Code: about $0.10–0.60 a trial.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from experiments import live_claude_mcp as base

AGENT_ID = base.AGENT_ID
KEY = "dd" * 32
ROOT = Path(__file__).resolve().parent.parent

PROMPT = (
    "You are a maintenance assistant with a memory service, an HTTP API you call "
    "with the `mf` command in your shell (it adds the credential for you):\n"
    "- mf recall '{\"query\": \"...\"}'          -> memories\n"
    "- mf fetch '{\"memory_id\": \"...\"}'\n"
    "- mf verify '{\"memory_id\": \"...\"}'      -> whether it is still usable\n"
    "- mf remember '{\"content\": \"...\"}'\n"
    "A coastal pump unit is showing fault E01. Recall what is known. Before you "
    "recommend any action based on a memory, verify that memory: memories can be "
    "withdrawn after you read them, and you must not rely on one that is no "
    "longer usable. Then give your recommendation in one or two sentences. "
    "Finally, record one durable, general lesson with remember."
)

# The model's shell gets a wrapper rather than the credential: Claude Code refuses a
# command with an unexpanded variable in it, so `curl -H "...$MF_TOKEN"` never
# ran (found on the first attempt, which reached the server zero times).
# Claude Code does not pass custom environment variables to its shell either,
# so the wrapper carries the URL and a token *file* path. The model may only run
# `mf`, so it cannot read the file. `--noproxy`: the shell's own HTTP proxy
# answered "authentication required" for 127.0.0.1 before the server saw it.
WRAPPER = """#!/bin/sh
exec curl -s --noproxy '*' -X POST "{url}/$1" -H "Authorization: Bearer $(cat {token_file})" \\
  -H 'Content-Type: application/json' -d "$2"
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_trial(arm: str, n: int, model: str | None, workdir: str) -> base.Trial:
    trial = base.Trial(arm=arm, trial=n)
    db = os.path.join(workdir, f"{arm}-{n}.db")
    seed = base._seed_store(db)
    agents = os.path.join(workdir, "agents")
    Path(agents).write_text(f"{AGENT_ID}:tn_default:{KEY}\n")
    port = free_port()
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    server = subprocess.Popen(
        [sys.executable, "-m", "amberlog", "--db", db, "agent-api",
         "--agents-file", agents, "--port", str(port)],
        cwd=workdir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stop = threading.Event()
    watcher_out: dict[str, Any] = {}
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        bearer = subprocess.run(
            [sys.executable, "-m", "amberlog", "--db", db, "agent-api-issue",
             "--agents-file", agents, "--agent", AGENT_ID, "--ttl", "1800"],
            capture_output=True, text=True, env=env, cwd=workdir).stdout.strip().splitlines()[-1]
        if arm == "retracted":
            threading.Thread(target=base._watch_and_retract,
                             args=(db, seed, stop, watcher_out), daemon=True).start()
        bindir = Path(workdir) / "bin"
        bindir.mkdir(exist_ok=True)
        token_file = Path(workdir) / f"token-{arm}-{n}"
        token_file.write_text(bearer)
        token_file.chmod(0o600)
        url = f"http://127.0.0.1:{port}/v1"
        (bindir / "mf").write_text(WRAPPER.format(url=url, token_file=token_file))
        (bindir / "mf").chmod(0o755)
        cmd = ["claude", "-p", PROMPT, "--output-format", "stream-json",
               "--verbose", "--strict-mcp-config", "--tools", "Bash",
               "--allowedTools", "Bash(mf:*)"]
        if model:
            cmd += ["--model", model]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                                  cwd=workdir, env={**env, "PATH": f"{bindir}:{env.get('PATH', '')}"})
        except subprocess.TimeoutExpired:
            trial.error = "timeout"
            return trial
    finally:
        stop.set()
        server.terminate()
        server.wait(timeout=20)

    calls: list[str] = []
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "assistant":
            for block in msg.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    command = str(block.get("input", {}).get("command", ""))
                    for op in ("recall", "fetch", "verify", "remember"):
                        if f"mf {op}" in command:
                            calls.append(op)
                    if bearer in command:
                        trial.error = "the token appeared in a command"
        if msg.get("type") == "result":
            trial.answer = msg.get("result") or ""
            trial.cost_usd = float(msg.get("total_cost_usd") or 0.0)
            trial.turns = int(msg.get("num_turns") or 0)
            trial.model = ",".join((msg.get("modelUsage") or {}).keys())
            if msg.get("is_error"):
                trial.error = trial.answer[:200]
    trial.tools_called = calls
    if not calls and not trial.error:
        trial.error = "no API call was made"
    trial.verified_calls = calls.count("verify")
    if watcher_out:
        trial.retracted_at_seq = watcher_out.get("seq_after")
    base._score(db, seed, trial)
    # Judged from the store, not from the commands: an attempted call that the
    # shell refused never reached the API, and counting it scored a harness
    # failure as model behaviour.
    from amberlog import Amberlog
    store = Amberlog(db)
    try:
        reached = any(e.agent_id == AGENT_ID for e in store.log.read())
    finally:
        store.close()
    if not reached and not trial.error:
        trial.error = "no request reached the API"
    return trial


def to_markdown(summary: dict, trials: list[base.Trial], commit: str) -> str:
    rows = "\n".join(
        f"| {arm} | {s['n']} | {s['recalled']} | {s['verified']} | {s['refused_by_store']} "
        f"| {s['followed_seed']} | {s['remembered']} | ${s['cost_usd']:.2f} |"
        for arm, s in summary.items())
    errors = [t for t in trials if t.error]
    models = sorted({m for t in trials for m in t.model.split(",") if m})
    return f"""# Live Claude over the agent HTTP API

Produced by `python -m experiments.live_claude_http` at commit `{commit}`; raw
trials in [live-claude-http.json](live-claude-http.json). Model(s): {', '.join(models) or 'unknown'}
(Claude Code's default), driven headless with **only** `curl` allowed.

Scored from the store's event log, not from the model's account: *recalled* is
an `ExposureDecided` for the seed memory, *refused* an `AccessDenied` for it
(the verify that came back unusable), *remembered* a `MemoryCreated` by the
agent. *Followed* is a text check on the final answer, reported but not
trusted.

| arm | trials | recalled | called verify | refused by the store | recommended the seed's fix | remembered | cost |
|---|---|---|---|---|---|---|---|
{rows}

Trials excluded for a harness error: {len(errors)}{' (' + '; '.join(e.error[:60] for e in errors) + ')' if errors else ''}.

**What it shows.** A model that knows nothing of this system can use the
HTTP API from a shell, and a retraction issued by a separate process reaches
its `verify` over HTTP. **What it does not.** It is a handful of trials of one
model on one scripted task, so it is an integration check, not a measurement
of how often models comply. That question is the MCP run's
([live-claude-mcp.md](live-claude-mcp.md)), and with this few trials, this
run cannot answer it either.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    if shutil.which("claude") is None:
        print("claude CLI not found", file=sys.stderr)
        return 2
    trials: list[base.Trial] = []
    with tempfile.TemporaryDirectory() as workdir:
        for n in range(args.trials):
            for arm in ("control", "retracted"):
                t = run_trial(arm, n, args.model, workdir)
                trials.append(t)
                print(f"{arm:<9} #{n} recalled={t.recalled} verify={t.verified_calls} "
                      f"refused={t.refused} followed={t.followed} remembered={t.remembered} "
                      f"${t.cost_usd:.3f} {t.error[:60]}", flush=True)
    summary = base.summarise(trials)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    out = ROOT / "research" / "results"
    (out / "live-claude-http.json").write_text(json.dumps(
        {"commit": commit, "summary": summary, "trials": [asdict(t) for t in trials]},
        indent=2) + "\n")
    (out / "live-claude-http.md").write_text(to_markdown(summary, trials, commit))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
