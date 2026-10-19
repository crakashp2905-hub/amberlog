"""Generate docs/API.md and docs/CLI.md from the code (tests/test_reference_docs.py checks them).

    python tools/gen_reference.py           # write both
    python tools/gen_reference.py --check   # exit 1 if either is out of date

Signatures and the first paragraph of each docstring, grouped by what a
user is doing. Generated, so it cannot drift from the code: a signature
change without a regeneration fails CI.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

API: list[tuple[str, str, list[str]]] = [
    ("Store and retrieve", "memory_fabric.fabric:MemoryFabric",
     ["__init__", "remember", "derive", "revise", "retrieve", "get", "history", "explain",
      "lineage", "audit_trail", "start_episode", "cite", "record_outcome", "end_episode"]),
    ("Govern", "memory_fabric.fabric:MemoryFabric",
     ["validate", "quarantine", "release", "forget", "share", "challenge", "erase_content",
      "authority", "elevate", "sweep_retention", "certify", "verify_certificate"]),
    ("Agent SDK", "memory_fabric.sdk:agent", []),
    ("Agent SDK", "memory_fabric.sdk:AgentClient",
     ["recall", "fetch", "verify", "require", "remember", "episode", "record_outcome"]),
    ("Operator SDK", "memory_fabric.sdk:operator", []),
    ("Operator SDK", "memory_fabric.sdk:OperatorClient",
     ["inspect", "explain", "lineage", "attention", "retract", "validate", "share", "release",
      "erase_content"]),
    ("Identity and tenancy", "memory_fabric.service:MemoryService",
     ["register_agent", "issue", "session", "revoke", "revoke_agent"]),
    ("Identity and tenancy", "memory_fabric.service:Session",
     ["remember", "retrieve", "use", "certify", "quarantine", "validate", "inspect",
      "export_audit"]),
    ("Identity and tenancy", "memory_fabric.identity:Principal", ["permissions", "can"]),
    ("Identity and tenancy", "memory_fabric.tenancy:TenantRouter", ["store", "view", "tenants"]),
    ("Actions", "memory_fabric.actions:ActionGate",
     ["authorize", "execute", "issue_grant", "revoke_grant"]),
    ("Actions", "memory_fabric.actions:ToolRule", []),
    ("Actions", "memory_fabric.actions:ActionRequest", []),
    ("Correction and recovery", "memory_fabric.correction:preview", []),
    ("Correction and recovery", "memory_fabric.correction:apply", []),
    ("Correction and recovery", "memory_fabric.correction:status", []),
    ("Correction and recovery", "memory_fabric.response:verify_recovery", []),
    ("Correction and recovery", "memory_fabric.influence:impact", []),
    ("Correction and recovery", "memory_fabric.influence:paraphrases", []),
    ("Trust", "memory_fabric.authority:of", []),
    ("Trust", "memory_fabric.validation:assess", []),
    ("Trust", "memory_fabric.validation:assess_write", []),
    ("Trust", "memory_fabric.validation:review_queue", []),
    ("Objectives", "memory_fabric.objective_v2:MemoryObjectiveV2",
     ["eligibility", "explain", "omissions", "reviewed"]),
    ("Objectives", "memory_fabric.objective_v2:ObjectiveLog", ["propose", "adopt"]),
    ("Sessions", "memory_fabric.compaction:compact_session", []),
    ("Sessions", "memory_fabric.compaction:summary_for", []),
    ("Sessions", "memory_fabric.adapters.transcripts:ingest_transcript", []),
    ("Federation", "memory_fabric.federation:offer", []),
    ("Federation", "memory_fabric.federation:offer_remote", []),
    ("Background maintenance", "memory_fabric.manager:MemoryManager", ["run_once", "start", "stop"]),
    ("Limits", "memory_fabric.limits:Limits", []),
]


def first_paragraph(obj: object) -> str:
    doc = inspect.getdoc(obj) or ""
    return doc.split("\n\n", 1)[0].replace("\n", " ").strip()


def _annotation(a: object) -> str:
    if a is inspect.Parameter.empty:
        return ""
    text = a if isinstance(a, str) else getattr(a, "__name__", str(a))
    return str(text).strip("'\"").replace("'", "")


def _default(d: object) -> str:
    import enum

    if isinstance(d, enum.Enum):
        return f"{type(d).__name__}.{d.name}"
    return re.sub(r" at 0x[0-9a-f]+", "", repr(d))


def signature(obj: object) -> str:
    try:
        sig = inspect.signature(obj)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "(...)"
    parts = []
    for p in sig.parameters.values():
        if p.name == "self":
            continue
        text = ("*" if p.kind is p.VAR_POSITIONAL else "**" if p.kind is p.VAR_KEYWORD else "") + p.name
        ann = _annotation(p.annotation)
        if ann:
            text += f": {ann}"
        if p.default is not inspect.Parameter.empty:
            text += f" = {_default(p.default)}"
        parts.append(text)
    ret = _annotation(sig.return_annotation)
    return f"({', '.join(parts)})" + (f" -> {ret}" if ret and ret != "None" else "")


def stability(module_name: str) -> str:
    return getattr(importlib.import_module(module_name), "__stability__", "?")


def api_md() -> str:
    lines = ["# API reference", "",
             "Generated by `tools/gen_reference.py` from the code. The tier is the module's",
             "`__stability__` ([STABILITY.md](../STABILITY.md)). Start with",
             "[QUICKSTART.md](QUICKSTART.md); task-sized examples are in [COOKBOOK.md](COOKBOOK.md).", ""]
    section = None
    for title, target, members in API:
        module_name, name = target.split(":")
        obj = getattr(importlib.import_module(module_name), name)
        if title != section:
            lines += [f"## {title}", ""]
            section = title
        short = module_name.replace("memory_fabric.", "")
        lines += [f"### `{short}.{name}` ({stability(module_name)})", ""]
        if inspect.isclass(obj) and not members:
            lines += [f"```python\n{name}{signature(obj)}\n```", ""]
        elif not inspect.isclass(obj):
            lines += [f"```python\n{name}{signature(obj)}\n```", ""]
        summary = first_paragraph(obj)
        if summary:
            lines += [summary, ""]
        for member in members:
            fn = getattr(obj, member)
            shown = name if member == "__init__" else f"{name}.{member}"
            lines += [f"- **`{shown}{signature(fn)}`**"]
            summary = first_paragraph(fn)
            if summary and member != "__init__":
                lines += [f"  {summary}"]
        if members:
            lines += [""]
    return "\n".join(lines).rstrip() + "\n"


def cli_md() -> str:
    from memory_fabric.cli import build_parser

    parser = build_parser()
    lines = ["# CLI reference", "",
             "Generated by `tools/gen_reference.py` from the argument parser.",
             "Global options go **before** the command: `memory-fabric --db store.db --json overview`.",
             "", "## Global options", ""]
    for action in parser._actions:
        if action.option_strings and action.dest != "help":
            lines.append(f"- `{', '.join(action.option_strings)}`: {action.help or ''}")
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    lines += ["", "## Commands", ""]
    for name, command in sorted(sub.choices.items()):
        lines += [f"### `{name}`", "", (command.description or "").strip(), ""]
        for action in command._actions:
            if action.dest == "help":
                continue
            flag = ", ".join(action.option_strings) or action.dest
            lines.append(f"- `{flag}`: {action.help or ''}".rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    outputs = {ROOT / "docs" / "API.md": api_md(), ROOT / "docs" / "CLI.md": cli_md()}
    if "--check" in argv:
        import difflib

        stale = [p for p, text in outputs.items()
                 if not p.exists() or p.read_text(encoding="utf-8") != text]
        for path in stale:
            current = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            diff = list(difflib.unified_diff(current, outputs[path].splitlines(), "committed",
                                             "generated", lineterm="", n=0))
            for line in diff[:40]:
                print(line)
        if stale:
            print(f"out of date: {[p.name for p in stale]}; run python tools/gen_reference.py")
            return 1
        return 0
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
