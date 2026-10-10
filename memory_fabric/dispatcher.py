"""Phase 2 — the outbox dispatcher and reconciliation.

The dispatcher is what makes the outbox worth having: it drains delivery intent
that was committed durably, so a retraction owed before a crash is still owed
after one. It is deliberately a plain loop the caller drives rather than a
background thread, because a test needs to run exactly one pass and a crash
needs to be simulatable by simply not calling it again.

Reconciliation is the other half. An offline recipient misses deliveries; on
reconnect it asks each origin what it has missed **since its own cursor**.
Replaying too much is safe because processing is idempotent (Phase 1); replaying
too little is the only real failure, which is why the cursor belongs to the
recipient and is never the origin's guess about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .outbox import OutboxRow, now_ms
from .protocol import Acknowledgement, PropagationState, Retraction
from .transport import Transport, TransportError


@dataclass
class DispatchReport:
    """What one pass did. Every counter is something an operator asks about."""

    attempted: int = 0
    enforced: int = 0
    rejected: int = 0
    superseded: int = 0
    retrying: int = 0
    failed: int = 0
    refused_overstatement: int = 0
    """Acknowledgements claiming persistence with no state revision behind them.
    Counted rather than trusted: recording a guarantee that was not given is
    the failure the whole acknowledgement design exists to prevent."""

    errors: list[str] = field(default_factory=list)

    @property
    def settled(self) -> int:
        return self.enforced + self.rejected + self.superseded + self.failed


class Dispatcher:
    """Drains one store's outbox through a transport."""

    def __init__(self, fabric: Any, transport: Transport) -> None:
        self.fabric = fabric
        self.transport = transport

    def run_once(self, limit: int = 100) -> DispatchReport:
        report = DispatchReport()
        outbox = self.fabric.outbox
        for row in outbox.due(now_ms(), limit=limit):
            report.attempted += 1
            self._deliver(row, report)
        return report

    def drain(self, max_passes: int = 32, limit: int = 100) -> DispatchReport:
        """Run until nothing is due or `max_passes` is reached.

        Bounded because an unbounded drain on a permanently failing recipient is
        a spin, and the backoff that prevents it is in wall-clock time which a
        test does not want to wait for.
        """
        total = DispatchReport()
        for _ in range(max_passes):
            report = self.run_once(limit=limit)
            if report.attempted == 0:
                break
            for name in (
                "attempted", "enforced", "rejected", "superseded",
                "retrying", "failed", "refused_overstatement",
            ):
                setattr(total, name, getattr(total, name) + getattr(report, name))
            total.errors.extend(report.errors)
        return total

    def _deliver(self, row: OutboxRow, report: DispatchReport) -> None:
        """Send outside a transaction, then commit the outcome inside one.

        The split matters twice. Holding a write lock across network I/O would
        block every other writer for the duration of a timeout. And the state
        changes for one `(retraction, recipient)` — the acknowledgement and the
        advance — have to commit together or not at all, or an origin restart
        loses what a recipient confirmed. A test caught exactly that: the
        acknowledgements were visible on the open connection and gone after a
        reopen, because nothing had committed them.
        """
        outbox = self.fabric.outbox
        connection = self.fabric.log._conn
        try:
            ack = self.transport.send(row.recipient, row.retraction)
        except TransportError as exc:
            report.errors.append(f"{row.recipient}: {exc.detail}")
            with connection:
                if exc.permanent:
                    # A route that does not exist will not start existing. Fail
                    # visibly rather than retrying eight times first.
                    outbox.advance(
                        row.retraction_id, row.recipient,
                        PropagationState.FAILED, now_ms(), exc.detail,
                    )
                    report.failed += 1
                else:
                    state = outbox.record_attempt(row, now_ms(), exc.detail)
                    if state is PropagationState.FAILED:
                        report.failed += 1
                    else:
                        report.retrying += 1
            return

        with connection:
            self._absorb(row, ack, report)

    def _absorb(
        self, row: OutboxRow, ack: Acknowledgement, report: DispatchReport
    ) -> None:
        """Record one delivery's outcome. **Called inside a transaction** by
        `_deliver`; calling it outside one is how the durability bug returns."""
        outbox = self.fabric.outbox

        if ack.overstates_persistence:
            # The recipient claimed persisted/enforced/verified with no state
            # revision behind it. Refuse the claim rather than record it.
            report.refused_overstatement += 1
            report.errors.append(
                f"{row.recipient} claimed {ack.state.value} with no state revision"
            )
            outbox.record_attempt(row, now_ms(), "acknowledgement overstated state")
            report.retrying += 1
            return

        outbox.record_acknowledgement(ack)
        outbox.advance(row.retraction_id, row.recipient, PropagationState.DELIVERED, now_ms())

        if ack.state is PropagationState.ENFORCED:
            # The recipient persisted *and* stopped exposing the version, so the
            # intermediate state is recorded and then advanced through.
            outbox.advance(
                row.retraction_id, row.recipient, PropagationState.PERSISTED, now_ms()
            )
            outbox.advance(
                row.retraction_id, row.recipient, PropagationState.ENFORCED, now_ms()
            )
            report.enforced += 1
        elif ack.state is PropagationState.PERSISTED:
            outbox.advance(
                row.retraction_id, row.recipient, PropagationState.PERSISTED, now_ms()
            )
        elif ack.state is PropagationState.SUPERSEDED:
            outbox.advance(
                row.retraction_id, row.recipient,
                PropagationState.SUPERSEDED, now_ms(), ack.detail,
            )
            report.superseded += 1
        elif ack.state is PropagationState.REJECTED:
            outbox.advance(
                row.retraction_id, row.recipient,
                PropagationState.REJECTED, now_ms(),
                ack.rejection_code or ack.detail,
            )
            report.rejected += 1
        else:
            # received / unknown / pending_review: no durable claim was made, so
            # it stays owed.
            outbox.record_attempt(row, now_ms(), f"recipient said {ack.state.value}")
            report.retrying += 1


def reconcile(
    recipient: Any, origin_retractions: Sequence[Retraction], origin_store_id: str
) -> list[Acknowledgement]:
    """Apply everything an origin replayed after an outage.

    Sorted by `origin_sequence` so a replay is applied in the origin's own
    order: feeding a newer retraction before an older one would have the older
    one refused as `superseded` when it should simply have been applied first.
    Idempotency means re-applying what the recipient already has is free.
    """
    ordered = sorted(origin_retractions, key=lambda r: r.origin_sequence)
    acks: list[Acknowledgement] = []
    for retraction in ordered:
        if retraction.origin_store_id != origin_store_id:
            # A replay from one origin must not carry another's events; that
            # would let a compromised peer retract on someone else's behalf.
            continue
        acks.append(recipient.receive_retraction(retraction, sender_authorised=True))
    return acks
