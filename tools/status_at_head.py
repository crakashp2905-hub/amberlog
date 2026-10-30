"""What is true of this tree, checked rather than remembered (masterplan MF-001).

    python tools/status_at_head.py            # print the page
    python tools/status_at_head.py --write    # rewrite docs/STATUS_AT_HEAD.md
    python tools/status_at_head.py --check    # exit 1 if any contradiction is found

The page is derived from the tree, so it carries no commit hash of its own (a
committed file cannot name the commit that contains it). The commit is stamped
by CI's release bundle, which runs this with `--sha` and keeps the output beside
the test results for that exact commit.

Every row is computed: versions from `pyproject.toml`, `model.SCHEMA_VERSION`
and `SPEC.md`; tiers from each module's `__stability__`; which experimental
modules a preset turns on; the test count CI collects; the tests that skip when
an optional dependency or service is absent; and which recorded results name
the commit that produced them. Contradictions are listed, not smoothed over.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "STATUS_AT_HEAD.md"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def versions() -> dict[str, str]:
    package = re.search(r'(?m)^version = "([^"]+)"', _read("pyproject.toml"))
    schema = re.search(r'(?m)^SCHEMA_VERSION = "([^"]+)"', _read("src/memory_fabric/model.py"))
    spec = re.search(r"Schema version:\*\* `([^`]+)`", _read("SPEC.md"))
    spec_latest = re.search(r"(?m)^### (\d+\.\d+\.\d+) ", _read("SPEC.md"))
    notes = sorted((ROOT / "docs").glob("RELEASE_NOTES_*.md"),
                   key=lambda p: tuple(int(x) for x in p.stem.split("_")[-1].split(".")))
    return {"package": package[1] if package else "?", "schema": schema[1] if schema else "?",
            "spec_header": spec[1] if spec else "?",
            "spec_latest_section": spec_latest[1] if spec_latest else "?",
            "latest_release_notes": notes[-1].stem.split("_")[-1] if notes else "none"}


def tags() -> list[str]:
    done = subprocess.run(["git", "tag", "--list"], capture_output=True, text=True, cwd=ROOT)
    return sorted(done.stdout.split()) if done.returncode == 0 else []


def tiers() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in sorted((ROOT / "src" / "memory_fabric").rglob("*.py"), key=lambda p: p.as_posix()):
        if "__pycache__" in path.parts:
            continue
        match = re.search(r'(?m)^__stability__ = "(\w+)"', path.read_text(encoding="utf-8"))
        if match:
            name = ".".join(path.relative_to(ROOT / "src").with_suffix("").parts)
            out.setdefault(match[1], []).append(name.removesuffix(".__init__"))
    return out


def preset_experimental(experimental: list[str]) -> list[str]:
    """Experimental modules a preset imports, i.e. turns on by default in that mode."""
    tree = ast.parse(_read("src/memory_fabric/presets.py"))
    used = {f"memory_fabric.{n.module.lstrip('.')}" for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module}
    return sorted(used & set(experimental))


def skips() -> list[str]:
    found = []
    pattern = re.compile(r"skip(?:Unless|If)\((.+?),\s*[\"'](.+?)[\"']\)")
    for path in sorted((ROOT / "tests").glob("test_*.py"), key=lambda p: p.name):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            found.append(f"`{path.name}`: {match[2]}")
    return sorted(set(found))


def test_count() -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    import count_tests  # noqa: E402

    return count_tests.count()


def results() -> tuple[list[str], list[str]]:
    pinned, unpinned = [], []
    # Sorted by name, not by Path: Windows compares paths case-insensitively.
    for path in sorted((ROOT / "research" / "results").glob("*.json"), key=lambda p: p.name):
        if path.name == "MANIFEST.json":   # the index of results, not a result
            continue
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            unpinned.append(path.name)
            continue
        (pinned if isinstance(data, dict) and data.get("commit") else unpinned).append(path.name)
    return pinned, unpinned


def contradictions(v: dict[str, str]) -> list[str]:
    out = []
    if v["spec_header"] != v["schema"]:
        out.append(f"SPEC.md header says schema `{v['spec_header']}`, code says `{v['schema']}`")
    if v["spec_latest_section"] != v["schema"]:
        out.append(f"SPEC.md's newest section is `{v['spec_latest_section']}`, code says `{v['schema']}`")
    if tuple(map(int, v["package"].split("."))) < tuple(map(int, v["schema"].split("."))):
        out.append(f"package `{v['package']}` is behind schema `{v['schema']}`")
    return out


def render(sha: str | None = None) -> str:
    v = versions()
    t = tiers()
    experimental = t.get("experimental", [])
    defaults = preset_experimental(experimental)
    pinned, unpinned = results()
    found = contradictions(v)
    # Tag availability depends on shallow checkout/fetch settings, not source.
    # Only stamped runtime release evidence should inspect the checkout refs.
    released = tags() if sha else []
    lines = [
        "# Status at HEAD",
        "",
        "Generated by `tools/status_at_head.py` from the tree; do not edit by hand. "
        "CI's release bundle runs it with `--sha` to stamp the exact commit.",
        "",
        f"- **Commit:** {f'`{sha}`' if sha else 'stamped by CI (`--sha`)'}",
        f"- **Package version:** `{v['package']}`; **schema:** `{v['schema']}`; "
        f"**SPEC.md header:** `{v['spec_header']}`",
        f"- **Released tags:** " + (
            ', '.join(f'`{x}`' for x in released) if released else
            'none visible in this checkout (not proof of publication status)' if sha else
            'not enumerated in the deterministic tree report; inspect stamped release evidence'),
        f"- **Latest release notes:** `{v['latest_release_notes']}` (they pin their own baseline commit; "
        "work merged since is not part of that release)",
        f"- **Tests CI collects:** {test_count()}",
        f"- **Module tiers:** " + ", ".join(f"{k} {len(t[k])}" for k in ("stable", "beta", "experimental") if k in t),
        "",
        "## Contradictions",
        "",
        *([f"- {c}" for c in found] or ["- none found"]),
        "",
        "## Experimental modules on by default",
        "",
        "Turned on by a preset in `src/memory_fabric/presets.py`; every other experimental module is opt-in.",
        "",
        *([f"- `{m}`" for m in defaults] or ["- none"]),
        "",
        "## Tests that skip without an optional dependency or service",
        "",
        "Skipped is not passed: CI's optional jobs (Postgres, framework contracts) run these.",
        "",
        *[f"- {s}" for s in skips()],
        "",
        "## Recorded results",
        "",
        f"{len(pinned)} result files name the commit that produced them; {len(unpinned)} do not "
        "(older runs, or runs whose commit is in the companion `.md`). The manifest with every "
        "field is `research/results/MANIFEST.json` (`tools/results_manifest.py`).",
        "",
        "Without a commit: " + ", ".join(f"`{u}`" for u in unpinned) + ".",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    sha = argv[argv.index("--sha") + 1] if "--sha" in argv else None
    page = render(sha)
    if "--check" in argv:
        found = contradictions(versions())
        for c in found:
            print(c)
        return 1 if found else 0
    if "--write" in argv:
        OUT.write_text(page, encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
        return 0
    print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
