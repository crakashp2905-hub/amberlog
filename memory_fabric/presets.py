"""Three modes instead of a dozen settings: `personal`, `team`, `regulated`.

    from memory_fabric.presets import open_store, tool_rule

    fabric = open_store("memory/store.db", "team")
    rule = tool_rule("team", "issue_refund")

| | personal | team | regulated |
|---|---|---|---|
| new memories | active at once | wait for review | wait for review |
| suspicious claims held | yes | yes | yes |
| source caught injecting withheld everywhere | yes | yes | yes |
| evidence for a protected tool | 1 source | 1 source, no held or provisional claims | 2 independent sources, fresh leases for imported evidence, no provisional claims |
| content encryption profile | default | default | production (AES-256-GCM, `cryptography` required) |
| MCP agents | `--trusted-local` | reviewed | reviewed |

`personal` is one person and their agents on one machine. `team` is several
people or agents sharing knowledge. `regulated` is where an action on a wrong
fact has a cost someone must answer for. Every setting stays overridable:
keyword arguments win over the preset.
"""

from __future__ import annotations

__stability__ = "beta"

from typing import Any

MODES = ("personal", "team", "regulated")

_STORE: dict[str, dict[str, Any]] = {
    "personal": {"auto_activate": True, "hold_suspicious": True, "withhold_hostile_sources": True},
    "team": {"auto_activate": False, "hold_suspicious": True, "withhold_hostile_sources": True},
    "regulated": {"auto_activate": False, "hold_suspicious": True,
                  "withhold_hostile_sources": True, "crypto_profile": "production"},
}
_RULE: dict[str, dict[str, Any]] = {
    "personal": {},
    "team": {"refuse_suspicious": True, "refuse_provisional": True},
    "regulated": {"refuse_suspicious": True, "refuse_provisional": True,
                  "min_independent_sources": 2, "require_fresh": True},
}


def _mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    return mode


def store_settings(mode: str) -> dict[str, Any]:
    return dict(_STORE[_mode(mode)])


def open_store(path: str, mode: str, **overrides: Any) -> Any:
    """A `MemoryFabric` with the mode's settings; `overrides` win."""
    from .fabric import MemoryFabric

    return MemoryFabric(path, **{**store_settings(mode), **overrides})


def tool_rule(mode: str, tool: str, **overrides: Any) -> Any:
    """A `ToolRule` for a protected tool under the mode; `overrides` win."""
    from .actions import ToolRule

    return ToolRule(tool, **{**_RULE[_mode(mode)], **overrides})


def mcp_flags(mode: str) -> list[str]:
    return ["--trusted-local"] if _mode(mode) == "personal" else []
