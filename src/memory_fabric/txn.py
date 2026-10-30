"""Nesting transactions, keyed per connection.

`sqlite3.Connection.__exit__` commits unconditionally and knows nothing about
nesting, so an inner `with conn:` inside an outer one commits the outer
transaction as well. That turned `MemoryFabric.request_retraction` — which
wraps a quarantine, an event append and the outbox rows in what looks like one
transaction — into three separate commits, because `EventLog.append_many` had
its own `with self._conn:` inside it.

The consequence was the exact half-state invariant 3 exists to prevent: a
memory withdrawn locally with the `RetractionRequested` event committed and the
outbox rows missing, so nothing recorded that any recipient was owed a
correction. Found by the multi-process kill tests; the in-process fault matrix
could not see it, because its "crash" closes a handle cleanly and a clean close
commits everything anyway.

The depth lives in a table keyed by **connection** rather than on any one
object, because `EventLog`, `Outbox` and `ContentVault` deliberately share one
connection in order to share one transactional boundary. If each kept its own
counter they would open nested transactions unaware of each other, which is the
bug again with more steps.

Keyed by `id(conn)` in a plain dict, because `sqlite3.Connection` is a C type
that cannot be weak-referenced and has no `__dict__` to hang state on. That
means entries do not disappear by themselves, so `EventLog.close` calls
`forget`. Each entry is a lock and an integer, and a leaked one is harmless —
but a process that opened stores in a loop would accumulate them, so the
cleanup is explicit rather than left to chance.
"""

from __future__ import annotations

__stability__ = "stable"

from .dbtypes import Connection

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator


class _State:
    __slots__ = ("lock", "depth")

    def __init__(self) -> None:
        # Re-entrant: an inner level must not block on the lock its own outer
        # level is holding.
        self.lock = threading.RLock()
        self.depth = 0


_STATES: dict[int, _State] = {}
_REGISTRY_LOCK = threading.Lock()


def _state_for(conn: Connection) -> _State:
    key = id(conn)
    with _REGISTRY_LOCK:
        state = _STATES.get(key)
        if state is None:
            state = _State()
            _STATES[key] = state
        return state


def forget(conn: Connection) -> None:
    """Drop a closed connection's entry. Called by `EventLog.close`.

    Safe to call on a connection mid-transaction only because closing one then
    is already a bug; the entry going away cannot make that worse, and keeping
    it would hold a lock nobody can release.
    """
    with _REGISTRY_LOCK:
        _STATES.pop(id(conn), None)


def depth(conn: Connection) -> int:
    return _state_for(conn).depth


@contextmanager
def transaction(conn: Connection) -> Iterator[None]:
    """One transaction, or one savepoint inside an open one.

    The outermost level issues `BEGIN IMMEDIATE` — the write lock is taken up
    front, so two writers conflict immediately rather than part-way through,
    when one has already done work it must discard. Inner levels use named
    savepoints, so a nested failure unwinds to its own savepoint and an outer
    caller can still choose to continue.

    Requires `isolation_level=None` on the connection. With sqlite3's default,
    a bare statement silently opens its own transaction and the explicit
    `BEGIN` here would fail or interleave.
    """
    state = _state_for(conn)
    with state.lock:
        name = f"mf_sp_{state.depth}"
        if state.depth == 0:
            conn.execute("BEGIN IMMEDIATE")
        else:
            conn.execute(f"SAVEPOINT {name}")
        state.depth += 1
        try:
            yield
        except BaseException:
            state.depth -= 1
            try:
                if state.depth == 0:
                    conn.execute("ROLLBACK")
                else:
                    conn.execute(f"ROLLBACK TO {name}")
                    conn.execute(f"RELEASE {name}")
            except sqlite3.Error:
                # The connection may already have aborted the transaction —
                # on a disk error, for instance. Losing the original exception
                # to a secondary failure during unwinding would hide the cause.
                pass
            raise
        state.depth -= 1
        if state.depth == 0:
            conn.execute("COMMIT")
        else:
            conn.execute(f"RELEASE {name}")
