"""`memory_fabric connect <tool>`: the exact setup for each agent tool.

Every MCP client wants the same server described in a slightly different
file, key and format. This knows them, so a user names their tool and gets
the right snippet, or `--write` merges it into the tool's config file (the
previous file is kept beside it as `.bak`). Nothing else in that file is
touched.

Each agent gets its own id (`--agent`), so every memory records which tool
wrote it and the dashboard can tell them apart. Tools that are not MCP
clients get the HTTP API or the Python SDK instead.
"""

from __future__ import annotations

__stability__ = "beta"

import json
import os
import platform
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class Target:
    name: str
    title: str
    kind: str  # "json", "toml", "yaml", "command", "text"
    path: Callable[[], Path | None]
    key: str = "mcpServers"
    note: str = ""


def _home(*parts: str) -> Path:
    return Path.home().joinpath(*parts)


def _claude_desktop() -> Path:
    system = platform.system()
    if system == "Darwin":
        return _home("Library", "Application Support", "Claude", "claude_desktop_config.json")
    if system == "Windows":
        return Path(os.environ.get("APPDATA", str(_home()))) / "Claude" / "claude_desktop_config.json"
    return _home(".config", "Claude", "claude_desktop_config.json")


def _vscode_user() -> Path:
    return Path(".vscode") / "mcp.json"


TARGETS: dict[str, Target] = {t.name: t for t in (
    Target("claude-code", "Claude Code", "command", lambda: None),
    Target("claude-desktop", "Claude Desktop", "json", _claude_desktop),
    Target("cursor", "Cursor", "json", lambda: _home(".cursor", "mcp.json")),
    Target("windsurf", "Windsurf", "json", lambda: _home(".codeium", "windsurf", "mcp_config.json")),
    Target("vscode", "VS Code (Copilot agent mode)", "json", _vscode_user, key="servers",
           note="workspace file; commit it only if the paths are shared"),
    Target("cline", "Cline", "json", lambda: None,
           note="paste into Cline's MCP settings (cline_mcp_settings.json)"),
    Target("gemini-cli", "Gemini CLI", "json", lambda: _home(".gemini", "settings.json")),
    Target("zed", "Zed", "json", lambda: _home(".config", "zed", "settings.json"),
           key="context_servers"),
    Target("codex", "OpenAI Codex CLI", "toml", lambda: _home(".codex", "config.toml")),
    Target("continue", "Continue", "yaml",
           lambda: Path(".continue") / "mcpServers" / "memory_fabric.yaml"),
    Target("http", "Any language, over HTTP", "text", lambda: None),
    Target("python", "Python frameworks (LangGraph, OpenAI Agents SDK, CrewAI, AutoGen, ...)",
           "text", lambda: None),
)}


def server_args(db: str, agent: str, keys: str | None, trusted_local: bool) -> list[str]:
    args = ["--db", os.path.abspath(db)]
    if keys:
        args += ["--keys", os.path.abspath(keys)]
    args += ["mcp", "--agent", agent]
    if trusted_local:
        args.append("--trusted-local")
    return args


def command() -> str:
    found = shutil.which("memory_fabric")
    return found or "memory_fabric"


def snippet(target: str, db: str, agent: str, keys: str | None = None,
            trusted_local: bool = False) -> dict[str, Any]:
    """What to write for `target`: {"kind", "path", "text", "entry"}."""
    t = TARGETS[target]
    args = server_args(db, agent, keys, trusted_local)
    cmd = command()
    entry: dict[str, Any] = {"command": cmd, "args": args}
    if t.name == "zed":
        entry = {"command": {"path": cmd, "args": args}, "settings": {}}
    if t.name == "vscode":
        entry = {"type": "stdio", "command": cmd, "args": args}
    path = t.path()
    if t.kind == "command":
        text = "claude mcp add memory_fabric -- " + " ".join(shlex.quote(a) for a in [cmd, *args])
    elif t.kind == "json":
        text = json.dumps({t.key: {"memory_fabric": entry}}, indent=2)
    elif t.kind == "toml":
        text = ("[mcp_servers.memory_fabric]\n"
                f"command = {json.dumps(cmd)}\nargs = {json.dumps(args)}\n")
    elif t.kind == "yaml":
        text = ("name: Memory Fabric\nversion: 0.0.1\nschema: v1\nmcpServers:\n"
                "  - name: memory_fabric\n"
                f"    command: {json.dumps(cmd)}\n    args: {json.dumps(args)}\n")
    elif t.name == "http":
        text = (f"memory_fabric --db {shlex.quote(os.path.abspath(db))} agent-api "
                f"--agents-file agents.txt          # once; 127.0.0.1:8766\n"
                f"memory_fabric --db {shlex.quote(os.path.abspath(db))} agent-api-issue "
                f"--agents-file agents.txt --agent {agent}\n"
                "curl -s -X POST http://127.0.0.1:8766/v1/recall \\\n"
                "  -H \"Authorization: Bearer $MF_CREDENTIAL\" -d '{\"query\": \"...\"}'\n"
                "# endpoints: /v1/recall /v1/fetch /v1/verify /v1/remember\n")
    else:
        text = ("from memory_fabric import MemoryFabric\n"
                "from memory_fabric.integrations.tools import FabricTools\n"
                "from memory_fabric.sdk import agent\n\n"
                f"fabric = MemoryFabric({os.path.abspath(db)!r})\n"
                f"mem = FabricTools(agent(fabric, {agent!r}))\n"
                "tools = mem.specs(\"openai\")        # or \"anthropic\"\n"
                "result = mem.call(name, arguments)  # any function-calling framework\n"
                "# guides: docs/guides/langgraph.md, openai-agents.md, crewai.md\n")
    return {"kind": t.kind, "path": str(path) if path else None, "text": text, "entry": entry,
            "key": t.key, "note": t.note, "title": t.title}


def write(target: str, db: str, agent: str, keys: str | None = None,
          trusted_local: bool = False) -> str:
    """Merge the server into the tool's config file. Returns the path written."""
    s = snippet(target, db, agent, keys, trusted_local)
    if not s["path"] or s["kind"] in ("command", "text"):
        raise ValueError(f"{target}: nothing to write; run or paste the snippet instead")
    path = Path(s["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing:
        path.with_name(path.name + ".bak").write_text(existing, encoding="utf-8")
    if s["kind"] == "json":
        data = json.loads(existing) if existing.strip() else {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a JSON object; not changing it")
        data.setdefault(s["key"], {})["memory_fabric"] = s["entry"]
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    elif s["kind"] == "toml":
        if "[mcp_servers.memory_fabric]" in existing:
            raise ValueError(f"{path} already has [mcp_servers.memory_fabric]; edit it by hand")
        path.write_text(existing.rstrip() + ("\n\n" if existing.strip() else "") + s["text"],
                        encoding="utf-8")
    else:
        path.write_text(s["text"], encoding="utf-8")
    return str(path)
