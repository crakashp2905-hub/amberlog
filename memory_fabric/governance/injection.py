"""Prompt-injection screening on the ingestion path.

The read side already defends against a retrieved memory hijacking a prompt:
`adapters/context.py` delimits memories, labels them as evidence and survives a
memory containing its own closing delimiter. That stops a memory *escaping* its
block. It does nothing about a memory whose content is an instruction aimed at
whatever model reads it later -- "ignore your previous instructions and ..." --
which, once validated and shared, is a persistent injection delivered to every
agent that recalls it. Memory is a better carrier for an injection than a single
prompt, because it outlives the conversation that planted it.

So this screens on the way in, like the sensitive-data detector, and with the
same posture: coarse, pattern-based, documented as coarse, and never the only
control. A high-confidence finding quarantines the write rather than dropping
it, because that an agent tried to memorise an injection is itself worth an
audit row. Softer signals warn.

Every pattern has a positive and a near-miss negative in
`tests/test_injection_patterns.py`, and the test refuses a pattern without both
-- the discipline the sensitive-data screen learned the hard way.
"""

from __future__ import annotations

import re
from typing import Pattern

from .sensitive import Finding

_PATTERNS: list[tuple[str, str, Pattern[str]]] = [
    # Telling the reader to drop the instructions it was given. Requires both
    # the override verb and an instruction noun, so "ignore previous alarms" is
    # not caught.
    ("instruction_override", "high", re.compile(
        r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|the\s+|your\s+)?"
        r"(?:previous|prior|above|earlier|preceding|system|original)\s+"
        r"(?:instructions?|prompts?|rules|directives|guidelines|messages?)\b",
        re.IGNORECASE)),
    # Chat-template control tokens. Prose about templates spells them out with
    # spaces or backticks; an injection needs the exact token.
    ("role_tag", "high", re.compile(
        r"<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>"
        r"|\[/?INST\]"
        r"|</?(?:system|assistant)>",
        re.IGNORECASE)),
    # Asking the reader to disclose its own instructions or credentials.
    ("prompt_exfiltration", "high", re.compile(
        r"\b(?:reveal|print|output|repeat|show|leak|dump)\s+(?:me\s+)?(?:your|the)\s+"
        r"(?:system\s+prompt|hidden\s+instructions|initial\s+instructions|api\s+keys?)\b",
        re.IGNORECASE)),
    # Re-casting the reader's identity. Ordinary text says "you are now
    # connected", so this needs a role word after it, and it only warns.
    ("persona_override", "medium", re.compile(
        r"\byou\s+are\s+now\s+(?:a|an|the|in)\s+(?:\w+\s+){0,2}"
        r"(?:assistant|ai|model|mode|agent|jailbreak|dan)\b",
        re.IGNORECASE)),
]


class InjectionDetector:
    """Finds instruction-like content aimed at a model that later reads it."""

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for kind, severity, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                findings.append(Finding(
                    kind=kind, severity=severity,
                    # The excerpt is the matched phrase itself: it is the
                    # evidence a reviewer needs, and unlike a secret it is not
                    # harmful to display.
                    excerpt=match.group(0)[:80],
                    start=match.start(), end=match.end(),
                ))
        return findings


PATTERN_KINDS = tuple(kind for kind, _, _ in _PATTERNS)
