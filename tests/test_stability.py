"""Every module declares a stability tier, and STABILITY.md says the same thing as the code."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIERS = ("stable", "beta", "experimental")


def declared() -> dict[str, str]:
    out = {}
    for path in sorted((ROOT / "src" / "amberlog").rglob("*.py")):
        if path.name == "__main__.py":
            continue
        rel = path.relative_to(ROOT / "src" / "amberlog").with_suffix("").as_posix()
        match = re.search(r'^__stability__ = "(\w+)"', path.read_text(encoding="utf-8"), re.M)
        out["amberlog." + rel.replace("/", ".")] = match.group(1) if match else ""
    return out


class Stability(unittest.TestCase):
    def test_every_module_declares_a_known_tier(self) -> None:
        missing = [m for m, tier in declared().items() if tier not in TIERS]
        self.assertEqual(missing, [], "add __stability__ = 'stable' | 'beta' | 'experimental'")

    def test_the_document_matches_the_code(self) -> None:
        doc = (ROOT / "STABILITY.md").read_text(encoding="utf-8")
        listed = {}
        for tier in TIERS:
            section = re.search(rf"^## {tier.title()} \(\d+\)\n(.*?)(?=^## )", doc, re.M | re.S)
            self.assertIsNotNone(section, f"no {tier} section")
            for name in re.findall(r"^- `([\w.]+)`", section.group(1), re.M):
                listed[name] = tier
        self.assertEqual(listed, declared(), "regenerate the tier lists: python tools/gen_stability.py")

    def test_experimental_modules_are_not_imported_by_the_default_path(self) -> None:
        experimental = {m.rsplit(".", 1)[-1] for m, t in declared().items() if t == "experimental"}
        for core in ("fabric", "service", "agent_api", "session"):
            text = (ROOT / "src" / "amberlog" / f"{core}.py").read_text(encoding="utf-8")
            top = [line for line in text.splitlines() if line.startswith(("from .", "import "))]
            hits = [line for line in top if any(f"from .{e} import" in line for e in experimental)]
            self.assertEqual(hits, [], f"{core}.py imports an experimental module at top level")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
