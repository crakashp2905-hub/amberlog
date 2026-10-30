"""Research harness. Not part of the installable package.

Imports from `memory_fabric`; the core never imports from here (AGENTS.md).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
