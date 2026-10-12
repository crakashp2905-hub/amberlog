"""Sensitive-data detection on the ingestion path (SECURITY.md T6).

Pattern matching plus an entropy heuristic. It is a coarse net, and it is
documented as coarse: it will miss novel secret formats and it will flag some
harmless strings. The design consequence is that a positive finding leads to
quarantine and review rather than silent deletion, and that this detector is
never the only control on a restricted memory.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Pattern


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: str  # "high" | "medium"
    excerpt: str
    start: int
    end: int


# Ordered most specific first so a match is attributed to the tightest pattern.
_PATTERNS: list[tuple[str, str, Pattern[str]]] = [
    ("private_key", "high", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", "high", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", "high", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", "high", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("anthropic_key", "high", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b")),
    ("openai_key", "high", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("jwt", "high", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    # --- added 2026-10-13 -------------------------------------------------
    #
    # Thirteen patterns covered the credential classes this project happened to
    # think of. These are the ones plainly missing, chosen for a shape that
    # cannot plausibly occur by accident -- a fixed vendor prefix and a fixed
    # length -- so each adds coverage without adding false positives. Classes
    # needing a loose shape (an AWS *secret* key is 40 base64 characters with
    # no prefix) are deliberately left to the entropy check, because a pattern
    # for them would fire on every hash and ULID in a store.
    #
    # The count is not the point. `SECURITY.md` records the real weakness as
    # **no adversarial testing**, and more patterns do not address it; the test
    # corpus in `tests/test_sensitive_patterns.py` does, with a positive and a
    # near-miss negative for every class including the original thirteen.
    ("google_api_key", "high", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("google_oauth_secret", "high", re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{28}\b")),
    ("stripe_key", "high", re.compile(r"\b[srp]k_(?:live|test)_[0-9A-Za-z]{20,}\b")),
    ("gitlab_token", "high", re.compile(r"\bglpat-[0-9A-Za-z_-]{20}\b")),
    ("huggingface_token", "high", re.compile(r"\bhf_[A-Za-z0-9]{34,}\b")),
    ("npm_token", "high", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("sendgrid_key", "high", re.compile(r"\bSG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{40,}\b")),
    ("twilio_sid", "high", re.compile(r"\b(?:AC|SK)[0-9a-f]{32}\b")),
    ("slack_webhook", "high",
     re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{20,}")),
    # A connection string carries the password in the authority, so the whole
    # URI is the secret. Narrowed to known schemes: a generic `user:pass@host`
    # matches ordinary prose about email addresses.
    ("connection_string", "high", re.compile(
        r"\b(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis|amqp)://"
        r"[^\s:@/]+:[^\s:@/]+@\S+")),
    ("azure_storage_key", "high",
     re.compile(r"(?i)\bAccountKey\s*=\s*[A-Za-z0-9+/=]{40,}")),
    # Identity numbers with a checkable shape. `iban` is deliberately bounded
    # at 15 characters so it does not swallow arbitrary alphanumeric runs.
    ("iban", "high", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,28}\b")),
    ("ni_number_uk", "high",
     re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b")),
    (
        "password_assignment",
        "high",
        re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*\S{6,}"),
    ),
    ("credit_card", "high", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ("ssn_us", "high", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", "medium", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")),
    ("ipv4", "medium", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("phone", "medium", re.compile(r"(?<!\d)\+?\d[\d ()-]{8,}\d(?!\d)")),
]

_HIGH_ENTROPY = re.compile(r"\b[A-Za-z0-9+/=_-]{24,}\b")


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    total = len(text)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def _luhn_ok(digits: str) -> bool:
    """Checksum for card-number candidates, to cut false positives on any long
    run of digits (order ids, timestamps, phone numbers)."""
    numbers = [int(d) for d in digits if d.isdigit()]
    if not 13 <= len(numbers) <= 19:
        return False
    total = 0
    for index, digit in enumerate(reversed(numbers)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


class SensitiveDataDetector:
    def __init__(self, entropy_threshold: float = 4.0, check_entropy: bool = True) -> None:
        self.entropy_threshold = entropy_threshold
        self.check_entropy = check_entropy

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        covered: list[tuple[int, int]] = []

        def overlaps(start: int, end: int) -> bool:
            return any(start < c_end and end > c_start for c_start, c_end in covered)

        for kind, severity, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                start, end = match.span()
                if overlaps(start, end):
                    continue
                if kind == "credit_card" and not _luhn_ok(match.group()):
                    continue
                covered.append((start, end))
                findings.append(
                    Finding(
                        kind=kind,
                        severity=severity,
                        excerpt=_redact(match.group()),
                        start=start,
                        end=end,
                    )
                )

        if self.check_entropy:
            for match in _HIGH_ENTROPY.finditer(text):
                start, end = match.span()
                if overlaps(start, end):
                    continue
                if shannon_entropy(match.group()) >= self.entropy_threshold:
                    covered.append((start, end))
                    findings.append(
                        Finding(
                            kind="high_entropy_string",
                            severity="medium",
                            excerpt=_redact(match.group()),
                            start=start,
                            end=end,
                        )
                    )

        findings.sort(key=lambda f: f.start)
        return findings

    def has_high_severity(self, text: str) -> bool:
        return any(f.severity == "high" for f in self.scan(text))

    def redact(self, text: str) -> str:
        """Replace findings with typed placeholders, right to left so earlier
        spans keep their offsets."""
        out = text
        for finding in sorted(self.scan(text), key=lambda f: f.start, reverse=True):
            out = out[: finding.start] + f"[REDACTED:{finding.kind}]" + out[finding.end :]
        return out


def _redact(value: str, keep: int = 4) -> str:
    """Never echo a secret in full, not even into an audit record."""
    stripped = value.strip()
    if len(stripped) <= keep:
        return "*" * len(stripped)
    return stripped[:keep] + "*" * (len(stripped) - keep)


def summarise(findings: Iterable[Finding]) -> str:
    kinds = sorted({f.kind for f in findings})
    return ", ".join(kinds) if kinds else "none"


# --- scrubbing derived text -------------------------------------------------
#
# Lives here rather than in a display layer because more than one display layer
# needs it, and the one that forgot leaked a credential: `explain()` built a
# narrative straight from raw content while the dashboard scrubbed, so printing
# an explanation to a terminal showed the secret the firewall had quarantined.


def secret_values(detector: SensitiveDataDetector, text: str) -> list[tuple[str, str]]:
    """The literal secret values in a piece of content, with their kinds.

    Slices the original text at each finding's span: `Finding.excerpt` is
    already masked and so cannot be matched against derived strings.
    """
    return [(text[f.start : f.end], f.kind) for f in detector.scan(text)]


def scrub(text: str, secrets: Iterable[tuple[str, str]]) -> str:
    """Replace known secret values wherever they appear in derived text.

    Deliberately *not* a re-scan. Running the detector over derived strings
    flags things that merely look like secrets — a ULID reads as a high-entropy
    token — which mangles the output while adding no protection. Replacing the
    values already found in the source catches every copy without inventing new
    findings.
    """
    out = text
    # Longest first, so a secret contained inside another is not half-replaced.
    for value, kind in sorted(secrets, key=lambda pair: -len(pair[0])):
        if value:
            out = out.replace(value, f"[REDACTED:{kind}]")
    return out


def scrub_tree(payload: Any, secrets: Iterable[tuple[str, str]]) -> Any:
    """Scrub every string in a nested structure.

    Needed because a detail payload re-embeds the raw memory in more than one
    place, and missing any one of them leaks the value just as completely.
    """
    pairs = list(secrets)
    if isinstance(payload, str):
        return scrub(payload, pairs)
    if isinstance(payload, dict):
        return {k: scrub_tree(v, pairs) for k, v in payload.items()}
    if isinstance(payload, list):
        return [scrub_tree(v, pairs) for v in payload]
    return payload
