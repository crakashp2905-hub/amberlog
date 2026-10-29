"""Build the dashboard's limitations list from docs/LIMITATIONS.md.

    python tools/gen_limitations.py           # write amberlog/observability/static/limitations.json
    python tools/gen_limitations.py --check   # exit 1 if it is out of date
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "LIMITATIONS.md"
OUT = ROOT / "amberlog" / "observability" / "static" / "limitations.json"
ROW = re.compile(r"^\|\s*\*\*(?P<title>.+?)\*\*(?P<rest>.*?)\|\s*(?P<todo>.+?)\s*\|\s*$")


def strip_md(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.replace("**", "").replace("`", "").strip()


def build() -> list[dict[str, str]]:
    section = ""
    rows = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = ROW.match(line)
        if m and section:
            rows.append({"area": section, "limitation": strip_md(m["title"] + m["rest"]),
                         "what_to_do": strip_md(m["todo"])})
    return rows


def main() -> int:
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("limitations.json is out of date: run python tools/gen_limitations.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(json.loads(text))} limitations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
