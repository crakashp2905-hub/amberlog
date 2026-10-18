"""Adapters: running real agents on the fabric.

The core is dependency-free and stays that way. An adapter for a specific
framework imports that framework lazily, so installing this package never drags
in an SDK the caller does not use.

- `context.py` — turning retrieved memories into prompt text. Framework-agnostic.
- `claude.py`  — the Claude API adapter (needs `pip install anthropic`).
- `transcripts.py` — turning existing conversation logs into episodic memories.
"""

__stability__ = "stable"

from .context import (
    INJECTION_PREAMBLE,
    MemoryBlock,
    MemoryContext,
    build_context,
    render_context,
)
from .transcripts import Turn, ingest_transcript

__all__ = [
    "INJECTION_PREAMBLE",
    "MemoryBlock",
    "MemoryContext",
    "build_context",
    "render_context",
    "Turn",
    "ingest_transcript",
]
