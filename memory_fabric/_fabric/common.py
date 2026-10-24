"""Shared by the MemoryFabric services: exceptions, result types and the `_fresh` decorator."""

from __future__ import annotations

__stability__ = "stable"


import functools

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from ..fabric import MemoryFabric  # noqa: F401
    pass

from datetime import datetime, timezone

from ..model import (
    Memory,
)



class FabricError(RuntimeError):
    pass


class NotFound(FabricError):
    pass


class PolicyViolation(FabricError):
    """Raised when a caller asks for something governance forbids."""


@dataclass
class RetrievalResult:
    """What the agent gets back, plus the record of what it did not get.

    `withheld` is returned deliberately: callers that log their own traces
    should be able to see that a candidate existed and was held back, because
    that is exactly the information a relevance-only system throws away.
    """

    exposed: list[Memory] = field(default_factory=list)
    withheld: list[Memory] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    policy_id: str = ""

    def __iter__(self):
        return iter(self.exposed)

    def __len__(self) -> int:
        return len(self.exposed)

    @property
    def contents(self) -> list[str]:
        return [m.content for m in self.exposed]


@dataclass
class HealthReport:
    total: int
    by_state: dict[str, int]
    by_scope: dict[str, int]
    by_type: dict[str, int]
    unverified: int
    contested: int
    quarantined: int
    never_exposed: int
    open_hypothesis_sets: int
    episodes: int
    episodes_with_outcome: int
    events: int


def iso_timestamp(ms: int) -> str:
    """RFC3339 UTC, for the protocol's `issued_at` / `at` fields.

    Advisory metadata only: it never decides precedence, because clocks
    disagree and a sender controls its own (docs/PROTOCOL.md §2).
    """
    return (
        datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )



def _screened_text(content: str, *metadata: Any) -> str:
    """The text the ingest screen must see: the content *and* every string in
    the metadata stored beside it.

    The screen used to read `content` alone. A secret put in `context` or
    `structured` was stored as an active memory, kept in plaintext (only the
    content is sealed), and copied into every conclusion `derive` drew from
    it, because derived memories inherit their parents' context. Found while
    writing the summary-leakage regression test (SAFETY_AND_SECURITY.md S8).
    Keys are included as well as values: a key is as able to carry a secret.
    """
    parts = [content]

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, Mapping):
            for key, item in value.items():
                walk(str(key))
                walk(item)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                walk(item)
        elif value is not None and not isinstance(value, (bool, int, float)):
            parts.append(str(value))

    for item in metadata:
        walk(item)
    return "\n".join(parts)


def _fresh(method):
    """Catch up on other processes' writes before serving, enforcing or writing.

    See `MemoryFabric.refresh`. Applied to the public entry points only:
    internal calls read `self.state` directly, so the cost is one indexed read
    per call made from outside.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        # Under the fabric's lock: the projection is plain dicts and the
        # connection is one sqlite3 connection, and neither may be used from
        # two threads at once. Re-entrant, so a public method calling another
        # takes it once.
        with self.lock:
            self.refresh()
            return method(self, *args, **kwargs)

    return wrapper


