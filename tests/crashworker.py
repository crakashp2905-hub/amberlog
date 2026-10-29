"""A child process that does one thing to a store and then dies hard.

Run as a script, never imported by the test that drives it. That separation is
the whole point: the existing fault matrix simulates a crash by closing a
handle and opening the same file, which is a *clean* shutdown and exercises
replay but not durability. SQLite flushes on close, Python runs `finally`
blocks and `atexit` hooks, and open transactions are rolled back politely.

Here a crash is `os._exit`, which runs no handlers, flushes no buffers and
closes no files — the process simply stops existing, as it would on a power
loss, an OOM kill or a container eviction. Anything the parent can still read
afterwards is genuinely durable rather than durable-looking.

Each scenario crashes at a named boundary. `commit` points are the interesting
ones, because that is where an intent exists in memory but not yet on disk, and
where the Phase D forwarding obligation is supposed to be inseparable from the
withdrawal it accompanies.

Usage:
    python crashworker.py <scenario> <store-path> [extra...]

Exit codes: 0 means the scenario ran to completion without crashing (only the
`_survive` variants do that); 70 means the scenario reached its crash point and
called `os._exit`, which the parent treats as success. Any other code is the
worker failing for an unintended reason, and the parent fails the test rather
than reading a crash it did not cause.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from amberlog import Amberlog, WithdrawalBasis  # noqa: E402
from amberlog.federation import offer  # noqa: E402
from amberlog.governance.firewall import (  # noqa: E402
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)
from amberlog.outbox import now_ms  # noqa: E402
from amberlog.protocol import PropagationState  # noqa: E402

CRASHED = 70


def permissive() -> Firewall:
    return Firewall(
        rules=[
            rule_must_be_active,
            rule_restricted_stays_private,
            rule_capabilities_must_be_granted,
        ]
    )


def open_store(path: str) -> Amberlog:
    return Amberlog(path, firewall=permissive(), auto_activate=True)


def die() -> None:
    """A hard crash: no handlers, no flush, no close."""
    sys.stdout.flush()
    os._exit(CRASHED)


_HELD: list = []


def open_transaction(fabric: Amberlog):
    """Enter the store's real transaction and never leave it.

    `__enter__` by hand rather than a `with` block, because the point is to die
    *inside* and a `with` block would unwind on the way out. Using the store's
    own `log.transaction()` rather than a raw `BEGIN` matters: that helper is
    what nests, and a bare BEGIN collides with it.

    The manager is parked in a module-level list, and that is load-bearing
    rather than tidiness. `transaction()` is a generator-based context manager
    suspended at its `yield`; drop the last reference and CPython closes the
    generator, which throws `GeneratorExit` at the yield, which the helper
    treats as a failure and **rolls the transaction back immediately**. The
    first version of this function returned the manager and the caller
    discarded it, so every "crash inside a transaction" scenario was really
    running with no transaction at all and silently autocommitting.
    """
    manager = fabric.log.transaction()
    manager.__enter__()
    _HELD.append(manager)
    return manager


# --- scenarios --------------------------------------------------------------


def seed(path: str, *_: str) -> int:
    """Write one memory and exit cleanly. The fixture every scenario starts from."""
    fabric = open_store(path)
    memory_id = fabric.remember(agent_id="ag", content="valve 7 is upstream of the pump")
    print(memory_id)
    fabric.close()
    return 0


def share(path: str, other: str, *_: str) -> int:
    source = open_store(path)
    target = open_store(other)
    memory_id = next(iter(source.state.memories))
    result = offer(source, memory_id, target, "ag-b", activate=True)
    if not result.accepted:
        print(f"offer refused: {result.reasons}", file=sys.stderr)
        return 1
    print(result.imported_memory_id)
    source.close()
    target.close()
    return 0


def crash_mid_retraction_transaction(path: str, recipient: str, *_: str) -> int:
    """Die *inside* the transaction that records a retraction.

    Nothing should survive: not the quarantine, not the `RetractionRequested`
    event, not the outbox row. A half-applied retraction — the memory withdrawn
    locally with no record that recipients are owed anything — is the exact
    failure invariant 3 exists to prevent, and the one a clean close cannot
    produce.
    """
    fabric = open_store(path)
    memory_id = next(iter(fabric.state.memories))
    open_transaction(fabric)
    fabric.quarantine(
        memory_id, reason="contradicted", actor="ops",
        basis=WithdrawalBasis.CONTRADICTED,
    )
    die()
    return 0  # pragma: no cover


def crash_after_retraction_commit(path: str, recipient: str, *_: str) -> int:
    """Commit the retraction, then die before any dispatch.

    The intent must still be owed afterwards. This is the scenario the
    in-process matrix already covers with a clean reopen; running it as a real
    kill is what turns "the code closes properly" into "the bytes are on disk".
    """
    fabric = open_store(path)
    memory_id = next(iter(fabric.state.memories))
    fabric.request_retraction(
        memory_id, reason="contradicted", recipients=[recipient],
        actor="ops", basis=WithdrawalBasis.CONTRADICTED,
    )
    die()
    return 0  # pragma: no cover


def crash_after_recipient_applies(path: str, origin_path: str, *_: str) -> int:
    """Apply an arriving retraction, commit, then die before acknowledging.

    The origin never learns it worked. On restart it re-sends, the recipient
    deduplicates on event identity and returns its *first* outcome, and the
    origin records enforcement. Convergence through a lost acknowledgement,
    which at-least-once delivery plus idempotent processing is supposed to
    give — tested here against a process that really died rather than one that
    returned an error.
    """
    recipient = open_store(path)
    origin = open_store(origin_path)
    retraction = next(iter(origin.retractions_since(-1)), None)
    if retraction is None:
        print("no retraction to deliver", file=sys.stderr)
        return 1
    ack = recipient.receive_retraction(retraction)
    print(ack.state.value)
    die()
    return 0  # pragma: no cover


def crash_mid_forwarding_commit(path: str, origin_path: str, *_: str) -> int:
    """Die inside the transaction that applies *and* forwards.

    Phase D commits the local withdrawal and the onward obligation together.
    A hard kill here must leave **neither** — a withdrawal with no recorded
    obligation would leave live copies two hops out that nothing in the
    federation is tracking, and nothing would notice, because the upstream
    acknowledgement would truthfully say `enforced` about the one copy it was
    asked about.
    """
    middle = open_store(path)
    origin = open_store(origin_path)
    retraction = next(iter(origin.retractions_since(-1)), None)
    if retraction is None:
        print("no retraction to deliver", file=sys.stderr)
        return 1
    open_transaction(middle)
    # The same work `receive_retraction` does, opened inside a transaction this
    # process will never commit.
    targets = middle._imports_of(retraction)
    if not targets:
        print("no import held", file=sys.stderr)
        return 1
    for local_id in targets:
        middle.quarantine(
            local_id, reason="retracted at origin", actor="origin",
            basis=WithdrawalBasis.RETRACTED_AT_ORIGIN,
        )
    middle._forward_retraction(retraction, targets)
    die()
    return 0  # pragma: no cover


def crash_mid_write(path: str, *_: str) -> int:
    """Die inside an uncommitted batch of ordinary writes.

    Not about retraction at all: about whether the database is still openable
    and replayable after a hard kill during a write. A corrupted store would
    make every other guarantee untestable.
    """
    fabric = open_store(path)
    open_transaction(fabric)
    for index in range(50):
        fabric.remember(agent_id="ag", content=f"observation {index}")
    die()
    return 0  # pragma: no cover


def dispatch_then_crash(path: str, *_: str) -> int:
    """Send a retraction, let the recipient commit it, then die before
    recording the acknowledgement.

    The mirror of `crash_after_recipient_applies`: here the *origin* loses the
    outcome. Its outbox row must still be owed, so a restart re-delivers rather
    than assuming the worst or the best.
    """
    from amberlog.dispatcher import Dispatcher
    from amberlog.transport import InProcessTransport

    fabric = open_store(path)
    rows = fabric.outbox.due(now_ms())
    if not rows:
        print("nothing due", file=sys.stderr)
        return 1
    # Deliberately *not* using the dispatcher's own commit: send, then die.
    transport = InProcessTransport({})
    try:
        transport.send(rows[0].recipient, rows[0].retraction)
    except Exception:
        pass
    die()
    return 0  # pragma: no cover


SCENARIOS = {
    "seed": seed,
    "share": share,
    "crash_mid_retraction_transaction": crash_mid_retraction_transaction,
    "crash_after_retraction_commit": crash_after_retraction_commit,
    "crash_after_recipient_applies": crash_after_recipient_applies,
    "crash_mid_forwarding_commit": crash_mid_forwarding_commit,
    "crash_mid_write": crash_mid_write,
    "dispatch_then_crash": dispatch_then_crash,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in SCENARIOS:
        print(f"usage: crashworker.py <{'|'.join(SCENARIOS)}> <path> [extra...]",
              file=sys.stderr)
        return 2
    return SCENARIOS[argv[0]](*argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
