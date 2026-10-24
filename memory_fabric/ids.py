"""ULID generation: lexicographically sortable, time-ordered identifiers.

Stdlib only. Monotonic within a millisecond so that event ordering by id is
stable even when many events are appended in the same tick.
"""

from __future__ import annotations

__stability__ = "stable"

import os
import threading
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIME_LEN = 10
_RAND_LEN = 16
_RAND_BITS = 80


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


class UlidFactory:
    """Creates ULIDs. Injectable so tests can pin time and randomness."""

    def __init__(self, time_ms=None, randbits=None) -> None:
        self._time_ms = time_ms or (lambda: int(time.time() * 1000))
        self._randbits = randbits or (lambda n: int.from_bytes(os.urandom((n + 7) // 8), "big") >> ((8 - n % 8) % 8))
        self._lock = threading.Lock()
        self._last_ms = -1
        self._last_rand = 0

    def new(self) -> str:
        with self._lock:
            now = self._time_ms()
            if now == self._last_ms:
                # Same millisecond: increment so ids stay strictly increasing.
                self._last_rand = (self._last_rand + 1) & ((1 << _RAND_BITS) - 1)
            else:
                self._last_ms = now
                self._last_rand = self._randbits(_RAND_BITS)
            return _encode(now, _TIME_LEN) + _encode(self._last_rand, _RAND_LEN)


_default = UlidFactory()


def new_ulid() -> str:
    return _default.new()


def ulid_time_ms(ulid: str) -> int:
    """Extract the millisecond timestamp encoded in a ULID."""
    value = 0
    for char in ulid[:_TIME_LEN]:
        value = value * 32 + _CROCKFORD.index(char)
    return value
