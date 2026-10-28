"""Optional lossless phrase-dictionary summarizer for repetitive sessions.

Byte savings are not model-token savings. Models need a dictionary-aware reader
or authorized decoding; no downstream accuracy improvement is claimed.
"""
from __future__ import annotations

__stability__ = "experimental"

from collections import Counter
import json
import re
from typing import TYPE_CHECKING, Sequence

from .compaction import extractive

if TYPE_CHECKING:
    from .model import Memory

MAX_CHARS = 200_000
_REFERENCE = re.compile(r"~([A-P])~")


def encode_records(texts: Sequence[str]) -> str:
    """Deterministic lossless encoding, falling back to uncompressed JSON if larger."""
    if sum(map(len, texts)) > MAX_CHARS:
        raise ValueError("phrase compaction source exceeds its character budget")
    raw = list(texts)
    encoded = list(texts)
    dictionary: dict[str, str] = {}
    candidates: Counter[str] = Counter()
    if not any(_REFERENCE.search(t) for t in raw):
        for text in raw:
            spans = list(re.finditer(r"\S+", text))
            for width in range(3, 9):
                for start in range(len(spans) - width + 1):
                    phrase = text[spans[start].start():spans[start + width - 1].end()]
                    if any(ch.isdigit() for ch in phrase):
                        continue  # keep every numeric token/identifier visible to existing fact checks
                    if len(candidates) < 50_000 or phrase in candidates:
                        candidates[phrase] += 1
        ranked = sorted(candidates, key=lambda p: (-(len(p) - 3) * candidates[p] + len(p), p))
        for phrase in ranked:
            if len(dictionary) == 16:
                break
            pattern = re.compile(r"(?<!\S)" + re.escape(phrase) + r"(?!\S)")
            occurrences = sum(len(list(pattern.finditer(t))) for t in encoded)
            if occurrences < 3 or (len(phrase) - 3) * occurrences <= len(phrase) + 12:
                continue
            code = chr(ord("A") + len(dictionary))
            dictionary[code] = phrase
            encoded = [pattern.sub(f"~{code}~", t) for t in encoded]

    def dump(d: dict[str, str], rows: list[str]) -> str:
        return json.dumps({"dictionary": d, "records": rows}, ensure_ascii=False, separators=(",", ":"))

    payload, baseline = dump(dictionary, encoded), dump({}, raw)
    if len(payload.encode("utf-8")) >= len(baseline.encode("utf-8")):
        payload = baseline
    if decode_records(payload) != raw:
        raise ValueError("phrase encoding failed exact round-trip verification")
    return payload


def decode_records(payload: str) -> list[str]:
    """Decode data only; unknown references and oversized expansion are refused."""
    if len(payload) > MAX_CHARS * 3:
        raise ValueError("encoded payload exceeds the character budget")
    data = json.loads(payload)
    if not isinstance(data, dict) or set(data) != {"dictionary", "records"}:
        raise ValueError("invalid phrase dictionary envelope")
    dictionary, records = data["dictionary"], data["records"]
    if (not isinstance(dictionary, dict) or len(dictionary) > 16 or not isinstance(records, list)
            or any(not isinstance(t, str) for t in records)
            or any(not re.fullmatch(r"[A-P]", k) or not isinstance(v, str)
                   or _REFERENCE.search(v) for k, v in dictionary.items())):
        raise ValueError("invalid phrase dictionary fields")
    output = []
    size = 0
    for text in records:
        if dictionary:
            if any(m[1] not in dictionary for m in _REFERENCE.finditer(text)):
                raise ValueError("unknown phrase reference")
            # Calculate expansion before allocating a potentially oversized string.
            expanded = len(text) + sum(len(dictionary[m[1]]) - len(m[0]) for m in _REFERENCE.finditer(text))
            if size + expanded > MAX_CHARS:
                raise ValueError("decoded content exceeds the character budget")
            text = _REFERENCE.sub(lambda m: dictionary[m[1]], text)
        size += len(text)
        if size > MAX_CHARS:
            raise ValueError("decoded content exceeds the character budget")
        output.append(text)
    return output


def dictionary_summary(memories: Sequence["Memory"], disputes: Sequence[Sequence["Memory"]]) -> str:
    """Pass as compact_session(..., summarise=dictionary_summary); never a default."""
    if disputes:
        return extractive(memories, disputes)
    texts = [m.content for m in memories]
    payload = encode_records(texts)
    if len(payload.encode("utf-8")) >= len(" ".join(texts).encode("utf-8")):
        return extractive(memories, disputes)
    return payload
