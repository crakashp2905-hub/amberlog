"""Render product/capabilities.json as docs/product/CAPABILITY_REGISTRY.md.

    python tools/gen_capabilities.py           # write
    python tools/gen_capabilities.py --check   # exit 1 if the page is stale

The JSON is the registry; the page and the dashboard's status badges are
generated from it, never edited by hand. `tests/test_capability_registry.py`
checks every module, test and surface it names against the code, so a
capability cannot be listed as available on a path that does not exist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "product" / "capabilities.json"
PAGE = ROOT / "docs" / "product" / "CAPABILITY_REGISTRY.md"
# The dashboard's status badges read this copy, shipped as package data.
BADGES = ROOT / "src" / "amberlog" / "observability" / "static" / "capabilities.json"
ORDER = ("available", "experimental", "planned", "unsupported")


def render() -> str:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    lines = ["# Capability registry", "",
             "Generated from `product/capabilities.json` by `tools/gen_capabilities.py`; "
             "do not edit. Every module, test and surface named here is checked against "
             "the code by `tests/test_capability_registry.py`.", "",
             "| status | meaning |", "|---|---|"]
    lines += [f"| **{s}** | {data['statuses'][s]} |" for s in ORDER]
    for status in ORDER:
        caps = [c for c in data["capabilities"] if c["status"] == status]
        if not caps:
            continue
        lines += ["", f"## {status.title()}", ""]
        for c in caps:
            lines += [f"### {c['title']}", "", f"`{c['id']}` — {c['user_problem']}", ""]
            surfaces = ", ".join(f"{k}: `{v}`" for k, v in c["surfaces"].items() if v)
            if surfaces:
                lines.append(f"- **Surfaces:** {surfaces}")
            if c["modules"]:
                lines.append("- **Code:** " + ", ".join(f"`{m}`" for m in c["modules"]))
            if c["tests"]:
                lines.append("- **Tests:** " + ", ".join(f"`{t}`" for t in c["tests"]))
            for lim in c["limitations"]:
                lines.append(f"- **Limitation:** {lim}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    outputs = {PAGE: render(), BADGES: SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n")}
    if "--check" in argv:
        stale = [p for p, text in outputs.items()
                 if not p.exists() or p.read_text(encoding="utf-8").replace("\r\n", "\n") != text]
        for p in stale:
            print(f"{p.relative_to(ROOT)} is stale: run python tools/gen_capabilities.py")
        return 1 if stale else 0
    for p, text in outputs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
