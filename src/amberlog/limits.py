"""Store-level resource limits: bounded payloads, write quotas, federation budgets.

The HTTP surfaces already bound request bodies and rate-limit requests
(`agent_api.RateLimit`, `transport.MAX_BODY_BYTES`). Those protect a server,
not the store: a library caller, an MCP tool loop or a peer offering a flood
of imports reaches `remember` directly. These limits sit there.

- **Payload:** content above `max_content_bytes` is refused (default 1 MiB).
- **Write quota:** at most `writes_per_window` writes per agent per window.
- **Federation budget:** at most `imports_per_window` imports per origin
  store per window, so one peer cannot fill a recipient's review queue.

Quota counters are operational state, kept in memory and not in the log:
they protect the process now and say nothing about what the memory is. A
restart resets them, which is the usual behaviour of a rate limit. Quotas are
off by default in the library; the servers turn them on.
"""

from __future__ import annotations

__stability__ = "beta"

import threading
from collections import deque
from dataclasses import dataclass


class LimitExceeded(Exception):
    """A write was refused by a resource limit. Retrying later may succeed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Limits:
    max_content_bytes: int = 1024 * 1024
    writes_per_window: int | None = None
    imports_per_window: int | None = None
    window_ms: int = 60_000


SERVER_DEFAULTS = Limits(max_content_bytes=256 * 1024, writes_per_window=600,
                         imports_per_window=300)


class Meter:
    """Sliding-window counters for one store."""

    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self._seen: dict[str, deque[int]] = {}
        self._lock = threading.Lock()

    def check_write(self, agent_id: str, content: str, origin_store: str | None,
                    now_ms: int) -> None:
        size = len(content.encode("utf-8"))
        if size > self.limits.max_content_bytes:
            raise LimitExceeded("payload_too_large",
                                f"content is {size} bytes; the limit is "
                                f"{self.limits.max_content_bytes}")
        if origin_store is not None:
            self._take(f"import:{origin_store}", self.limits.imports_per_window, now_ms,
                       "federation_budget_exhausted")
        else:
            self._take(f"agent:{agent_id}", self.limits.writes_per_window, now_ms,
                       "write_quota_exhausted")

    def _take(self, key: str, budget: int | None, now_ms: int, code: str) -> None:
        if budget is None:
            return
        with self._lock:
            window = self._seen.setdefault(key, deque())
            while window and window[0] <= now_ms - self.limits.window_ms:
                window.popleft()
            if len(window) >= budget:
                raise LimitExceeded(code, f"{key} used {budget} writes in "
                                          f"{self.limits.window_ms} ms; try again later")
            window.append(now_ms)
