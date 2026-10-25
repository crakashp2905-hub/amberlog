"""User-facing documents describe the product, not the research programme behind it.

They may state what the product does and what it does not. They do not link
into `research/`, cite experiment ids, or use the vocabulary of the research
process. That material is for maintainers (docs/README.md, "For maintainers").
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_DOCS = ["README.md", "DEPLOYMENT.md", "SECURITY.md", "VERSIONING.md",
             "docs/QUICKSTART.md", "docs/CONCEPTS.md", "docs/COOKBOOK.md", "docs/FAQ.md",
             "docs/SCALE.md", "docs/INTEGRATIONS.md", "docs/RELEASE_NOTES_0.12.0.md",
             "docs/TROUBLESHOOTING.md", "docs/LIMITATIONS.md", "docs/OPERATIONS.md",
             "docs/RUNBOOKS.md", "docs/MIGRATION.md", "docs/REFERENCE_DEPLOYMENT.md",
             "examples/README.md", "STABILITY.md", "docs/API.md", "docs/CLI.md",
             "docs/guides/claude.md", "docs/guides/langgraph.md",
             "docs/guides/openai-agents.md", "docs/guides/crewai.md",
             "docs/RETRIEVAL.md"]
# Case-sensitive on purpose: "T2" alone is threat T2 in SECURITY.md, and
# "oracle" alone is the security sense (a probe that reveals existence).
FORBIDDEN = re.compile(
    r"research/|[Pp]re-?regist|\b[Hh]ypothes[ie]s\b(?! sets?\b)|oracle (?:arm|ceiling)|SCORECARD|FINDINGS|"
    r"\b[Hh]eld-out\b|\b(?:PB2|P9|P12b?|S[1-6]|T2b|G4b?|M1b?|M2[ab]?|C1|H[1-5]|"
    r"Phase [A-D]′?)\b")


def violations() -> list[str]:
    out = []
    for doc in USER_DOCS:
        for n, line in enumerate((ROOT / doc).read_text(encoding="utf-8").splitlines(), 1):
            m = FORBIDDEN.search(line)
            if m:
                out.append(f"{doc}:{n}: {m.group(0)!r}: {line.strip()[:100]}")
    return out


class UserDocs(unittest.TestCase):
    def test_no_research_in_user_docs(self) -> None:
        self.assertEqual(violations(), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
