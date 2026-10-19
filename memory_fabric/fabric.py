"""MemoryFabric: the public facade, per SPEC.md section 6.

Everything a caller does becomes an event first and state second. State is a
projection that can be thrown away and rebuilt, which is what makes the audit
trail trustworthy: there is no way to change a memory without leaving a record,
because the record *is* the change.
"""

from __future__ import annotations

__stability__ = "stable"

import functools

import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

if TYPE_CHECKING:
    from .protocol import SourceNotice  # pragma: no cover
    from .certificates import CertificateVerification, EvidenceCertificate
    from .session import AgentSession

from . import events as ev
from .estimators import ValueEstimator, build_estimator
from .eventlog import EventLog
from .exposure import Candidate, ExposurePolicy, build_policy
from .governance.firewall import Firewall, FirewallRequest, FirewallRuling
from .governance.retention import RetentionDecision, RetentionPolicy
from .ids import new_ulid
from . import chains
from . import duplicates
from . import rerank as reranking
from . import extraction as extracting
from .relations import PULLS_IN_SUBJECT, RelationKind
from .relevance import ReasonCode as _ReasonCode
from .lineage import LineageGraph, LineageView
import hashlib
import json
from datetime import datetime, timezone

from .justification import JustificationGraph
from .enforcement import (
    AccessDecision,
    EnforcedRead,
    Enforcer,
    ExposureToken,
    RiskLevel,
    Verdict,
)
from .governance.cipher import associated_data, is_sealed
from .governance.erasure import (
    ERASED_MARKER,
    ContentVault,
    KeyProvider,
    seal,
    unseal,
)
from .outbox import Outbox, now_ms as _now_ms
from .protocol import (
    MAX_HOPS,
    PROTOCOL_VERSION,
    Acknowledgement,
    PropagationState,
    RejectionCode,
    Retraction,
    new_retraction_id,
    new_store_id,
)
from .identity import (
    DEFAULT_TENANT,
    Credential,
    IdentityError,
    Principal,
    PrincipalRegistry,
)
from .model import (
    SCHEMA_VERSION,
    BLOCKED_STATES,
    EXPLORATORY_STATES,
    EXPOSABLE_STATES,
    WITHDRAWN_STATES,
    FirewallDecision,
    LifecycleState,
    Memory,
    MemoryStats,
    MemoryType,
    Provenance,
    ProvenanceMethod,
    Scope,
    SecurityClass,
    WithdrawalBasis,
    ValueEstimate,
    context_key,
    visible_to,
)
from .projections import Episode, Projection, _digest
from .vectors import (
    MIN_RELEVANCE,
    Embedder,
    LexicalIndex,
    VectorIndex,
    fuse,
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


class MemoryFabric:
    """Single-process memory fabric with a governed write and share path."""

    def __init__(
        self,
        path: str | Path = ":memory:",
        estimator: str | ValueEstimator = "naive_usage",
        exposure_policy: str | ExposurePolicy = "top_k",
        firewall: Firewall | None = None,
        retention: RetentionPolicy | None = None,
        embedder: Embedder | None = None,
        seed: int | None = None,
        clock=None,
        auto_activate: bool = False,
        encrypt_content: bool = True,
        key_provider: "KeyProvider | None" = None,
        retrieval: str = "lexical",
        busy_timeout_ms: int = 5_000,
        recognise_copies: bool = True,
        rerank: bool = False,
        conceal_cross_tenant: bool = False,
    ) -> None:
        # Off by default to keep the documented reason code. On, a request
        # from another tenant is refused exactly as a missing id is, so the
        # refusal does not confirm that the id exists anywhere (plan Task 11).
        self.conceal_cross_tenant = conceal_cross_tenant
        # Default on, because the alternative is measured to be wrong rather
        # than merely unmeasured: a withdrawn document re-ingested under its own
        # id was **100% of the residual** in P3, counted as independent support
        # by every rule tested, and carried a withdrawal that never reached its
        # restatement. The cost is a linear scan of held content per write,
        # which is why it is switchable for a store that ingests in bulk and
        # would rather run the check as a batch job.
        self.recognise_copies = recognise_copies
        # One lock for everything that touches this fabric's connection and
        # projection. Threaded servers (agent API, dashboard, federation)
        # hold it per request, so a process serving several of them on one
        # store is still serialised. See tests/test_concurrent_requests.py.
        self.lock = threading.RLock()
        # Off by default until it passes its registered bar
        # (research/prereg/r2a-feature-reranker.md). A mechanism that has not
        # been measured does not become a default, and this project has a
        # standing record of mechanisms that looked right and were not.
        # True selects the default mode; a string names one explicitly, so a
        # benchmark can measure "replace" against "tiebreak" without a second
        # constructor argument.
        self.rerank = rerank
        # Bounded candidate lookup for the subset test. The exhaustive scan it
        # replaces cost 32.4 ms a write at 10,000 memories against 0.19 ms
        # with the check off -- a 168x write cost growing linearly, which made
        # the default indefensible (see research/results/p4-envelope.md).
        self.copy_index = duplicates.CopyIndex()
        # memory id -> content terms, and the same minus bare numerals. The
        # second is what an edge in a chain may be built from, and splitting
        # it here keeps the numeric test out of the search's inner loop.
        self.chain_terms: dict[str, frozenset[str]] = {}
        self.chain_plain: dict[str, frozenset[str]] = {}
        # Structure extracted from a memory's content, when a caller supplies
        # it. An index like any other, and not populated on the write path:
        # extraction costs a model call per memory, and
        # `research/prereg/x1-extraction-at-ingest.md` predicts the measurement
        # will make it a batch job rather than an ingest-path step.
        self.extracted: dict[str, "extracting.Extracted"] = {}
        self.log = EventLog(path, busy_timeout_ms=busy_timeout_ms)
        # Everything after opening the log can fail — a missing key store
        # makes every sealed memory unreadable and `KeyUnavailable`
        # propagates from the replay. Closing the connection on the way out
        # matters on Windows, where a leaked handle keeps the file locked
        # and the next attempt fails for a different and misleading reason.
        try:
            # The vault must exist before the replay: the projection unseals as it
            # folds, so the keys have to be reachable first.
            #
            # `key_provider` is a constructor argument and not a settable
            # attribute, because by the time a caller could assign one the replay
            # has already tried to unseal every memory with the default. A test
            # that swapped it afterwards failed on exactly that, which is the API
            # telling the truth about when the decision has to be made.
            self.vault = ContentVault(
                self.log._conn, keys=key_provider, now_ms=self.now
            )
            self.encrypt_content = encrypt_content
            self.projection = Projection(unsealer=self._unseal_content)
            self._seen_seq = 0
            self.index = VectorIndex(embedder)
            # The arm the product was missing. `relevance_v1` measured the
            # vector path as the weakest non-broken arm, losing to
            # IDF-weighted token overlap by up to 32 points on the frozen
            # split, because `HashingEmbedder` is a hashed bag of words rather
            # than a trained model.
            self.lexical = LexicalIndex()
            self.retrieval_mode = retrieval
            self.firewall = firewall or Firewall()
            self.retention = retention or RetentionPolicy()
            self.estimator = build_estimator(estimator)
            self.policy = build_policy(exposure_policy)
            self.rng = random.Random(seed)
            self._clock = clock or (lambda: int(time.time() * 1000))
            # When true, a clean memory becomes active immediately. Off by default:
            # a new memory is a candidate until something validates it.
            self.auto_activate = auto_activate
            self._estimator_dirty = True
            self._enforcer: Enforcer | None = None
            self._principals: PrincipalRegistry | None = None
            self._justifications: JustificationGraph | None = None
            # Read from the log *before* the replay, not from the projection.
            # The ciphertext AAD binds the store id, and `_replay` builds a new
            # projection and only assigns it when finished — so during the replay
            # `self.state` is still the empty one and `self.store_id` asserts.
            # Caught by the erasure tests on reopen: a store with sealed content
            # could not be opened at all.
            self._sealing_store_id = self._store_id_from_log()
            self._replay()
            self.outbox = Outbox(self.log._conn)
            self._ensure_store_identity()
        except BaseException:
            self.log.close()
            raise

    def _unseal_content(self, content: str, memory_id: str, version: int = 1) -> str:
        """Decrypt on the way out of the log, or report erasure.

        Text written before encryption existed passes through untouched, which
        is what keeps a 0.2.0 log replayable.

        A failed authentication raises rather than returning anything. The
        previous cipher could not fail — it had no tag — and decoded with
        `errors="replace"`, so tampered bytes became mojibake inside a
        `Memory.content` and travelled into an agent's context as if they were
        remembered facts.
        """
        if not is_sealed(content):
            return content
        return unseal(
            content,
            self.vault.key_for(memory_id, self.now()),
            self._content_aad(memory_id, version),
        )

    def _seal_content(self, content: str, memory_id: str, version: int = 1) -> str:
        """Encrypt on the way into the log, when the store is configured to.

        Without this, `erase_content` destroys a key that was never used and the
        plaintext stays in the event log — which would make erasure cosmetic
        rather than real. Found by actually erasing something and reading the
        log back.
        """
        if not self.encrypt_content:
            return content
        key = self.vault.key_for(memory_id, self.now())
        if key is None:
            # The key was destroyed. Falling back to plaintext here would store
            # readable content for a memory whose content was erased — and
            # unsealed, so a later erasure could not reach it either. Refuse.
            raise PolicyViolation(
                f"{memory_id} has been content-erased; its content cannot be "
                "written again. Record new information as a new memory."
            )
        return seal(content, key, self._content_aad(memory_id, version))

    def _ensure_store_identity(self) -> None:
        """Mint this store's opaque identity once and record it in its own log.

        Recorded as an event rather than read from configuration because the
        identity has to survive a restore from backup, and the log is the only
        thing guaranteed to. A mis-deployed config would otherwise silently
        re-identify a store, and every retraction addressed to the old id would
        go nowhere.

        Existing logs predate this, so a store without the event mints one on
        first open — an additive migration, no schema break.
        """
        if self.state.store_id is None:
            self._emit(ev.store_identified(ts=self.now(), store_id=new_store_id()))
        self._sealing_store_id = self.state.store_id

    def _store_id_from_log(self) -> str | None:
        """This store's id straight from its `StoreIdentified` event.

        Deliberately not via the projection: this is needed *while* the
        projection is being rebuilt. Returns None for a store that has never
        been identified, which is a store with no memories either, so nothing
        needs the AAD yet.

        **Two distinct identities is a fatal condition, not a tie to break.**
        It means events were copied from another store into this one, event by
        event. The copied memories' content is sealed with the *source* store's
        id in its associated data, so picking either identity makes the other
        store's content undecryptable — and the failure surfaces much later as
        `content failed authentication (AES-GCM)`, which sends whoever reads it
        looking for a tamper that never happened.

        Found by a shipped example doing exactly this: building a fresh store
        and replaying another's events into it. That is not a backup. Use
        `memory-fabric backup`, which copies the file and therefore the
        identity.
        """
        identities: list[str] = []
        for event in self.log.read_types([ev.EventType.STORE_IDENTIFIED]):
            store_id = event.payload.get("store_id")
            if store_id and str(store_id) not in identities:
                identities.append(str(store_id))
        if len(identities) > 1:
            raise PolicyViolation(
                f"this log contains {len(identities)} store identities "
                f"({', '.join(identities)}), which happens when one store's "
                "events are replayed into another. Content sealed by one store "
                "cannot be read under another's identity, so there is no "
                "correct choice here. Copy the file with `memory-fabric "
                "backup` instead of replaying events."
            )
        return identities[0] if identities else None

    def _content_aad(self, memory_id: str, version: int) -> bytes:
        """The associated data a content ciphertext is bound to.

        Raises rather than substituting a placeholder when the store has no
        identity: sealing under `""` and later unsealing under a real id would
        fail authentication on every read, and the failure would look like
        tampering instead of like the configuration error it is.
        """
        store_id = self._sealing_store_id or self.state.store_id
        if store_id is None:
            raise PolicyViolation(
                "cannot seal or unseal content before this store has an "
                "identity; the StoreIdentified event is missing from the log"
            )
        return associated_data(store_id, memory_id, version)

    @property
    def store_id(self) -> str:
        """This store's identity. Never a path: the old origin record used
        `log.path`, so two containers each holding `./store.db` were
        indistinguishable and `:memory:` identified every in-memory store."""
        assert self.state.store_id is not None, "store identity not minted"
        return self.state.store_id

    # --- durable retraction protocol -------------------------------------

    def request_retraction(
        self,
        memory_id: str,
        reason: str,
        recipients: Sequence[str],
        actor: str = "operator",
        basis: str | WithdrawalBasis | None = None,
    ) -> Retraction:
        """Quarantine locally **and** durably record that the retraction is owed
        to each recipient — in one transaction.

        This is what `propagate_retraction` could not do. That function
        committed the local quarantine and then looped over live target objects
        in the same call, so a crash in between lost the dispatch with no record
        that it was owed. Here the `RetractionRequested` event and the outbox
        rows commit together, so a crash leaves the intent recorded and a
        dispatcher picks it up (invariant 3).

        Returns the `Retraction` for dispatch. It names an **exact version**:
        matching on the memory id alone would withdraw an import of v3 on a
        retraction of v1.
        """
        memory = self._require(memory_id)
        retraction = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=self.store_id,
            origin_memory_id=memory_id,
            origin_memory_version=memory.version,
            origin_sequence=self.state.origin_sequence + 1,
            reason_code=(
                basis.value if isinstance(basis, WithdrawalBasis) else basis
            ) or WithdrawalBasis.UNSTATED.value,
            requested_by=actor,
            issued_at=iso_timestamp(self.now()),
        )

        with self._transaction():
            self.quarantine(memory_id, reason=reason, actor=actor, basis=basis)
            self._emit(
                ev.retraction_requested(
                    ts=self.now(),
                    retraction_id=retraction.retraction_id,
                    origin_store_id=retraction.origin_store_id,
                    origin_memory_id=retraction.origin_memory_id,
                    origin_memory_version=retraction.origin_memory_version,
                    origin_sequence=retraction.origin_sequence,
                    reason_code=retraction.reason_code,
                    recipients=list(recipients),
                    requested_by=actor,
                )
            )
            self.outbox.enqueue(retraction, recipients, _now_ms())
        return retraction

    def authority(self, memory_id: str) -> "Any":
        """Origin-bound authority of a memory (`authority.py`)."""
        from . import authority

        self._require(memory_id)
        return authority.of(self, memory_id)

    @_fresh
    def elevate(self, memory_id: str, approver: str, reason: str,
                policy: str = "manual-review", revoke: bool = False) -> "Any":
        """Lift a memory version's *soft* authority reasons, after review.

        Refused when the approver wrote the memory, or when a hard reason
        (withdrawn or contested ancestor, hostile source, instruction) stands:
        those are removed at their cause, not overridden.
        """
        from . import authority

        memory = self._require(memory_id)
        current = authority.of(self, memory_id)
        if not revoke:
            if approver == memory.provenance.created_by or approver in current.origins:
                raise PolicyViolation("a memory's author or source cannot elevate it")
            if current.hard:
                raise PolicyViolation(
                    f"cannot elevate past hard reasons: {sorted(r for r in current.reasons if r in authority.HARD)}")
        self._emit(ev.authority_elevated(ts=self.now(), memory_id=memory_id,
                                         version=memory.version, approver=approver,
                                         policy=policy, reason=reason, revoked=revoke))
        return authority.of(self, memory_id)

    @_fresh
    def discredit_source(self, author: str, actor: str, signal: str = "hostile",
                         reason_code: str = "injection_screen") -> "SourceNotice":
        """Record that a local source was caught being hostile; return the notice for peers.

        Idempotent per (author, signal). The notice goes to the stores that
        hold this author's shared memories (`notice_recipients`), and the
        background manager sends it (`manager.py`).
        """
        from .protocol import SOURCE_SIGNALS, SourceNotice

        if signal not in SOURCE_SIGNALS:
            raise PolicyViolation(f"signal must be one of {SOURCE_SIGNALS}")
        notice_id = "sn_" + hashlib.sha256(
            f"{self.store_id}/{author}/{signal}".encode()).hexdigest()[:26]
        if not any(e.payload.get("notice_id") == notice_id
                   for e in self.log.read_types([ev.EventType.SOURCE_DISCREDITED])):
            self._emit(ev.source_discredited(ts=self.now(), author_ref=author, signal=signal,
                                             origin_store_id=self.store_id,
                                             notice_id=notice_id, reason_code=reason_code,
                                             actor=actor))
        return SourceNotice(notice_id=notice_id, origin_store_id=self.store_id, author=author,
                            signal=signal, reason_code=reason_code,
                            issued_at=iso_timestamp(self.now()))

    def notice_recipients(self, author: str) -> list[str]:
        """Stores holding a memory this author wrote here and shared."""
        out: set[str] = set()
        for memory_id, recipients in self.state.shared_to.items():
            memory = self.state.memories.get(memory_id)
            if memory is not None and memory.provenance.created_by == author:
                out.update(recipients)
        return sorted(out)

    @_fresh
    def receive_notice(self, notice: "SourceNotice", sender_authorised: bool = True) -> bool:
        """Record a peer's signed notice. Idempotent. Returns whether it was accepted."""
        author_ref = f"{notice.origin_store_id}/{notice.author}"
        seen = any(e.payload.get("notice_id") == notice.notice_id
                   and e.payload.get("authorised")
                   for e in self.log.read_types([ev.EventType.SOURCE_DISCREDITED]))
        if seen:
            return True
        self._emit(ev.source_discredited(ts=self.now(), author_ref=author_ref,
                                         signal=notice.signal,
                                         origin_store_id=notice.origin_store_id,
                                         notice_id=notice.notice_id,
                                         reason_code=notice.reason_code,
                                         actor=notice.origin_store_id,
                                         authorised=sender_authorised))
        return sender_authorised

    @_fresh
    def supersede_copies(self, memory_id: str, actor: str) -> list[Retraction]:
        """Owe every store holding an older version's copy a retraction of that version.

        A revision changed nothing in the stores that held a copy: only
        retractions travel, and offering the new version left the old import
        active beside it (found by G4; research direction S1). This is the
        correction half: for each store that was sent an older version, a
        retraction of **that version only** -- `contradicted`, with
        `evidence_reference` naming the version that replaced it -- through the
        same outbox, transport and dispatcher as any retraction. The origin's
        own current version is not withdrawn. A recipient withdraws exactly the
        copy of that version (supersession is per memory and version, F11), and
        its conclusions built on that copy are re-checked like any retraction's.

        Offering the current version is the host's step, as every share is
        (`federation.offer`). Idempotent: a (version, store) already owed is not
        owed twice. Returns the retractions, one per superseded version.
        """
        memory = self._require(memory_id)
        held: dict[str, set[int]] = {}
        for event in self.log.read_types([ev.EventType.MEMORY_SHARED]):
            if event.payload.get("memory_id") == memory_id:
                held.setdefault(event.payload["recipient_store_id"], set()).add(
                    int(event.payload.get("version", 1)))
        already = {
            (int(e.payload.get("origin_memory_version", 0)), recipient)
            for e in self.log.read_types([ev.EventType.RETRACTION_REQUESTED])
            if e.payload.get("origin_memory_id") == memory_id
            for recipient in e.payload.get("recipients") or ()
        }
        owed: dict[int, list[str]] = {}
        for recipient, versions in sorted(held.items()):
            for version in sorted(versions):
                if version < memory.version and (version, recipient) not in already:
                    owed.setdefault(version, []).append(recipient)
        out: list[Retraction] = []
        with self._transaction():
            for version, recipients in sorted(owed.items()):
                retraction = Retraction(
                    retraction_id=new_retraction_id(),
                    origin_store_id=self.store_id,
                    origin_memory_id=memory_id,
                    origin_memory_version=version,
                    origin_sequence=self.state.origin_sequence + 1,
                    reason_code=WithdrawalBasis.CONTRADICTED.value,
                    requested_by=actor,
                    issued_at=iso_timestamp(self.now()),
                    evidence_reference=f"superseded by version {memory.version}",
                )
                self._emit(ev.retraction_requested(
                    ts=self.now(), retraction_id=retraction.retraction_id,
                    origin_store_id=retraction.origin_store_id,
                    origin_memory_id=memory_id, origin_memory_version=version,
                    origin_sequence=retraction.origin_sequence,
                    reason_code=retraction.reason_code, recipients=recipients,
                    requested_by=actor))
                self.outbox.enqueue(retraction, recipients, _now_ms())
                out.append(retraction)
        return out

    def record_share(
        self,
        memory_id: str,
        recipient_store_id: str,
        imported_memory_id: str,
        actor: str = "federation",
    ) -> None:
        """Record that `memory_id` left this store for `recipient_store_id`.

        The forwarding table a transitive retraction walks. `federation.offer`
        calls this on every accepted offer, so a store that re-shares an import
        knows who else now holds it.

        Not derivable after the fact: the recipient's copy is a new memory in
        the recipient's log with its own id, and nothing in the sender's log
        mentioned it until this event existed. Phase B worked without it only
        because its recipients never re-shared, which made the origin exactly
        one hop from every copy in the federation.
        """
        memory = self._require(memory_id)
        self._emit(
            ev.memory_shared(
                ts=self.now(),
                memory_id=memory_id,
                version=memory.version,
                recipient_store_id=recipient_store_id,
                imported_memory_id=imported_memory_id,
                actor=actor,
            )
        )

    def shared_with(self, memory_id: str) -> dict[str, str]:
        """Which stores hold a copy of this memory, and what they call it."""
        return dict(self.state.shared_to.get(memory_id, {}))

    def receive_retraction(
        self, retraction: Retraction, sender_authorised: bool = True
    ) -> Acknowledgement:
        """Apply a retraction arriving from another store, idempotently.

        The order is the one docs/PROTOCOL.md §5 specifies, and the ordering
        matters: deduplication comes before the version check so a replay gets
        the *first* outcome rather than a fresh verdict.

        Returns an acknowledgement of **committed** state only. `persisted`
        after the commit, `enforced` once the projections no longer expose the
        version. Acknowledging on receipt would be the most damaging lie
        available here.
        """
        at = iso_timestamp(self.now())

        def ack(state: PropagationState, detail: str = "", code: str | None = None):
            return Acknowledgement(
                retraction_id=retraction.retraction_id,
                recipient_store_id=self.store_id,
                state=state,
                at=at,
                # Per origin, not the log head. The head told every origin how
                # much this store did between two of its retractions, which is
                # none of its business (security review F13, measured by S5).
                # A count of this origin's applied retractions still regresses
                # when the store is restored from an older backup, which is
                # what the field is for.
                state_revision=self.outbox.inbox_count(retraction.origin_store_id),
                origin_sequence_seen=self.outbox.cursor_for(retraction.origin_store_id),
                detail=detail,
                rejection_code=code,
            )

        if not sender_authorised:
            self._emit(
                ev.retraction_rejected(
                    ts=self.now(),
                    retraction_id=retraction.retraction_id,
                    origin_store_id=retraction.origin_store_id,
                    rejection_code=RejectionCode.UNAUTHORIZED.value,
                    detail="sender not authorised for this destination",
                    actor=self.store_id,
                )
            )
            return ack(
                PropagationState.REJECTED,
                "sender not authorised",
                RejectionCode.UNAUTHORIZED.value,
            )

        # 4. Deduplicate on event identity, before anything else can change.
        previous = self.outbox.seen(retraction)
        if previous is not None:
            outcome, detail = previous
            state = {
                "applied": PropagationState.ENFORCED,
                "superseded": PropagationState.SUPERSEDED,
                "unknown_memory": PropagationState.REJECTED,
            }.get(outcome, PropagationState.REJECTED)
            return ack(state, f"duplicate: {outcome}")

        # 5. Supersession, per origin memory. It used to compare against one
        #    cursor per *origin store*, so a retraction delayed by an outage
        #    was discarded as "superseded" once a later retraction of a
        #    *different* memory had arrived first -- and the withdrawn memory
        #    stayed active here while the origin recorded the delivery as
        #    settled (docs/SECURITY_REVIEW.md F11). Stale means: a retraction of
        #    this same memory *and version* with a higher origin sequence was
        #    already applied. Version too, because a correction withdraws copies
        #    version by version, and a retraction of the v2 copy arriving before
        #    the one for the v1 copy must not discard it.
        cursor = self._latest_applied_sequence(retraction.origin_store_id,
                                               retraction.origin_memory_id,
                                               retraction.origin_memory_version)
        if cursor is not None and retraction.origin_sequence < cursor:
            with self._transaction():
                self.outbox.record_inbox(
                    retraction, "superseded", f"below cursor {cursor}", _now_ms()
                )
                self._emit(
                    ev.retraction_rejected(
                        ts=self.now(),
                        retraction_id=retraction.retraction_id,
                        origin_store_id=retraction.origin_store_id,
                        rejection_code=RejectionCode.VERSION_SUPERSEDED.value,
                        detail=f"origin_sequence {retraction.origin_sequence} below cursor {cursor}",
                        actor=self.store_id,
                    )
                )
            return ack(
                PropagationState.SUPERSEDED,
                f"below cursor {cursor}",
                RejectionCode.VERSION_SUPERSEDED.value,
            )

        targets = self._imports_of(retraction)
        if not targets:
            with self._transaction():
                self.outbox.record_inbox(retraction, "unknown_memory", "no import held", _now_ms())
                self.outbox.advance_cursor(
                    retraction.origin_store_id, retraction.origin_sequence
                )
            return ack(
                PropagationState.REJECTED,
                "no import of that memory version held here",
                RejectionCode.UNKNOWN_MEMORY.value,
            )

        # 6. Persist the event, the inbox record and the lifecycle change in one
        #    transaction. A crash between them is the window invariant 6 covers.
        with self._transaction():
            for local_id in targets:
                if self.get(local_id).lifecycle_state is not LifecycleState.QUARANTINED:
                    self.quarantine(
                        local_id,
                        reason=f"retracted at origin ({retraction.reason_code})",
                        actor=self.store_id,
                        basis=WithdrawalBasis.RETRACTED_AT_ORIGIN,
                    )
                self._emit(
                    ev.retraction_applied(
                        ts=self.now(),
                        retraction_id=retraction.retraction_id,
                        origin_store_id=retraction.origin_store_id,
                        origin_memory_id=retraction.origin_memory_id,
                        origin_memory_version=retraction.origin_memory_version,
                        local_memory_id=local_id,
                        actor=self.store_id,
                    )
                )
            forwarded = self._forward_retraction(retraction, targets)
            self.outbox.record_inbox(
                retraction, "applied", f"{len(targets)} memory/ies", _now_ms()
            )
            self.outbox.advance_cursor(
                retraction.origin_store_id, retraction.origin_sequence
            )

        # 7. Projections already reflect it: `quarantine` emitted through the
        #    same projection fold, and `_eligible_ids` reads lifecycle state, so
        #    the version is no longer exposed. Hence `enforced`, not `persisted`.
        # No counts: how many copies this store held and how many peers it
        # re-shared to are its own sharing graph, and went to every origin
        # (F13). Both stay in this store's log.
        del forwarded
        return ack(PropagationState.ENFORCED, "withdrawn")

    def _latest_applied_sequence(self, origin_store_id: str, origin_memory_id: str,
                                 origin_memory_version: int) -> int | None:
        """The highest origin sequence of a retraction of this memory version applied here."""
        applied = {
            e.payload["retraction_id"]
            for e in self.log.read_types([ev.EventType.RETRACTION_APPLIED])
            if e.payload.get("origin_store_id") == origin_store_id
            and e.payload.get("origin_memory_id") == origin_memory_id
            and int(e.payload.get("origin_memory_version", 0)) == int(origin_memory_version)
        }
        return self.outbox.max_inbox_sequence(origin_store_id, applied) if applied else None

    def _forward_retraction(
        self, retraction: Retraction, targets: Sequence[str]
    ) -> int:
        """Owe the same retraction onward to everyone this store re-shared to.

        **Called inside the caller's transaction**, so the onward intent commits
        with the local withdrawal. A store that applied a retraction and then
        crashed before recording what it owed would leave copies downstream that
        nothing was tracking — the same gap `request_retraction` closed at the
        origin, one hop out.

        Three things keep this terminating, and each is load-bearing:

        * the campaign identity `(origin_store_id, retraction_id)` is preserved,
          so a recipient recognises a copy it has already handled;
        * the *target* is retargeted per hop, so the inbox deduplicates per copy
          rather than per campaign, and a finite federation holds finitely many
          copies;
        * `MAX_HOPS` is a backstop, not the defence. Reaching it is a bug, so it
          records a rejection rather than failing quietly.
        """
        if retraction.hop >= MAX_HOPS:
            self._emit(
                ev.retraction_rejected(
                    ts=self.now(),
                    retraction_id=retraction.retraction_id,
                    origin_store_id=retraction.origin_store_id,
                    rejection_code=RejectionCode.HOP_LIMIT.value,
                    detail=f"hop limit {MAX_HOPS} reached; not forwarding further",
                    actor=self.store_id,
                )
            )
            return 0

        count = 0
        for local_id in targets:
            recipients = [
                store
                for store in self.state.shared_to.get(local_id, {})
                # Never back to the store that just told us. Not a correctness
                # requirement — dedup would absorb it — but one pointless round
                # trip per hop, per peer, is worth not making.
                if store != (retraction.forwarded_by or retraction.origin_store_id)
            ]
            if not recipients:
                continue
            onward = retraction.forward(
                from_store_id=self.store_id,
                local_memory_id=local_id,
                local_version=self.get(local_id).version,
            )
            self._emit(
                ev.retraction_requested(
                    ts=self.now(),
                    retraction_id=onward.retraction_id,
                    origin_store_id=onward.origin_store_id,
                    origin_memory_id=onward.origin_memory_id,
                    origin_memory_version=onward.origin_memory_version,
                    origin_sequence=onward.origin_sequence,
                    reason_code=onward.reason_code,
                    recipients=recipients,
                    requested_by=self.store_id,
                )
            )
            count += self.outbox.enqueue(onward, recipients, _now_ms())
        return count

    def erase_content(
        self, memory_id: str, reason: str, actor: str = "operator"
    ) -> bool:
        """Destroy a memory's content key: crypto-erasure.

        Invariant 12. The event log is append-only and rewriting it to delete a
        memory's text would destroy the property everything else rests on — and
        a log you can edit to remove embarrassing entries is not an audit trail.
        But "it is in an immutable log" is not an answer to a subject asking for
        erasure, or to a leaked credential.

        So the content is encrypted per memory and the *key* is destroyed. Every
        event stays exactly as it was, every projection still replays, lineage
        and the propagation record are untouched, and the text is unrecoverable.

        Irreversible. Returns False when there was nothing to erase, which is
        recorded too: "we were asked and there was no content" is a different
        audit answer from silence.
        """
        self._require(memory_id)
        with self._transaction():
            had_content = self.vault.erase(memory_id, reason, _now_ms())
            self._emit(
                ev.content_erased(
                    ts=self.now(),
                    memory_id=memory_id,
                    reason=reason,
                    actor=actor,
                    had_content=had_content,
                )
            )
        # The index holds the plaintext too, so drop it or a search would still
        # surface the content the caller just erased. The copy index as well:
        # `_unindex` leaves it alone, so that withdrawn documents stay
        # recognisable, but its term set is derived from the erased text.
        self._unindex(memory_id)
        self.copy_index.remove(memory_id)
        return had_content

    def erasure_scope(self, memory_id: str) -> dict[str, Any]:
        """What an erasure reached, and what it provably did not.

        A subject-access request needs a truthful answer, and "the content is
        erased" is only true of the places this store controls. The honest
        answer has three parts, and the third is the one usually left out.

        **Reached**, and verified rather than asserted: the content key is
        destroyed, the event-log payload is ciphertext nobody can open, the
        search indexes no longer hold the terms, and the projection returns the
        marker.

        **Deliberately kept**: provenance, lineage, the retraction basis, the
        propagation record and the whole audit trail. An auditor can still
        answer "was this handled correctly?" about a memory nobody can read —
        that is the point rather than a shortfall.

        **Outside this store's reach**, and reported as unknown rather than
        guessed: backups taken before the key was destroyed still hold the
        ciphertext *and* the key; anything exported, logged, or sent to a model
        provider left before erasure existed; a federated copy at another store
        has its own key and must be erased there. `doctor` cannot see any of
        these, so neither can this.
        """
        memory = self._require(memory_id)
        record = self.vault.status(memory_id)
        sealed = is_sealed(
            next(
                (
                    (event.payload.get("memory") or {}).get("content", "")
                    for event in reversed(list(self.log.read()))
                    if event.type
                    in (
                        ev.EventType.MEMORY_CREATED,
                        ev.EventType.MEMORY_VERSIONED,
                    )
                    and (event.payload.get("memory") or {}).get("id") == memory_id
                ),
                "",
            )
        )
        shared = self.shared_with(memory_id)
        return {
            "memory_id": memory_id,
            "erased": record.erased,
            "reason": record.reason,
            "erased_at": record.erased_ms,
            "reached": {
                "content_key_destroyed": record.erased,
                "log_payload_is_ciphertext": sealed,
                "content_reads_as_marker": memory.content == ERASED_MARKER,
                "removed_from_vector_index": memory_id not in self.index._vectors,
                "removed_from_lexical_index": memory_id not in self.lexical._terms,
            },
            "kept_deliberately": [
                "provenance and the creating agent",
                "derivation lineage in both directions",
                "lifecycle history and the withdrawal basis",
                "the propagation record and every acknowledgement",
                "the erasure event itself, with its reason and time",
            ],
            "outside_this_store": {
                "backups_taken_before_erasure": "unknown — they hold both the "
                "ciphertext and the key; retention is an operational control",
                "exports_logs_and_model_traces": "unknown — anything that left "
                "this store is beyond crypto-erasure",
                "federated_copies": sorted(shared) or "none recorded",
                "federated_copies_note": "each recipient holds its own key and "
                "must erase independently; a retraction withdraws a copy from "
                "use but does not destroy its content",
            },
            "key_custody": type(self.vault.keys).__name__,
            "provider_can_destroy": self.vault.supports_destroy,
        }

    def erasure_status(self, memory_id: str):
        return self.vault.status(memory_id)

    def retractions_since(self, sequence: int) -> list[Retraction]:
        """Every retraction this store has issued above `sequence`.

        What an origin replays when a recipient reconnects and says where it got
        to. Read from the event log rather than from a cache, because the log is
        the source of truth and a cache would be one more thing that can be
        stale after a restore.
        """
        out: list[Retraction] = []
        for event in self.log.read():
            if event.type != ev.EventType.RETRACTION_REQUESTED:
                continue
            payload = event.payload
            if int(payload.get("origin_sequence", 0)) <= sequence:
                continue
            out.append(
                Retraction(
                    retraction_id=payload["retraction_id"],
                    origin_store_id=payload["origin_store_id"],
                    origin_memory_id=payload["origin_memory_id"],
                    origin_memory_version=int(payload["origin_memory_version"]),
                    origin_sequence=int(payload["origin_sequence"]),
                    reason_code=payload["reason_code"],
                    requested_by=payload["requested_by"],
                    issued_at=iso_timestamp(event.ts),
                    evidence_digest=payload.get("evidence_digest"),
                )
            )
        out.sort(key=lambda r: r.origin_sequence)
        return out

    def integrity_snapshot(self) -> dict[str, Any]:
        """The integrity state a backup must not silently omit.

        A restore that dropped pending retractions would reintroduce withdrawn
        knowledge and nothing downstream could detect it, so the snapshot names
        the unresolved ones explicitly and carries a checksum over them.
        """
        import hashlib

        pending = [
            {
                "retraction_id": row.retraction_id,
                "recipient": row.recipient,
                "state": row.state.value,
                "attempts": row.attempts,
            }
            for row in self.outbox.pending()
        ]
        cursors = {
            row["origin_store_id"]: row["sequence_seen"]
            for row in self.log._conn.execute("SELECT * FROM origin_cursor")
        }
        material = json.dumps(
            {"pending": pending, "cursors": cursors}, sort_keys=True
        ).encode("utf-8")
        return {
            "store_id": self.store_id,
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "events": len(self.log),
            "origin_sequence": self.state.origin_sequence,
            "origin_cursors": cursors,
            "unresolved_retractions": pending,
            "checksum": "sha256:" + hashlib.sha256(material).hexdigest(),
        }

    def _imports_of(self, retraction: Retraction) -> list[str]:
        """Local memories imported from the retraction's **target** version.

        Matching on store and id was the old behaviour; adding the version is
        what stops a retraction of v1 withdrawing an import of v3.

        The target is the *hop's* target, which for a direct retraction is the
        origin and for a forwarded one is the store that passed it on. A store
        two hops from the origin never imported from the origin, so matching on
        the origin fields would find nothing and the retraction would stop one
        hop short — silently, with an acknowledgement saying "no import held".
        """
        from .federation import imported_from

        found: list[str] = []
        for memory_id in self.state.memories:
            # Provenance method, not just the origin record. A memory *derived*
            # locally from an import inherits the parent's context, origin key
            # included, so it looks like a second copy of the imported memory.
            # Without this check a recipient's own conclusions were quarantined
            # outright instead of having their support recomputed — which is
            # exactly the "withdrawing unrelated useful knowledge" failure the
            # project exists to prevent. `descendants_of` carries the same
            # guard for the same reason; the deterministic fault matrix caught
            # this one (scenario `derived_conclusion_at_recipient`).
            if self.state.memories[memory_id].provenance.method is not ProvenanceMethod.IMPORTED:
                continue
            origin = imported_from(self, memory_id)
            if origin is None:
                continue
            if origin.get("store") != retraction.applies_to_store:
                continue
            if origin.get("memory_id") != retraction.applies_to_memory:
                continue
            version = origin.get("version")
            if version is not None and int(version) != retraction.applies_to_version:
                continue
            found.append(memory_id)
        return found

    # --- plumbing --------------------------------------------------------

    @property
    def state(self):
        return self.projection.state

    @property
    def lineage_graph(self) -> LineageGraph:
        return LineageGraph(self.state)

    def now(self) -> int:
        return self._clock()

    def _emit(self, *events: ev.Event) -> list[ev.Event]:
        stored = self.log.append_many(events)
        if stored and stored[0].seq != self._seen_seq + 1:
            # Another process appended between our last catch-up and this
            # write, so folding only our own events would put the projection
            # out of log order. Fold everything after what we had seen, in log
            # order -- theirs, then ours -- which is what a rebuild would do.
            self._catch_up()
            return stored
        before = dict(self.state.memories)
        for event in stored:
            self.projection.apply(event)
        self._reindex_changed(before)
        if stored and stored[-1].seq is not None:
            self._seen_seq = stored[-1].seq
        self._estimator_dirty = True
        return stored

    def refresh(self) -> bool:
        """Fold in whatever other processes have appended to the log.

        **Each process folds only its own writes**, so without this a running
        fabric -- an MCP server, an app, the dashboard -- went on serving a
        memory that an operator had quarantined from a terminal, until it was
        restarted. A fresh process said `quarantined`; the live one recalled
        it. That broke "a known-invalid version is never served" for the
        deployment shape the MCP server and dashboard create
        (`tests/test_cross_process_freshness.py`).

        Called at every entry point that serves, enforces or writes. When
        nothing changed it costs one indexed `MAX(seq)` read; when something
        did, it folds the new events in log order (`_catch_up`). Inside an
        open transaction it does nothing: the write lock is ours, so nobody
        else can have appended. Returns whether anything was folded.
        """
        if self.log.in_transaction:
            return False
        if self.log.head_seq == self._seen_seq:
            return False
        self._catch_up()
        return True

    def _catch_up(self) -> int:
        """Fold the events after `_seen_seq`, and re-index only what they changed.

        This used to be a full `_replay` -- every event re-read, every memory
        re-unsealed and re-indexed (re-embedded, with a real embedder) -- each
        time any other process had written. Under contention that is every
        operation, and the log grows with every retrieve because exposures are
        logged, so the cost per operation grew with the log and with the
        number of writers. P12's collapse at 10-100 agents was that: profiled,
        it was 95% of one contending agent's time (experiments/p12_profile.py).

        It is the same projection either way. A rebuild *is* the in-order fold
        of the log (`Projection.rebuild` is `apply_all(log.read())`), so
        folding the suffix onto the state that already holds the prefix gives
        the state a rebuild would, which `tests/test_catch_up.py` checks
        against a fresh replay. Memories are frozen, so the ones the suffix
        changed are exactly those whose object changed; those are re-indexed
        by the rule `_replay` uses -- indexed unless deleted -- and everything
        else keeps entries a replay would have rewritten with the same text.
        A changed memory is re-indexed when its text changed or it is not in
        the index at all; re-indexing one whose text is unchanged would only
        re-embed it.

        Returns the number of events folded.
        """
        head = self.log.head_seq
        before = dict(self.state.memories)
        events = list(self.log.read(since_seq=self._seen_seq))
        self.projection.apply_all(events)
        self._reindex_changed(before)
        # Only forward. `head` was read first, so a suffix that grew while it
        # was being read ends later than `head`, and the watermark follows the
        # last event actually folded.
        last = events[-1].seq if events and events[-1].seq is not None else head
        self._seen_seq = max(self._seen_seq, head, last)
        self._estimator_dirty = True
        return len(events)

    def _reindex_changed(self, before: Mapping[str, Memory]) -> None:
        """Bring the indexes in line with memories a fold just changed.

        One rule for every fold, this process's own writes and others':
        a deleted memory leaves the index; a changed memory that retrieval can
        serve is (re)indexed if its text changed or it is absent. Absent
        covers a memory this process unindexed itself -- `forget` does -- that
        has since come back: validated out of `deprecated`, for instance.
        Before this rule, that memory stayed unretrievable in the process that
        forgot it, and only there, until a restart. Deprecated and erased
        memories need not be present, since retrieval refuses both, but an
        entry that is present always holds the current text.

        Memories are frozen, so "changed" is an identity test, and the cost is
        one pass over the memory table, not a pass over the log.
        """
        for memory_id, memory in self.state.memories.items():
            old = before.get(memory_id)
            if old is memory:
                continue
            state = memory.lifecycle_state
            if state is LifecycleState.DELETED:
                self._unindex(memory_id)
                self.copy_index.remove(memory_id)
                continue
            text = self._index_text(memory)
            present = memory_id in self.index
            changed = old is None or self._index_text(old) != text
            if state is LifecycleState.DEPRECATED or memory_id in self.state.erased:
                # Not served, so an absent entry may stay absent -- but a
                # present one must stay current, or it is stale text waiting
                # for the memory to become servable again. The first version
                # of this rule left it alone, and tests/test_catch_up.py found
                # a revision of a deprecated memory indexed under its old text
                # once a later transition made it contested.
                if old is None or (present and changed):
                    self._index(memory_id, text)
                continue
            if changed or not present:
                self._index(memory_id, text)

    @contextmanager
    def _transaction(self):
        """A log transaction that also keeps the **projection** honest.

        `_emit` appends to the log *and* folds the event into the projection
        immediately, because callers inside a transaction read `self.state`
        straight afterwards — `quarantine` recomputes support from it, for
        instance. So the fold cannot be deferred to the commit.

        The consequence is that a rollback leaves the in-memory projection
        ahead of the log: the disk is correct and the live process keeps
        serving a withdrawal that no longer exists. Found by the regression
        test for the atomicity fix, which asserted on the open fabric and not
        only on a reopened one.

        So an outermost rollback replays from the log. That is a full rebuild,
        which is why it is on the failure path only — AGENTS.md principle 3
        says the log is the source of truth, and this is the one place that was
        quietly not true of a running process.
        """
        outermost = not self.log.in_transaction
        try:
            with self.log.transaction():
                if outermost and self.log.head_seq != self._seen_seq:
                    # The write lock is now ours, so this is the last moment
                    # anyone else can have appended: catch up before writing.
                    self._catch_up()
                yield
        except BaseException:
            if outermost:
                self._replay()
            raise

    def _replay(self) -> None:
        """Rebuild all state from the log, including the vector index."""
        head = self.log.head_seq
        self.projection = Projection.rebuild(
            self.log, unsealer=self._unseal_content
        )
        for memory in self.state.memories.values():
            if memory.lifecycle_state is not LifecycleState.DELETED:
                self._index(memory.id, self._index_text(memory))
        # Read before the rebuild: an event appended during it is picked up by
        # the next `refresh` rather than counted as seen and never folded.
        self._seen_seq = head
        self._estimator_dirty = True

    # --- the three mechanisms the store had and retrieval did not use -----
    #
    # `relevance_v1` found the five families with the largest oracle gap, and
    # three of them — indirect evidence, copied evidence, temporal drift — are
    # answerable with provenance edges, source roots and recorded time. All
    # three already existed; retrieval simply never consulted them.
    #
    # Each is **off by default** and measured as its own benchmark arm. Turning
    # one on by assumption is how a mechanism gets credit it has not earned,
    # which is the H2/H3/H4a pattern this project keeps recording.

    def _applicable_at(self, memory_ids: Iterable[str], when: int | None,
                       until: int | None = None) -> set[str]:
        """Narrow by validity: a point in time, or a history through a time.

        `when` is **state at a point** -- `valid_from <= when < valid_to` --
        and `until` is **everything known through a point**, which ignores
        `valid_to` and keeps a claim that has since been superseded.

        The two are different questions and conflating them is measured to
        cost. On LongMemEval's temporal-reasoning questions -- "which did I do
        first, X or Y?" -- passing the question's own date as `when` discards
        **20% of the turns and 19 points of turn recall**, because the evidence
        for an ordering question is spread across the whole history and some of
        it postdates the moment the question is asked. `applies_at` is right
        and the call was wrong: a question about when things happened is not a
        question about what was true at a moment.

        Neither mode set does nothing, which is right for a task that does not
        say what time it is about. A memory with no window applies always, so a
        store written before 0.7.0 is unaffected.
        """
        if when is None and until is None:
            return set(memory_ids)
        out = set()
        for memory_id in memory_ids:
            memory = self.state.memories[memory_id]
            if when is not None and not memory.applies_at(when):
                continue
            if until is not None:
                begins = memory.valid_from
                if begins is not None and begins > until:
                    continue
            out.add(memory_id)
        return out

    def source_root(self, memory_id: str) -> str:
        """The earliest observation this memory traces back to.

        Its own id when it has no parents. Used to tell corroboration from
        repetition: four memories quoting one report are one piece of evidence,
        and a context assembled from all four *looks* four times as supported.
        `relevance_v1`'s `copied_evidence` family is that case.

        The lexicographically smallest root when there are several, so the
        grouping key is deterministic — an id that varied by walk order would
        make deduplication depend on insertion order.

        **A recognised re-ingestion resolves to its original's root.** That is
        the whole of the fix for the one case [P3](../research/results/p3-correction-propagation.md)
        could not solve: a withdrawn document re-ingested under its own id was
        two roots and two votes, because provenance correctly recorded two
        ingestions and was correctly wrong about the evidence. Resolved here
        rather than at write time, so the copy keeps its own identity, its own
        provenance and its own place in the log, and only loses the claim to be
        independent support.
        """
        # Alternating resolution: follow a copy edge, then a lineage walk,
        # until neither moves. The first version resolved copies only for the
        # memory it was handed, so a conclusion *derived from a copy* still
        # reported the copy as its root -- the lineage walk found the copy, and
        # nothing resolved it onward to the original. Grouping then treated the
        # conclusion as independent of everything under the original's root,
        # which is the exact failure the copy relation exists to prevent, one
        # level down.
        seen: set[str] = set()
        current = memory_id
        while current not in seen:
            seen.add(current)
            original = self.state.copy_of.get(current)
            if original is not None and original not in seen:
                current = original
                continue
            roots = self.lineage_graph.roots(current)
            if not roots:
                return current
            candidate = min(roots)
            if candidate == current or candidate in seen:
                return candidate
            current = candidate
        return current

    def _group_by_root(
        self, ranked: Sequence[tuple[str, float]], limit: int
    ) -> list[tuple[str, float]]:
        """Keep the best-ranked memory per source root — **except** a premise
        of something already kept.

        The purpose is to stop copies counting as corroboration: four memories
        quoting one report are one piece of evidence, and a context assembled
        from all four *looks* four times as supported.
        `relevance_v1`'s `copied_evidence` family is that case.

        A premise and the conclusion drawn from it share a root and are **not**
        copies. Grouping them cost the whole lineage gain when both mechanisms
        were enabled: the `indirect` family scored 1.000 with lineage promotion
        alone and 0.613 with grouping as well, because grouping discarded
        exactly the premise promotion had just surfaced. The two mechanisms
        were undoing each other.

        So the rule is narrower than "one per root": a candidate is dropped
        only when something already kept shares its root *and* is not related
        to it by derivation. Copies collapse; evidence chains survive.

        Not content deduplication, deliberately. Two memories can be
        near-identical and independently observed, which is real
        corroboration, while two differently-worded memories can share one root
        and be none.
        """
        kept: list[tuple[str, float]] = []
        kept_by_root: dict[str, list[str]] = {}
        for memory_id, score in ranked:
            root = self.source_root(memory_id)
            siblings = kept_by_root.get(root, [])
            if siblings and not any(
                self._derivation_related(memory_id, other) for other in siblings
            ):
                continue
            kept.append((memory_id, score))
            kept_by_root.setdefault(root, []).append(memory_id)
            if len(kept) >= limit:
                break
        return kept

    def _derivation_related(self, left: str, right: str) -> bool:
        """Whether one of these is an ancestor of the other.

        Checked through the parent edges rather than by content, because that
        is the difference between "a conclusion and its premise" and "two
        copies of one report" — and only the first pair belongs in a context
        together.
        """
        graph = self.lineage_graph
        if any(node.memory_id == right for node in graph.ancestors(left)):
            return True
        return any(node.memory_id == left for node in graph.ancestors(right))

    def _expand_lineage(
        self,
        ranked: Sequence[tuple[str, float]],
        eligible: set[str],
        limit: int,
        depth: int = 1,
    ) -> list[tuple[str, float]]:
        """**Promote** the premises of what was retrieved, not merely include them.

        A conclusion is not assessable without the premise it rests on, and no
        lexical or vector signal connects them: the premise may share no words
        with the task at all. `relevance_v1`'s `indirect` family is exactly
        that, and it is one of the largest oracle gaps.

        The first version of this only *appended* absent parents, and measured
        **exactly zero** effect — because the candidate pool is four times `k`
        and already contained the premise, ranked below the distractors. Adding
        something already present changes nothing. What the case needs is for a
        premise to be pulled *up* to sit beside the conclusion that depends on
        it, so this raises a parent's score to just under its child's whenever
        that is an increase.

        Bounded, and the bounds are the design: `depth` hops, `limit` results,
        parents only, and a parent is promoted once. An unbounded walk over a
        dense graph returns the store.

        The 0.99 factor keeps the child ahead of its own premise, so the
        ordering still reads as "the answer, then what it rests on".
        """
        if depth < 1:
            return list(ranked)
        scores = dict(ranked)
        order = [memory_id for memory_id, _ in ranked]
        frontier = list(order)
        promoted: set[str] = set()
        for _ in range(depth):
            next_frontier: list[str] = []
            for memory_id in frontier:
                child_score = scores.get(memory_id, 0.0)
                # `state.parents` holds ids, not (id, version) pairs — the
                # versions live on `state.parent_versions`. Sorted so the walk
                # is deterministic.
                for parent_id in sorted(self.state.parents.get(memory_id, ())):
                    if parent_id in promoted or parent_id not in eligible:
                        continue
                    if parent_id not in self.state.memories:
                        continue
                    promoted.add(parent_id)
                    inherited = child_score * 0.99
                    if scores.get(parent_id, -1.0) < inherited:
                        scores[parent_id] = inherited
                        if parent_id not in order:
                            order.append(parent_id)
                    next_frontier.append(parent_id)
            frontier = next_frontier
            if not frontier:
                break
        ordered = sorted(order, key=lambda mid: (-scores[mid], mid))
        return [(memory_id, scores[memory_id]) for memory_id in ordered][:limit]

    def _search(
        self,
        query: str,
        k: int,
        eligible: set[str],
        min_relevance: float,
    ) -> list[tuple[str, float]]:
        """Candidate discovery, by configured mode.

        **`lexical` is the default, and it was `hybrid` until an external
        benchmark said otherwise.**

        `hybrid` is reciprocal-rank fusion of the vector and lexical arms, and
        it was chosen on `relevance_v1` because it beat vector-only and omitted
        fewer critical memories. On SciFact — 5,183 real abstracts, 339
        third-party judgements — it scores **0.558 nDCG@10 against lexical's
        0.621**, because the default embedder is a hashed bag of words scoring
        0.315 and RRF gives a near-noise arm real rank votes. Noise with a vote
        is worse than no vote.

        Not an isolated reading: on `relevance_v1`'s own expanded test split
        `lexical` scores 0.733 against hybrid's 0.693. **Lexical wins the
        held-out split of both benchmarks.**

        The rule is not "fusion is bad". On the same 300 SciFact queries with a
        *trained* embedder, the vector arm scores 0.701 and fusing it with
        lexical scores **0.726** — above published BM25 (~0.665). Fusion costs
        6.3 points with a hashed arm and gains 2.5 with a trained one, same
        mechanism, opposite sign. So `retrieval="hybrid"` is the measured
        recommendation once `embedder=` is a real model, and the rule is: do
        not fuse a weak arm into a strong one.

        `vector` reproduces the pre-2026-10-11 behaviour exactly, for anyone
        who needs the old ranking while validating.

        Numbers: `research/results/scifact-external.md` and
        `research/results/relevance-v1-real-embedder.md`.
        """
        mode = self.retrieval_mode
        if mode == "vector":
            return self.index.search(
                query, k=k, restrict_to=eligible, min_relevance=min_relevance
            )
        if mode == "lexical":
            return self.lexical.search(
                query, k=k, restrict_to=eligible, min_relevance=min_relevance
            )
        if mode != "hybrid":
            raise ValueError(
                f"unknown retrieval mode {mode!r}; expected hybrid, lexical or vector"
            )
        # Each arm is asked for the whole pool before fusion: truncating an arm
        # to k first would let a memory ranked k+1 by one arm and 1 by the
        # other drop out, which is exactly the case fusion exists to catch.
        dense = self.index.search(
            query, k=k, restrict_to=eligible, min_relevance=min_relevance
        )
        sparse = self.lexical.search(
            query, k=k, restrict_to=eligible, min_relevance=min_relevance
        )
        return fuse(dense, sparse, k=k)

    def _index(self, memory_id: str, text: str) -> None:
        """Both retrieval arms, always, plus the copy index.

        A memory indexed in one arm and not the other would make
        `retrieval_mode` change *what exists* rather than how it is ranked.

        The copy index is maintained here rather than in `remember` for the
        same reason: it is built on replay too, and a store whose copy index
        was populated only by live writes would stop recognising
        re-ingestions after a restart.
        """
        self.index.add(memory_id, text)
        self.lexical.add(memory_id, text)
        if self.recognise_copies:
            self.copy_index.add(memory_id, text)
        # Chain terms, cached for the same reason the IDF is: `reconstruct`
        # tokenised every candidate on every call, so a question over 413
        # turns cost 38.8 ms **before the search expanded a single node**.
        # Tokenisation does not depend on the query, so none of it needed
        # repeating.
        self.chain_terms[memory_id] = frozenset(chains.tokens(text))
        self.chain_plain[memory_id] = frozenset(
            t for t in self.chain_terms[memory_id] if not chains.is_numeric(t))

    def _unindex(self, memory_id: str) -> None:
        self.index.remove(memory_id)
        self.lexical.remove(memory_id)
        self.chain_terms.pop(memory_id, None)
        self.chain_plain.pop(memory_id, None)

    @staticmethod
    def _index_text(memory: Memory) -> str:
        """Context is indexed alongside content so retrieval is at least
        context-aware, even with the placeholder embedder."""
        parts = [memory.content]
        for key, value in sorted(memory.context.items()):
            if key == "tags" and isinstance(value, (list, tuple, set)):
                parts.extend(str(v) for v in value)
            else:
                parts.append(f"{key} {value}")
        return " ".join(parts)

    def _require(self, memory_id: str) -> Memory:
        memory = self.state.memories.get(memory_id)
        if memory is None:
            raise NotFound(f"no memory {memory_id!r}")
        return memory

    def _refresh_estimator(self) -> None:
        if self._estimator_dirty:
            self.estimator.fit(self.state)
            self._estimator_dirty = False

    # --- episodes --------------------------------------------------------

    @_fresh
    def start_episode(
        self,
        agent_id: str,
        task_id: str,
        context: Mapping[str, Any] | None = None,
        seed: int | None = None,
    ) -> Episode:
        episode_id = new_ulid()
        self._emit(
            ev.episode_started(
                ts=self.now(),
                agent_id=agent_id,
                episode_id=episode_id,
                task_id=task_id,
                context=dict(context or {}),
                seed=seed,
            )
        )
        return self.state.episodes[episode_id]

    def session(
        self,
        agent_id: str,
        task_id: str,
        context: Mapping[str, Any] | None = None,
        seed: int | None = None,
    ) -> "AgentSession":
        """Start an episode and return a handle scoped to it.

        This is what adapters are given, rather than the fabric itself, so they
        cannot write as another agent or against another episode (session.py).
        """
        from .session import AgentSession

        episode = self.start_episode(agent_id, task_id, context, seed)
        return AgentSession(fabric=self, agent_id=agent_id, episode=episode)

    @_fresh
    def record_outcome(self, episode_id: str, outcome: float, verifier_id: str) -> None:
        """Record a verified outcome.

        `verifier_id` is mandatory and must not be the acting agent. An agent
        that can score its own episodes can manufacture value for any memory it
        likes (SECURITY.md T2), which would corrupt every estimate downstream.
        """
        episode = self.state.episodes.get(episode_id)
        if episode is None:
            raise NotFound(f"no episode {episode_id!r}")
        if not verifier_id:
            raise PolicyViolation("record_outcome requires a verifier_id")
        if verifier_id == episode.agent_id:
            raise PolicyViolation(
                f"agent {verifier_id!r} may not verify its own episode outcome"
            )
        self._emit(
            ev.outcome_recorded(
                ts=self.now(),
                episode_id=episode_id,
                outcome=float(outcome),
                verifier_id=verifier_id,
            )
        )

    def end_episode(self, episode_id: str) -> Episode:
        episode = self.state.episodes.get(episode_id)
        if episode is None:
            raise NotFound(f"no episode {episode_id!r}")
        return episode

    # --- writing ---------------------------------------------------------

    @_fresh
    def remember(
        self,
        agent_id: str,
        content: str,
        type: str | MemoryType = MemoryType.SEMANTIC,
        context: Mapping[str, Any] | None = None,
        source_episodes: Sequence[str] = (),
        parents: Sequence[tuple[str, int]] = (),
        method: str | ProvenanceMethod = ProvenanceMethod.OBSERVED,
        structured: Mapping[str, Any] | None = None,
        security_class: str | SecurityClass = SecurityClass.INTERNAL,
        capabilities: Sequence[str] = (),
        scope: str | Scope = Scope.PRIVATE,
        episode_id: str | None = None,
        auto_activate: bool | None = None,
        tenant_id: str = DEFAULT_TENANT,
        valid_from: int | None = None,
        valid_to: int | None = None,
    ) -> str:
        """Store a new memory. Runs the ingest screen before anything is stored.

        A high-severity sensitive-data hit lands the memory in `quarantined`
        rather than dropping it: the fact that an agent tried to memorise a
        secret is itself worth auditing.

        `auto_activate` overrides the store's default for this one write. A
        caller that knows the content is not a trusted local observation — an
        import from another store, for instance — passes False so the store's
        convenience setting cannot silently promote it.
        """
        # An agent that writes the same thing twice in one episode is looping,
        # not observing twice. Found live: a model called the `remember` tool
        # four times in a single run and produced two distinct memories, which
        # inflates apparent consensus exactly the way several agents parroting
        # one source does (SECURITY.md T3) — except from a single agent, which
        # the evidence-independence check does not look at.
        #
        # Scoped to one episode on purpose. The same claim recorded in two
        # different episodes is two observations, and that *is* more evidence.
        if episode_id:
            key = (agent_id, episode_id, _digest(content))
            existing = self.state.written.get(key)
            if existing is not None:
                self._emit(
                    ev.duplicate_suppressed(
                        ts=self.now(),
                        agent_id=agent_id,
                        episode_id=episode_id,
                        existing_memory_id=existing,
                        content_digest=key[2],
                    )
                )
                return existing

        # A re-ingestion of something already held, across agents and
        # episodes. The exact-digest check above is scoped to one episode and
        # one agent on purpose -- the same claim observed twice really is more
        # evidence -- and it cannot see the case P3 measured: a document
        # withdrawn as wrong, then re-ingested months later from a shared drive
        # with a filing note appended, so its digest differs.
        #
        # Looked up *before* the write, and recorded after it, so the event
        # names a memory that exists.
        copy_of = None
        if self.recognise_copies:
            copy_of = self.copy_index.find(content)

        # Writing at a wider scope skips the firewall that `share` runs, which
        # is fine for host code except where a rule is absolute: a restricted
        # memory stays private (firewall.rule_restricted_stays_private), and
        # writing it straight into `team` would be the same leak by the side door.
        if (SecurityClass(security_class) is SecurityClass.RESTRICTED
                and Scope(scope) is not Scope.PRIVATE):
            raise PolicyViolation("a restricted memory stays private; it cannot be "
                                  f"written at scope {Scope(scope).value}")
        activate = self.auto_activate if auto_activate is None else auto_activate
        ruling = self.firewall.screen_ingest(
            _screened_text(content, context, structured))
        if ruling.decision is FirewallDecision.QUARANTINE:
            lifecycle = LifecycleState.QUARANTINED
        elif copy_of is not None and self.state.memories[
                copy_of.memory_id].lifecycle_state in WITHDRAWN_STATES:
            # Re-ingesting a withdrawn document does not restore it.
            #
            # CONTESTED rather than QUARANTINED: nobody has made a finding
            # about *this* write, and the original's withdrawal may itself have
            # been wrong. Contested is withheld from retrieval by default and
            # stays visible to an operator, which is the honest state for "this
            # arrived again and the reason it was withdrawn has not changed".
            lifecycle = LifecycleState.CONTESTED
        elif activate:
            lifecycle = LifecycleState.ACTIVE
        else:
            lifecycle = LifecycleState.CANDIDATE

        now = self.now()
        memory = Memory(
            id=new_ulid(),
            version=1,
            type=MemoryType(type),
            content=content,
            provenance=Provenance(
                created_by=agent_id,
                source_episodes=tuple(source_episodes),
                parents=tuple((p[0], int(p[1])) for p in parents),
                method=ProvenanceMethod(method),
            ),
            context=dict(context or {}),
            structured=dict(structured) if structured else None,
            scope=Scope(scope),
            tenant_id=tenant_id,
            # Validity in the world, separate from `created_at` which is when
            # this store learned it. Both None means "applies always", which is
            # how every memory written before 0.7.0 behaves.
            valid_from=valid_from,
            valid_to=valid_to,
            lifecycle_state=lifecycle,
            security_class=SecurityClass(security_class),
            capabilities=tuple(capabilities),
            created_at=now,
        )
        # Seal on the way into the log. The projection unseals as it folds, so
        # every reader downstream still sees plaintext; what changes is that the
        # bytes on disk are ciphertext and destroying the key is therefore real
        # erasure rather than a cosmetic one.
        sealed = memory.evolve(
            content=self._seal_content(memory.content, memory.id, memory.version)
        )
        emitted = [ev.memory_created(ts=now, memory=sealed, episode_id=episode_id)]
        if copy_of is not None:
            # After the creation event, so the copy edge never names a memory
            # the log has not yet introduced -- a replay applies these in order
            # and a forward reference would leave `copy_of` pointing at nothing.
            emitted.append(ev.copy_recognised(
                ts=now, agent_id=agent_id, episode_id=episode_id,
                memory_id=memory.id, original_memory_id=copy_of.memory_id,
                containment=copy_of.score,
            ))
            if lifecycle is LifecycleState.CONTESTED:
                emitted.append(ev.lifecycle_changed(
                    ts=now, memory_id=memory.id,
                    from_state=LifecycleState.CANDIDATE.value,
                    to_state=LifecycleState.CONTESTED.value,
                    reason=(f"re-ingestion of withdrawn {copy_of.memory_id}"),
                    actor="copy-recognition",
                    # A finding about the content, inherited: the original was
                    # withdrawn for a reason that has not changed. Not
                    # CO_OCCURRENCE, which Phase A measured as a harmful
                    # withdrawal rule, and not UNSTATED, which would hide that
                    # a reason exists.
                    basis=self.state.withdrawal_basis.get(
                        copy_of.memory_id, WithdrawalBasis.UNSTATED.value),
                ))
        if ruling.decision is FirewallDecision.QUARANTINE:
            emitted.append(
                ev.lifecycle_changed(
                    ts=now,
                    memory_id=memory.id,
                    from_state=LifecycleState.CANDIDATE.value,
                    to_state=LifecycleState.QUARANTINED.value,
                    reason="; ".join(ruling.reasons),
                    actor=self.firewall.id,
                    # The firewall quarantines on a finding about the memory
                    # itself, which is the strong case and the one worth
                    # distinguishing from "it was present when something failed".
                    basis=WithdrawalBasis.SENSITIVE_DATA.value,
                )
            )
        self._emit(*emitted)
        # From the state, not the local object: see `revise` for why.
        self._index(memory.id, self._index_text(self.state.memories[memory.id]))
        return memory.id

    @_fresh
    def revise(
        self,
        memory_id: str,
        content: str,
        agent_id: str,
        reason: str,
        method: str | ProvenanceMethod = ProvenanceMethod.CONSOLIDATED,
    ) -> Memory:
        """Create the next version of a memory. The old version stays in history.

        Refused once the content has been erased. Erasure is terminal for a
        memory's content: writing a new version under the same id would make it
        readable again and would defeat the erasure record. A property-based
        walk found the sequence (erase, then revise) and it stored the new text
        in plaintext, because the destroyed key made the sealer fall back.
        """
        current = self._require(memory_id)
        if memory_id in self.state.erased:
            raise PolicyViolation(
                f"{memory_id} has been content-erased; record new information "
                "as a new memory rather than a new version"
            )
        # A revision is a write and passes the same screen as the first
        # version. It used to skip it, so a revision could put a secret or an
        # injection into a memory that was already active and retrievable.
        ruling = self.firewall.screen_ingest(
            _screened_text(content, current.context, current.structured))
        now = self.now()
        revised = current.evolve(
            version=current.version + 1,
            content=content,
            provenance=Provenance(
                created_by=agent_id,
                source_episodes=current.provenance.source_episodes,
                parents=current.provenance.parents,
                method=ProvenanceMethod(method),
            ),
            created_at=now,
            superseded_at=None,
        )
        self._emit(
            ev.memory_versioned(
                ts=now,
                memory=revised.evolve(
                    content=self._seal_content(
                        revised.content, revised.id, revised.version
                    )
                ),
                reason=reason,
            ),
            *(
                [self._transition(
                    memory_id, LifecycleState.QUARANTINED, "; ".join(ruling.reasons),
                    self.firewall.id, basis=WithdrawalBasis.SENSITIVE_DATA.value,
                )]
                if ruling.decision is FirewallDecision.QUARANTINE
                and current.lifecycle_state is not LifecycleState.QUARANTINED
                else []
            ),
        )
        # The state's version, not `revised`: if another process revised the
        # same memory just after us, `_emit` has folded that later version in,
        # and indexing our own would put superseded text back in the index
        # under the current version. Found by tests/test_catch_up.py.
        current = self.state.memories[memory_id]
        self._index(memory_id, self._index_text(current))
        return current

    @_fresh
    def derive(
        self,
        agent_id: str,
        content: str,
        parents: Sequence[str],
        type: str | MemoryType = MemoryType.SEMANTIC,
        method: str | ProvenanceMethod = ProvenanceMethod.CONSOLIDATED,
        context: Mapping[str, Any] | None = None,
        tenant_id: str | None = None,
        security_class: str | SecurityClass | None = None,
        scope: str | Scope = Scope.PRIVATE,
        auto_activate: bool | None = None,
    ) -> str:
        """Create a memory derived from existing ones, recording the edges.

        `auto_activate` overrides the store's default for this write, as in
        `remember`. A rulebook proposal must stay a candidate on a store
        that activates everything else (`rulebook.py`).

        These edges are what makes retraction work, so deriving through this
        method rather than writing a fresh memory is the difference between a
        rollback that holds and one that leaks (SECURITY.md T5).

        `tenant_id` None inherits the parents' tenant, and the parents must
        agree. Defaulting to the *store's* default instead was the first
        version, and it was an isolation hole: a tenant's conclusion landed in
        `tn_default` where any agent scoped to that tenant could read it, even
        though both the acting agent and every premise were elsewhere. Found by
        the test for the ordinary within-tenant case, not by the test for the
        attack.
        """
        parent_versions = [(pid, self._require(pid).version) for pid in parents]
        if tenant_id is None:
            tenants = {self._require(pid).tenant_id for pid in parents}
            if len(tenants) > 1:
                raise PolicyViolation(
                    "cannot derive from premises in different tenants: "
                    f"{sorted(tenants)}. Name the tenant explicitly if this is "
                    "deliberate."
                )
            tenant_id = tenants.pop() if tenants else DEFAULT_TENANT
        inherited: dict[str, Any] = {}
        for pid in parents:
            inherited.update(self._require(pid).context)
        inherited.update(dict(context or {}))
        # A conclusion is at least as restricted as its most restricted
        # premise. It used to be written at the default class, so a summary of
        # a `restricted` memory came out `internal` and could be shared and
        # offered: restricted content laundered through a derivation (plan
        # Task 11). A caller may raise the class, never lower it below this.
        order = (SecurityClass.PUBLIC, SecurityClass.INTERNAL, SecurityClass.RESTRICTED)
        floor = max((self._require(pid).security_class for pid in parents),
                    key=order.index, default=SecurityClass.PUBLIC)
        requested = SecurityClass(security_class or SecurityClass.INTERNAL)
        effective = max(requested, floor, key=order.index)
        # Visibility follows the same rule the other way: no wider than the
        # narrowest premise, so a conclusion cannot show teammates what a
        # private premise would not.
        narrowest = min((self._require(pid).scope for pid in parents),
                        key=lambda s: s.rank, default=Scope.FEDERATED)
        visible = min(Scope(scope), narrowest, key=lambda s: s.rank)
        derived = self.remember(
            agent_id=agent_id,
            content=content,
            type=type,
            context=inherited,
            parents=parent_versions,
            method=method,
            tenant_id=tenant_id,
            security_class=effective,
            scope=visible,
            auto_activate=auto_activate,
        )

        # Check the support of what was just written.
        #
        # Retraction propagated to conclusions drawn *before* a withdrawal and
        # not to ones drawn after: deriving from an already-quarantined premise
        # produced an ACTIVE memory. The same two memories and the same
        # finding, with opposite results depending on which arrived first --
        # the same order-dependence the copy relation had, one layer up.
        #
        # This is the recomputation `quarantine` already runs, applied at write
        # time, so there is no second rule about what counts as support. A
        # derivation from independently-supported premises is unaffected: the
        # verdict is about whether support survives, not about whether a
        # premise is unusual.
        if self.state.memories[derived].lifecycle_state is not LifecycleState.QUARANTINED:
            verdict = self.justifications.recompute(derived)
            if not verdict.still_justified:
                self._emit(
                    ev.support_recomputed(
                        ts=self.now(),
                        memory_id=verdict.memory_id,
                        trigger_memory_id=derived,
                        verdict=verdict.verdict,
                        surviving=list(verdict.surviving),
                        lost=list(verdict.lost),
                        independent_count=verdict.independent_count,
                        reason=verdict.reason,
                        actor=agent_id,
                    ),
                    self._transition(
                        derived,
                        LifecycleState.CONTESTED,
                        f"derived from premises that do not support it: "
                        f"{verdict.reason}",
                        agent_id,
                    ),
                )
        return derived

    # --- retrieval -------------------------------------------------------

    @_fresh
    def retrieve(
        self,
        agent_id: str,
        query: str,
        context: Mapping[str, Any] | None = None,
        k: int = 5,
        episode_id: str | None = None,
        pool: int | None = None,
        include_contested: bool = False,
        step: int = 0,
        min_relevance: float = MIN_RELEVANCE,
        tenant_id: str | None = None,
        as_of: int | None = None,
        until: int | None = None,
        group_by_source_root: bool = True,
        expand_lineage: int = 1,
        follow_relations: bool = False,
        entities: Sequence[str] = (),
        use_extraction: bool = False,
        objective: Any = None,
    ) -> RetrievalResult:
        """Retrieve, decide exposure, log both, return what was exposed.

        `objective` (an `objective.MemoryObjective`) narrows the eligible set to
        what the session said is relevant, before ranking (M1).

        Candidates below `min_relevance` are not considered at all, so a query
        with nothing to match returns nothing rather than the least-bad rows in
        the store.

        `tenant_id` None searches every tenant, which is the operator view and
        the behaviour every single-tenant store has always had. A caller acting
        for one tenant should not be passing it by hand at all — use
        `for_tenant` or `as_principal`, which cannot be forgotten.

        **`group_by_source_root` and `expand_lineage` default on, because they
        were measured.** On `relevance_v1` the two together take this arm from
        0.752 to 0.795 nDCG@3 on dev and 0.658 to 0.732 on the frozen test
        split, with critical-memory omission falling from 0.214 to 0.143. Both
        can be switched off; the numbers are in
        `research/results/relevance-v1-ceiling.md` so the choice is informed.

        **`as_of` does not default**, and cannot. Defaulting it to `now` would
        make every historical question unanswerable — `temporal_drift-02` is
        the case: the same corpus, the opposite answer, because the task is
        about last year.

        **And a caller that knows its task's time should still think about
        which temporal question it is asking**, because passing the task's own
        event time is not always right. `as_of` means *state at a point*:
        `valid_from <= as_of < valid_to`. On LongMemEval's temporal-reasoning
        questions — "which did I do first, X or Y?" — doing that discards
        **20% of the turns and 19 points of turn recall**, because the evidence
        for an ordering question is spread across the whole history and some of
        it postdates the moment the question is asked
        (`research/results/longmemeval.md`). An earlier version of this
        docstring recommended passing the event time without qualification,
        and every internal benchmark agreed with it because none of them put
        evidence after the task's event time. It took an external benchmark to
        show the gap.

        So there are three temporal questions and the caller picks:

        * **what is true now, or was true at T** — `as_of=T`. Supersession applies.
        * **what did we know through T**, including claims since superseded — `until=T`. Half-open upper bounds are ignored.
        * **when did things happen** — neither. An ordering question needs the whole history, and filtering it is how 19 points go missing.
        """
        eligible = self._eligible_ids(
            include_contested=include_contested, tenant_id=tenant_id,
            agent_id=agent_id,
        )
        pool_size = pool if pool is not None else max(k * 4, k)
        # Temporal applicability narrows the *eligible set*, before the index
        # is queried, for the reason the tenant filter does: a memory excluded
        # before ranking cannot be ranked, scored, logged or leaked by a bug
        # in a policy.
        eligible = self._applicable_at(eligible, as_of, until)
        if objective is not None:
            # The session's own statement of relevance, at the same chokepoint
            # as tenancy and lifecycle, for the same reason: an excluded memory
            # is never ranked, exposed, or logged as a withheld candidate.
            eligible = {m for m in eligible
                        if objective.admits(self.state.memories[m].context)}
        hits = self._search(query, pool_size, eligible, min_relevance)
        if self.rerank:
            # After fusion and before grouping. Reranking a *fused* pool is
            # the claim under test -- that a reranker makes fusion safe -- so
            # it has to see what fusion produced, and grouping afterwards still
            # collapses copies in the new order.
            hits = reranking.rerank(
                query, hits,
                {mid: self.state.memories[mid].content for mid, _ in hits},
                self.lexical._idf(),
                mode=self.rerank if isinstance(self.rerank, str) else "tiebreak",
            )
        if expand_lineage:
            hits = self._expand_lineage(
                hits, eligible, limit=pool_size, depth=expand_lineage
            )
        if use_extraction:
            # Before relation-following, so a default admitted here can then
            # drag in whatever qualifies it.
            hits = self._admit_defaults(
                hits, eligible, entities, pool_size, k)
        if follow_relations:
            # After lineage expansion and before grouping: a qualifier should
            # travel with whatever it qualifies even if that arrived by
            # premise promotion, and grouping afterwards still collapses
            # copies in the new order.
            hits = self._follow_relations(hits, eligible, limit=pool_size)
        if group_by_source_root:
            hits = self._group_by_root(hits, limit=pool_size)

        # Only estimate values when the policy will actually rank on them.
        # Refitting the estimator on every retrieval and then ranking by
        # relevance is pure waste, and it grows with the log.
        wants_value = bool(getattr(self.policy, "needs_value", True))
        if wants_value:
            self._refresh_estimator()
        candidates: list[Candidate] = []
        for memory_id, score in hits:
            memory = self.state.memories[memory_id]
            candidates.append(
                Candidate(
                    memory_id=memory_id,
                    version=memory.version,
                    relevance=score,
                    value=self.estimator.estimate(memory_id, context) if wants_value else None,
                )
            )

        now = self.now()
        emitted: list[ev.Event] = [
            ev.retrieval_performed(
                ts=now,
                agent_id=agent_id,
                episode_id=episode_id,
                query=query,
                candidates=[(c.memory_id, c.version, c.relevance) for c in candidates],
                context=context,
            )
        ]

        decisions = self.policy.decide(candidates, k, self.rng)
        result = RetrievalResult(policy_id=self.policy.id)
        for decision in decisions:
            candidate = decision.candidate
            emitted.append(
                ev.exposure_decided(
                    ts=now,
                    agent_id=agent_id,
                    episode_id=episode_id,
                    memory_id=candidate.memory_id,
                    version=candidate.version,
                    exposed=decision.exposed,
                    propensity=decision.propensity,
                    policy_id=self.policy.id,
                    step=step,
                )
            )
            memory = self.state.memories[candidate.memory_id]
            result.scores[candidate.memory_id] = candidate.relevance
            (result.exposed if decision.exposed else result.withheld).append(memory)

        self._emit(*emitted)
        return result

    def reconstruct(
        self,
        agent_id: str,
        query: str,
        k: int = chains.MAX_STEPS,
        episode_id: str | None = None,
        tenant_id: str | None = None,
        as_of: int | None = None,
        until: int | None = None,
        include_contested: bool = False,
        follow_relations: bool = False,
        max_steps: int = chains.MAX_STEPS,
        beam: int = chains.BEAM,
        node_budget: int = chains.NODE_BUDGET,
        deadline_ms: float | None = None,
    ) -> "chains.EvidenceChain":
        """Reconstruct a connected chain of **currently valid** evidence.

        For the question `retrieve` cannot answer: one where no single memory
        matches, because the answer is distributed across several and the
        memory in the middle shares no word with the query.

        Measured need, not a speculative feature. `multi_hop_4` sufficiency is
        **0.000** for every arm that ranks candidates independently, against an
        oracle's 1.000, and a coverage-greedy selector scored 0.000 too because
        a connector's marginal query-term coverage is zero
        (`research/results/p2-context-sufficiency.md`). Premise promotion lifts
        the same family from 0.330 to 0.519 nDCG and cannot start from a query
        that matches nothing, because it promotes a parent only once the child
        has already ranked.

        **The candidate set is the eligible set, not the search results.** A
        connector scores zero on the index, so a candidate list taken from
        `_search` would not contain the one memory this method exists to find —
        the defect that made an earlier experiment's own oracle score 0.000 on
        both chain families. Ranking supplies the order; eligibility supplies
        the pool.

        **Validity is by construction.** The pool is what `_eligible_ids` and
        `_applicable_at` produce, so a retracted memory, a contested descendant
        of one, a wrong-tenant memory, an unauthorised one and a memory outside
        its validity interval are never nodes in the graph. Same argument
        `_eligible_ids` makes for itself: a memory excluded before the search
        cannot be reached by a bug in the search.

        An **incomplete** chain is a real answer rather than a failure. It names
        the query terms nothing could supply, which is the shape of "the corpus
        does not join up"; `complete` stays False so a caller cannot mistake one
        for the other, and deciding whether that means abstain is the caller's.

        Every step carries why it is there and a leave-one-out necessity
        verdict — see `chains.EvidenceChain.why`.
        """
        eligible = self._eligible_ids(
            include_contested=include_contested, tenant_id=tenant_id,
            agent_id=agent_id,
        )
        eligible = self._applicable_at(eligible, as_of, until)
        if not eligible:
            return chains.EvidenceChain()

        # Ranked first, then everything else eligible in a stable order. The
        # tail is where connectors live.
        scored = self._search(query, len(eligible), eligible, 0.0)
        relevance = {memory_id: score for memory_id, score in scored}
        ordered = [memory_id for memory_id, _ in scored]
        seen = set(ordered)
        ordered += sorted(memory_id for memory_id in eligible if memory_id not in seen)

        # `chains.tokens`, not the lexical index's: identifiers must stay
        # whole or the graph's edges stop meaning "about the same thing".
        # Read from the cache `_index` maintains, falling back for a memory
        # written before the cache existed in this process.
        terms = {
            memory_id: self.chain_terms.get(memory_id)
            or frozenset(chains.tokens(self.state.memories[memory_id].content))
            for memory_id in ordered
        }
        # Query terms some candidate actually contains. A term nothing supplies
        # cannot be covered, and demanding it would make every chain
        # incomplete -- the defect that once abstained on 79% of answerable
        # cases.
        present: set[str] = set()
        for tokens in terms.values():
            present.update(tokens)
        need = [t for t in chains.tokens(query) if t in present]

        chain = chains.search(
            ordered, terms, need,
            max_steps=max_steps, beam=beam, node_budget=node_budget,
            relevance=relevance,
            plain=self.chain_plain,
            deadline_ms=deadline_ms,
        )
        if follow_relations and chain.steps:
            # A qualifier is not reachable by the search: it supplies no query
            # term, so it has no coverage to gain, and it links nothing the
            # chain needs, so it is not a bridge either. That is exactly why
            # `multi_hop_4` fails -- the memory that *modifies* the answer is
            # invisible to coverage and connectedness both. A declared relation
            # is the only thing that can put it in.
            extra: list[chains.ChainStep] = []
            present = {step.memory_id for step in chain.steps}
            for step in chain.steps:
                for kind in PULLS_IN_SUBJECT:
                    for subject in sorted(
                        self.state.related_to.get(
                            (step.memory_id, kind.value), ())
                    ):
                        if subject in present or subject not in eligible:
                            continue
                        present.add(subject)
                        extra.append(chains.ChainStep(
                            memory_id=subject,
                            reason=_ReasonCode.DEPENDENCY_REQUIRED,
                            covers=(),
                            bridges=(),
                            # Necessary by declaration rather than by
                            # leave-one-out: a qualification changes the
                            # answer, so the chain is wrong without it in a way
                            # the coverage test cannot see.
                            necessary=True,
                            rank=-1,
                        ))
            if extra:
                chain = chains.EvidenceChain(
                    steps=chain.steps + tuple(extra),
                    covered=chain.covered, missing=chain.missing,
                    nodes_explored=chain.nodes_explored,
                    budget_exhausted=chain.budget_exhausted,
                    connected=chain.connected,
                )

        if k is not None and len(chain.steps) > k:
            # Truncating can only break a chain, so `connected` is
            # recomputed rather than carried over -- a k that cuts the
            # connector out must not leave the result claiming to hold
            # together.
            kept = chain.steps[:k]
            chain = chains.EvidenceChain(
                steps=kept, covered=chain.covered,
                missing=chain.missing, nodes_explored=chain.nodes_explored,
                budget_exhausted=chain.budget_exhausted,
                connected=chains._connected(
                    [s.memory_id for s in kept],
                    {
                        s.memory_id: (
                            self.chain_plain.get(s.memory_id, frozenset())
                            - set(need)
                        )
                        for s in kept
                    },
                ),
            )

        now = self.now()
        emitted: list[ev.Event] = [
            ev.retrieval_performed(
                ts=now, agent_id=agent_id, episode_id=episode_id, query=query,
                candidates=[
                    (step.memory_id, self.state.memories[step.memory_id].version,
                     relevance.get(step.memory_id, 0.0))
                    for step in chain.steps
                ],
                context=None,
            )
        ]
        for step in chain.steps:
            emitted.append(ev.exposure_decided(
                ts=now, agent_id=agent_id, episode_id=episode_id,
                memory_id=step.memory_id,
                version=self.state.memories[step.memory_id].version,
                exposed=True,
                # Deterministic search, so the propensity is 1.0 and is
                # recorded rather than omitted. Principle 4 is unconditional:
                # without a logged propensity this exposure cannot carry credit
                # later, and "it was deterministic" is a value, not an excuse
                # to leave the field empty.
                propensity=1.0,
                policy_id=f"chain/beam={beam},steps={max_steps}",
                step=0,
            ))
        self._emit(*emitted)
        return chain

    def index_extraction(self, record: "extracting.Extracted") -> None:
        """Record the structure extracted from a memory.

        Separate from `remember` on purpose. Extraction is one model call per
        memory, so putting it on the write path would make every write depend
        on a model being reachable — and the registered prediction is that the
        cost makes it a batch job. Indexing it afterwards keeps that a
        deployment's decision.
        """
        self._require(record.memory_id)
        self.extracted[record.memory_id] = record

    def _admit_defaults(
        self, ranked: Sequence[tuple[str, float]], eligible: set[str],
        entities: Sequence[str], limit: int, k: int | None = None,
    ) -> list[tuple[str, float]]:
        """Add default rules and scoped adjustments that cover the asked entities.

        The `implied_by_default` mechanism, and the one a memory-to-memory
        relation could not provide: *"all yard vehicles run 3.9 bar in winter,
        except at the harbour and quarry sites"* names neither the unit nor the
        site asked about, so it is **not similar to the query** and no ranking
        can surface it. Its applicability is a property of what it *excludes*,
        which is a fact about the record rather than a relation between two
        memories (`research/results/relations-ceiling.md` section 3).

        **Admitted inside the exposed set, which the first version was not.**
        A default has no similarity score to compete on, so the first version
        appended it below everything in the candidate pool and called that
        neutral. It is not neutral: the pool is `max(k * 4, k)` and the policy
        then exposes the top `k`, so an admitted memory was ranked 21st of 21
        for a k of 5 and could never be exposed. The mechanism was inert in any
        store large enough to have a pool, and its unit test passed because
        that store held **one memory**.

        So an admitted record is placed just above the weakest candidate that
        would otherwise be exposed, which makes a design claim worth stating
        rather than burying: **an applicable rule is worth more than the k-th
        similarity match.** That is the whole point of admitting it — a rule
        that names neither the unit nor the site asked about cannot win on
        similarity, and if it loses to the k-th nearest neighbour it will never
        be seen.

        At most `k - 1` records are admitted, so at least one similarity match
        survives and a query matching many rules cannot have its context
        replaced by them.

        **And it drops a default that does not apply**, which is the half the
        first version missed. A rule saying *"except at the harbour site"*
        shares enough words with a question about the harbour site to be
        retrieved by similarity, and serving it there is not an incomplete
        answer but a wrong one. Applicability has to exclude as well as admit,
        or the mechanism only ever adds.
        """
        if not entities or not self.extracted:
            return list(ranked)
        wanted = [e for e in entities if e]
        out: list[tuple[str, float]] = []
        for memory_id, score in ranked:
            record = self.extracted.get(memory_id)
            if (record is not None and record.is_default
                    and not record.applies_to(wanted)):
                continue
            out.append((memory_id, score))
        present = {memory_id for memory_id, _ in out}
        records = [r for mid, r in self.extracted.items() if mid in eligible]
        # Defaults *and* scoped adjustments, by the same rule and for the same
        # reason. A default is reached through what it excludes; an adjustment
        # through what it scopes to. Neither is similar to the query and
        # neither is a relation between two memories -- twelve adjustments in
        # one corpus differ only by site name, so each qualifies every rule
        # equally and only the query says which applies. Admitting defaults
        # alone left every adjustment unreachable, which is why X1's mechanism
        # scored 0.000 with correct extractions
        # (`research/results/x1-extraction.md` section 11).
        candidates = list(extracting.applicable_defaults(records, wanted))
        candidates += [
            memory_id
            for memory_id in extracting.applicable_adjustments(records, wanted)
            if memory_id not in candidates
        ]
        # Every applicable record is promoted, **not only the ones similarity
        # missed entirely**. The first version appended only records absent
        # from the pool, so a record that ranked 6th of 60 -- inside the pool
        # of 20, outside the exposed 5 -- kept its losing similarity score and
        # was cut, while the same record in a larger store ranked below the
        # pool, counted as new, and was admitted. The mechanism helped only
        # when similarity failed *completely*, and the symptom was a
        # sufficiency that went **down** as the corpus grew: 1.000 at 486
        # memories and 0.333 at 60. Admission is a statement that the record
        # applies, which does not depend on where similarity put it.
        fresh = list(candidates)
        if not fresh:
            return out[:limit]
        out = [(m, score) for m, score in out if m not in set(fresh)]

        # The score that lands a record inside the exposed set: just above the
        # weakest candidate the policy would otherwise expose. Without `k` --
        # an older caller -- fall back to the previous behaviour rather than
        # guessing a budget.
        if k is None or k <= 0:
            floor = out[-1][1] if out else 1.0
            bump = 0.0
        else:
            exposed = [score for _m, score in out[:k]]
            floor = exposed[-1] if exposed else 1.0
            bump = 1e-6

        # Recompute the floor after removing the promoted records, so a
        # record already in the exposed set does not set its own floor.
        if k is not None and k > 0:
            exposed = [score for _m, score in out[:k]]
            floor = exposed[-1] if exposed else floor
        room = max(0, (k - 1) if k else len(fresh))
        for position, memory_id in enumerate(fresh[:room] if k else fresh):
            present.add(memory_id)
            # Descending by a hair so the admitted records keep a stable order
            # among themselves and the sort is deterministic.
            out.append((memory_id, floor + bump * (len(fresh) - position)))
        out.sort(key=lambda row: (-row[1], row[0]))
        return out[:limit]

    def relate(
        self,
        subject_memory_id: str,
        kind: str | RelationKind,
        object_memory_id: str,
        actor: str = "operator",
    ) -> None:
        """Declare a typed relation that is not a derivation.

        `memory_fabric/relations.py` has the three kinds and why each exists.
        Deliberately **not** a parent edge: `_group_by_root` spares anything
        derivation-related to a kept memory, so a qualification recorded as a
        parent would inherit an exemption meant for premises.

        Nothing discovers these. A caller declares them, or an extraction step
        at ingest does, and this project has measured neither — the first
        measurement is a ceiling given perfect declarations, because the two
        families they target are text its own generators wrote and a pattern
        fitted to that phrasing would pass by construction
        (`research/results/relations-ceiling.md`).
        """
        self._require(subject_memory_id)
        self._require(object_memory_id)
        if subject_memory_id == object_memory_id:
            raise PolicyViolation("a memory cannot stand in a relation to itself")
        self._emit(ev.memories_related(
            ts=self.now(), actor=actor,
            subject_memory_id=subject_memory_id,
            kind=RelationKind(kind).value,
            object_memory_id=object_memory_id,
        ))

    def relations_of(self, memory_id: str, kind: str | RelationKind
                     ) -> list[str]:
        """Objects this memory stands in `kind` to. Content-free."""
        return sorted(
            self.state.relations.get((memory_id, RelationKind(kind).value), ()))

    def _follow_relations(
        self, ranked: Sequence[tuple[str, float]], eligible: set[str],
        limit: int,
    ) -> list[tuple[str, float]]:
        """Pull in whatever qualifies a selected memory.

        Towards the qualifier, not away from it: a qualification changes the
        answer, so its absence makes the answer *wrong* rather than
        incomplete. Placed just below the memory it qualifies, so it travels
        with it rather than competing with it on a score it was never given.

        `EXCEPTS` is not followed here on purpose — an exception is a reason
        *not* to use a rule, and pulling it in on selection would add a memory
        arguing against the one beside it. Its use is deciding applicability,
        which is a different step.
        """
        if not ranked:
            return list(ranked)
        out: list[tuple[str, float]] = []
        present = {memory_id for memory_id, _ in ranked}
        for memory_id, score in ranked:
            out.append((memory_id, score))
            for kind in PULLS_IN_SUBJECT:
                for subject in sorted(
                    self.state.related_to.get((memory_id, kind.value), ())
                ):
                    if subject in present or subject not in eligible:
                        continue
                    present.add(subject)
                    out.append((subject, score * (1 - 1e-6)))
        return out[:limit]

    def _eligible_ids(
        self, include_contested: bool = False, tenant_id: str | None = None,
        agent_id: str | None = None,
    ) -> set[str]:
        """The one chokepoint every retrieval narrows through.

        The tenant filter belongs here rather than after ranking, for the same
        reason the lifecycle filter does: a memory excluded *before* the index
        is queried cannot be ranked, cannot be scored, cannot appear in a
        `RetrievalPerformed` event and cannot leak through a bug in a policy.
        Filtering afterwards would put the boundary downstream of the code most
        likely to be wrong.
        """
        allowed = set(EXPOSABLE_STATES)
        if include_contested:
            allowed |= EXPLORATORY_STATES
        return {
            memory_id
            for memory_id, memory in self.state.memories.items()
            if memory.lifecycle_state in allowed
            and memory.lifecycle_state not in BLOCKED_STATES
            and (tenant_id is None or memory.tenant_id == tenant_id)
            and visible_to(memory, agent_id, self.state)
        }

    def cite(self, agent_id: str, episode_id: str, memory_id: str, step: int = 0) -> None:
        """Record that the agent says it used a memory. Diagnostic only: it is
        self-reported, so it never feeds value estimation."""
        self._emit(
            ev.memory_cited(
                ts=self.now(),
                agent_id=agent_id,
                episode_id=episode_id,
                memory_id=memory_id,
                step=step,
            )
        )

    # --- value -----------------------------------------------------------

    def value(
        self, memory_id: str, context: Mapping[str, Any] | None = None, persist: bool = False
    ) -> ValueEstimate:
        self._require(memory_id)
        self._refresh_estimator()
        estimate = self.estimator.estimate(memory_id, context)
        if persist:
            self._emit(
                ev.value_estimated(
                    ts=self.now(),
                    memory_id=memory_id,
                    context_key=context_key(context),
                    estimate=estimate.to_json(),
                    estimator_id=self.estimator.id,
                )
            )
        return estimate

    def stats(self, memory_id: str) -> MemoryStats:
        self._require(memory_id)
        return self.state.stats_for(memory_id)

    # --- lifecycle -------------------------------------------------------

    def _transition(
        self,
        memory_id: str,
        to_state: LifecycleState,
        reason: str,
        actor: str,
        basis: str | None = None,
    ) -> ev.Event:
        memory = self._require(memory_id)
        return ev.lifecycle_changed(
            ts=self.now(),
            memory_id=memory_id,
            from_state=memory.lifecycle_state.value,
            to_state=to_state.value,
            reason=reason,
            actor=actor,
            basis=basis,
        )

    @_fresh
    def validate(self, memory_id: str, actor: str, reason: str = "validated") -> Memory:
        """Promote a candidate to active."""
        memory = self._require(memory_id)
        if memory.lifecycle_state is LifecycleState.QUARANTINED:
            raise PolicyViolation(
                f"{memory_id} is quarantined; review and release it before validating"
            )
        self._emit(self._transition(memory_id, LifecycleState.ACTIVE, reason, actor))
        return self.state.memories[memory_id]

    @_fresh
    def quarantine(
        self,
        memory_id: str,
        reason: str,
        actor: str = "operator",
        propagate: bool = True,
        basis: str | WithdrawalBasis | None = None,
    ) -> list[str]:
        """Quarantine a memory and contest everything derived from it.

        This is the retraction step. Quarantining alone is not enough: the
        descendants were justified by this memory, so they lose their
        justification and must be re-examined. Without the propagation, a
        poisoned memory survives its own rollback through its children.

        **Do not drive this from "it was in context when something failed."**
        Phase A measured that policy and it made an agent substantially worse:
        it cut the rate at which a correct memory reached the prompt from 60% of
        episodes to 18%, because the memory that asserted what the agent wrongly
        said was usually a *correct* memory about a different situation that
        happened to name the same action. Agreement with a mistake is not
        evidence of having caused it. Quarantine on evidence about the memory —
        a sensitive-data finding, a contradiction with a verified fact, a
        contrastive estimate showing harm — not on co-occurrence with a failure.
        See research/results/phase-a-real-agent-benchmark.md.

        `basis` says *what kind of evidence* this rests on
        (`WithdrawalBasis`). It is optional so that existing callers keep
        working, and an omitted basis is recorded as `unstated` — which the
        attention list then surfaces, because "nobody said" is exactly the case
        worth a second look.

        Returns the ids marked contested.
        """
        self._require(memory_id)
        basis_value = (
            basis.value if isinstance(basis, WithdrawalBasis) else basis
        ) or WithdrawalBasis.UNSTATED.value
        emitted = [
            self._transition(
                memory_id, LifecycleState.QUARANTINED, reason, actor, basis_value
            )
        ]
        contested: list[str] = []
        if propagate:
            # Recompute support rather than assume its loss.
            #
            # This loop used to mark *every* descendant contested, so a
            # conclusion resting on two independent premises was treated
            # exactly like one resting on a single invalidated premise.
            # `evidence_is_independent` existed to tell them apart and nothing
            # called it, which is why roadmap §4.2 — correct a belief without
            # withdrawing unrelated knowledge — was unimplemented.
            #
            # The quarantine is emitted first so the recomputation sees the
            # premise as already lost; otherwise every descendant would still
            # find it usable and nothing would be contested at all.
            self._emit(*emitted)
            emitted = []

            # Nearest first, recomputing each one *after* the previous
            # transition has been emitted. Batching the verdicts against a
            # single snapshot looked equivalent and was not: a grandchild was
            # evaluated while its parent was still active, so it stayed
            # justified and the cascade stopped one level short. The lineage
            # walk is already ordered by depth, so one pass suffices.
            for node in sorted(
                self.lineage_graph.descendants(memory_id), key=lambda n: n.depth
            ):
                descendant = self.state.memories.get(node.memory_id)
                if descendant is None:
                    continue
                if descendant.lifecycle_state in (
                    LifecycleState.QUARANTINED,
                    LifecycleState.DELETED,
                ):
                    continue

                verdict = self.justifications.recompute(node.memory_id)
                record = ev.support_recomputed(
                    ts=self.now(),
                    memory_id=verdict.memory_id,
                    trigger_memory_id=memory_id,
                    verdict=verdict.verdict,
                    surviving=list(verdict.surviving),
                    lost=list(verdict.lost),
                    independent_count=verdict.independent_count,
                    reason=verdict.reason,
                    actor=actor,
                )
                if verdict.still_justified:
                    # Independently justified knowledge survives the loss of one
                    # premise. Recorded anyway, so an operator can see that the
                    # recomputation happened and what carried the conclusion.
                    self._emit(record)
                    continue

                self._emit(
                    record,
                    self._transition(
                        verdict.memory_id,
                        LifecycleState.CONTESTED,
                        f"support recomputed after {memory_id} was quarantined: "
                        f"{verdict.reason}",
                        actor,
                    ),
                )
                contested.append(verdict.memory_id)

            # Copies, which are not descendants and must not be treated as
            # such. A re-ingestion is not *justified by* the original -- it is
            # the same document -- so `justifications.recompute` has nothing to
            # say about it and would leave it standing. Withdrawing a document
            # withdraws every copy of it, transitively, and then the normal
            # recomputation runs over whatever those copies support.
            #
            # Without this, withdrawal order decided the outcome: a copy
            # written *after* the original was withdrawn came in contested,
            # while one written before it stayed active. The same two memories
            # and the same finding, with opposite results depending on which
            # arrived first.
            for copy_id in self._copy_closure(memory_id):
                copy = self.state.memories.get(copy_id)
                if copy is None or copy.lifecycle_state in (
                    LifecycleState.QUARANTINED,
                    LifecycleState.DELETED,
                    LifecycleState.CONTESTED,
                ):
                    continue
                self._emit(self._transition(
                    copy_id,
                    LifecycleState.CONTESTED,
                    f"re-ingestion of {memory_id}, which was withdrawn: {reason}",
                    actor,
                    basis_value,
                ))
                contested.append(copy_id)
                for node in sorted(
                    self.lineage_graph.descendants(copy_id),
                    key=lambda n: n.depth,
                ):
                    downstream = self.state.memories.get(node.memory_id)
                    if downstream is None or downstream.lifecycle_state in (
                        LifecycleState.QUARANTINED,
                        LifecycleState.DELETED,
                        LifecycleState.CONTESTED,
                    ):
                        continue
                    verdict = self.justifications.recompute(node.memory_id)
                    self._emit(ev.support_recomputed(
                        ts=self.now(),
                        memory_id=verdict.memory_id,
                        trigger_memory_id=copy_id,
                        verdict=verdict.verdict,
                        surviving=list(verdict.surviving),
                        lost=list(verdict.lost),
                        independent_count=verdict.independent_count,
                        reason=verdict.reason,
                        actor=actor,
                    ))
                    if not verdict.still_justified:
                        self._emit(self._transition(
                            verdict.memory_id,
                            LifecycleState.CONTESTED,
                            f"support recomputed after copy {copy_id} was "
                            f"contested: {verdict.reason}",
                            actor,
                        ))
                        contested.append(verdict.memory_id)
        self._emit(*emitted)
        return contested

    def _copy_closure(self, memory_id: str) -> list[str]:
        """Every other memory that is the same document as this one.

        **Symmetric**, which the first version was not. "These are the same
        document" does not have a direction, but the recorded edge does: the
        newer write points at the older one. So when a corpus arrives shuffled
        and the copy happens to be stored *before* the original, the edge runs
        copy -> original the other way round, and a walk that followed only
        `copies` found nothing. Withdrawing the original then left the copy
        standing -- the same ingestion order deciding the outcome that the
        write-time check was added to remove, surviving one level down.

        The relation is therefore walked as an undirected component over both
        indexes. A copy of a copy is still the same document, so it is
        transitive too. Ordered and cycle-guarded: the edges come from the log,
        and a propagation walk is the wrong place to discover a malformed one.
        """
        out: list[str] = []
        seen = {memory_id}
        frontier = [memory_id]
        while frontier:
            current = frontier.pop()
            neighbours = set(self.state.copies.get(current, ()))
            original = self.state.copy_of.get(current)
            if original is not None:
                neighbours.add(original)
            for other in sorted(neighbours):
                if other in seen:
                    continue
                seen.add(other)
                out.append(other)
                frontier.append(other)
        return out

    def release(self, memory_id: str, actor: str, reason: str = "reviewed and released") -> Memory:
        """Bring a quarantined memory back to candidate after human review."""
        memory = self._require(memory_id)
        if memory.lifecycle_state is not LifecycleState.QUARANTINED:
            raise PolicyViolation(f"{memory_id} is not quarantined")
        self._emit(self._transition(memory_id, LifecycleState.CANDIDATE, reason, actor))
        return self.state.memories[memory_id]

    def forget(self, memory_id: str, reason: str, actor: str = "operator") -> Memory:
        """Deprecate. Deletion is the retention policy's decision, not the
        caller's, so that a single call can never destroy an audit trail."""
        self._emit(self._transition(memory_id, LifecycleState.DEPRECATED, reason, actor))
        self._unindex(memory_id)
        return self.state.memories[memory_id]

    def challenge(
        self,
        memory_ids: Sequence[str],
        evidence: str,
        detector_id: str = "manual",
        confidence: float = 1.0,
        hypothesis_set: str | None = None,
        actor: str = "operator",
    ) -> str:
        """Open or extend a hypothesis set over contradictory memories.

        Nothing is deleted and no winner is chosen. The memories become
        `contested` and travel together from here on, because a disagreement is
        information and collapsing it early is the failure mode this whole
        design is built to avoid.
        """
        for memory_id in memory_ids:
            self._require(memory_id)
        set_id = hypothesis_set or f"hset_{new_ulid()}"
        now = self.now()
        emitted: list[ev.Event] = [
            ev.conflict_detected(
                ts=now,
                memory_ids=list(memory_ids),
                detector_id=detector_id,
                confidence=confidence,
                hypothesis_set=set_id,
                actor=actor,
            )
        ]
        for memory_id in memory_ids:
            memory = self.state.memories[memory_id]
            if memory.lifecycle_state in (LifecycleState.ACTIVE, LifecycleState.CANDIDATE):
                emitted.append(
                    self._transition(
                        memory_id,
                        LifecycleState.CONTESTED,
                        f"conflict: {evidence}",
                        actor,
                    )
                )
        self._emit(*emitted)
        return set_id

    def resolve(
        self,
        hypothesis_set: str,
        winner_id: str | None,
        design: Mapping[str, Any],
        results: Mapping[str, Any],
        actor: str = "operator",
    ) -> None:
        """Close a hypothesis set with evidence.

        Losers are deprecated rather than deleted, so that later contradictory
        evidence can bring the question back rather than meeting a store that
        has forgotten the alternative ever existed.
        """
        hset = self.state.hypothesis_sets.get(hypothesis_set)
        if hset is None:
            raise NotFound(f"no hypothesis set {hypothesis_set!r}")
        payload = dict(results)
        payload["resolved"] = True
        emitted: list[ev.Event] = [
            ev.experiment_run(
                ts=self.now(),
                hypothesis_set=hypothesis_set,
                design=design,
                results=payload,
            )
        ]
        for memory_id in sorted(hset.memory_ids):
            if memory_id == winner_id:
                emitted.append(
                    self._transition(
                        memory_id, LifecycleState.ACTIVE, "won experiment", actor
                    )
                )
            else:
                emitted.append(
                    self._transition(
                        memory_id,
                        LifecycleState.DEPRECATED,
                        f"lost experiment in {hypothesis_set}",
                        actor,
                    )
                )
        self._emit(*emitted)

    # --- sharing ---------------------------------------------------------

    def firewall_check(
        self,
        memory_id: str,
        target_scope: str | Scope,
        granted_capabilities: Iterable[str] = (),
    ) -> FirewallRuling:
        memory = self._require(memory_id)
        hset = (
            self.state.hypothesis_sets.get(memory.hypothesis_set)
            if memory.hypothesis_set
            else None
        )
        siblings = sorted(hset.memory_ids) if hset else [memory_id]
        return self.firewall.evaluate(
            FirewallRequest(
                memory=memory,
                target_scope=Scope(target_scope),
                value=self.value(memory_id),
                hypothesis_open=bool(hset and not hset.resolved),
                granted_capabilities=frozenset(granted_capabilities),
                evidence_independent=self.lineage_graph.evidence_is_independent(siblings)
                if len(siblings) > 1
                else True,
            )
        )

    @_fresh
    def share(
        self,
        memory_id: str,
        scope: str | Scope,
        actor: str = "operator",
        granted_capabilities: Iterable[str] = (),
    ) -> FirewallRuling:
        """Promote a memory's scope, if the firewall allows it.

        Default-deny: the scope changes only on ALLOW or ALLOW_WITH_WARNING, and
        the ruling is recorded either way so a refusal is as auditable as a
        grant.
        """
        memory = self._require(memory_id)
        target = Scope(scope)
        ruling = self.firewall_check(memory_id, target, granted_capabilities)

        emitted: list[ev.Event] = []
        if ruling.permits_sharing:
            emitted.append(
                ev.scope_changed(
                    ts=self.now(),
                    memory_id=memory_id,
                    from_scope=memory.scope.value,
                    to_scope=target.value,
                    firewall_decision=ruling.decision.value,
                    reasons=ruling.reasons,
                    actor=actor,
                )
            )
        else:
            # A denial is a scope_changed event to the *same* scope: the attempt
            # and its reasons belong in the audit trail.
            emitted.append(
                ev.scope_changed(
                    ts=self.now(),
                    memory_id=memory_id,
                    from_scope=memory.scope.value,
                    to_scope=memory.scope.value,
                    firewall_decision=ruling.decision.value,
                    reasons=ruling.reasons,
                    actor=actor,
                )
            )
            if ruling.decision is FirewallDecision.QUARANTINE:
                emitted.append(
                    self._transition(
                        memory_id,
                        LifecycleState.QUARANTINED,
                        "; ".join(ruling.reasons),
                        self.firewall.id,
                        WithdrawalBasis.SENSITIVE_DATA.value,
                    )
                )
        self._emit(*emitted)
        return ruling

    # --- inspection ------------------------------------------------------

    # --- collections (schema 0.10.0) --------------------------------------

    def _collection_event(self, name: str, action: str, actor: str, tenant_id: str,
                          **fields: Any) -> None:
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise PolicyViolation("a collection name is letters, digits, '-' and '_'")
        if not actor or actor == "operator":
            raise PolicyViolation("name who is changing this collection: it is audited")
        self._emit(ev.collection_changed(ts=self.now(), tenant_id=tenant_id, collection=name,
                                         action=action, actor=actor, **fields))

    @_fresh
    def collection_add(self, name: str, memory_id: str, actor: str) -> None:
        """Put a memory in a collection. Its readers can then read it, even if private.

        A restricted memory cannot join one: a collection is a way to widen
        who reads, and restricted memories stay private.
        """
        memory = self._require(memory_id)
        if memory.security_class is SecurityClass.RESTRICTED:
            raise PolicyViolation("a restricted memory stays private; it cannot join a collection")
        self._collection_event(name, "add", actor, memory.tenant_id, memory_id=memory_id)

    @_fresh
    def collection_remove(self, name: str, memory_id: str, actor: str) -> None:
        memory = self._require(memory_id)
        self._collection_event(name, "remove", actor, memory.tenant_id, memory_id=memory_id)

    @_fresh
    def collection_grant(self, name: str, agent_id: str, permissions: Iterable[str],
                         actor: str, tenant_id: str = DEFAULT_TENANT) -> None:
        """Attach an agent (`read`) or grant it more. See `model.PERMISSIONS`."""
        from .model import PERMISSIONS

        perms = set(permissions)
        if not perms or not perms <= set(PERMISSIONS):
            raise PolicyViolation(f"permissions must be a non-empty subset of {PERMISSIONS}")
        self._collection_event(name, "grant", actor, tenant_id, agent_id=agent_id,
                               permissions=sorted(perms))

    @_fresh
    def collection_revoke(self, name: str, agent_id: str, actor: str,
                          permissions: Iterable[str] = (), tenant_id: str = DEFAULT_TENANT) -> None:
        """Detach an agent (no permissions named: all of them) or take some back."""
        self._collection_event(name, "revoke", actor, tenant_id, agent_id=agent_id,
                               permissions=sorted(set(permissions)))

    def collections(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Name -> members and grants, for one tenant or all (`tenant/name` keys)."""
        out = {}
        for (tenant, name), c in self.state.collections.items():
            if tenant_id is not None and tenant != tenant_id:
                continue
            key = name if tenant_id is not None else f"{tenant}/{name}"
            out[key] = {"members": sorted(c.members),
                        "grants": {a: sorted(p) for a, p in sorted(c.grants.items())}}
        return out

    @_fresh
    def get(self, memory_id: str) -> Memory:
        """**Inspection only. Not an agent-facing read.**

        Returns a memory whatever its lifecycle state, which is correct for an
        operator tool asking "what is this and why was it withdrawn?" and wrong
        for anything that will put the content in front of a model. Phase 0's
        audit found this was the one way to reach past the lifecycle check
        without knowing it.

        The enforced read is `use()`. Supported adapters must call that; this
        exists for `explain`, the dashboard and the CLI, none of which hand
        memories to an agent.
        """
        return self._require(memory_id)

    # --- identity --------------------------------------------------------

    @property
    def principals(self) -> PrincipalRegistry:
        """Who this store will act as. The authorisation boundary for agents,
        the way `PeerRegistry` is for stores."""
        if self._principals is None:
            self._principals = PrincipalRegistry()
        return self._principals

    def for_tenant(self, tenant_id: str, agent_id: str) -> "TenantView":
        """A handle that can only see and write one tenant's memories.

        The operator path: the caller asserts the tenant and nothing verifies
        the assertion, which is honest because a caller holding the fabric
        could act on any tenant anyway. What this buys is that code written
        against the view *cannot forget* to scope a read — the boundary is in
        the handle rather than in a keyword argument at every call site.

        `as_principal` is the same handle with the assertion checked.
        """
        return TenantView(
            self, Principal(agent_id=agent_id, tenant_id=tenant_id), verified=False
        )

    def as_principal(self, credential: Credential) -> "TenantView":
        """Verify a credential and return a handle bound to that principal.

        Raises `IdentityError` rather than returning an empty view: a caller
        whose credential does not verify has not asked a question that has an
        answer, and silently scoping them to nothing would look like "this
        tenant has no memories".
        """
        principal = self.principals.verify(credential, self.now())
        return TenantView(self, principal, verified=True)

    @_fresh
    def lifecycle_of(self, memory_id: str) -> LifecycleState:
        """One memory's lifecycle state, and **no content**.

        Exists because the adapters wanted to tell a model what happened to its
        own write and were reaching for `get()` to do it. `get()` returns a
        withdrawn memory on purpose — an operator judging a withdrawal has to
        read what was withdrawn — so an adapter holding it is one autocomplete
        away from serving retracted knowledge to a model, and it would look
        like working code.

        Found by the data-access audit, which flagged every `fabric.get(` in
        the shipped examples and adapters.
        """
        return self._require(memory_id).lifecycle_state

    def tenant_of(self, memory_id: str) -> str:
        return self._require(memory_id).tenant_id

    def tenants(self) -> dict[str, int]:
        """Which tenants this store holds, and how many memories each has.

        An operator view. It is also the thing a `doctor` check needs in order
        to notice that a store believed to be single-tenant is not.
        """
        counts: dict[str, int] = {}
        for memory in self.state.memories.values():
            counts[memory.tenant_id] = counts.get(memory.tenant_id, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def justifications(self) -> "JustificationGraph":
        if self._justifications is None:
            self._justifications = JustificationGraph(self)
        return self._justifications

    @property
    def enforcer(self) -> "Enforcer":
        if self._enforcer is None:
            self._enforcer = Enforcer(self)
        return self._enforcer

    @_fresh
    def use(
        self,
        memory_id: str,
        agent_id: str,
        risk: "RiskLevel" = RiskLevel.LOW,
        include_contested: bool = False,
        audit: bool = True,
        tenant_id: str | None = None,
    ) -> "EnforcedRead":
        """The enforced read: one layer, and a token that can be re-checked.

        Returns the memory only when the decision allows it, so a caller that
        ignores the decision still cannot act on withdrawn knowledge. A refusal
        is audited without the content (see `ev.access_denied`).
        """
        decision = self.enforcer.check(
            memory_id, risk=risk, include_contested=include_contested,
            tenant_id=tenant_id, agent_id=agent_id,
        )
        if not decision.usable:
            if audit:
                self._emit(
                    ev.access_denied(
                        ts=self.now(),
                        memory_id=memory_id,
                        version=decision.version,
                        agent_id=agent_id,
                        verdict=decision.verdict.value,
                        reason_code=decision.reason_code,
                        risk=risk.value,
                        detail=decision.detail,
                    )
                )
            return EnforcedRead(decision=decision)

        memory = self.state.memories[memory_id]
        token = self.enforcer.issue(
            memory_id, agent_id, decision, policy_id=self.policy.id,
            tenant_id=tenant_id,
        )
        warnings = [decision.detail] if decision.verdict is Verdict.WARN and decision.detail else []
        return EnforcedRead(
            decision=decision, token=token, memory=memory, warnings=warnings
        )

    @_fresh
    def verify_before_action(
        self,
        token: "ExposureToken",
        agent_id: str,
        risk: "RiskLevel" = RiskLevel.HIGH,
        audit: bool = True,
    ) -> "AccessDecision":
        """Re-check immediately before a consequential action.

        The time-of-check/time-of-use defence. Retrieval may have been minutes
        ago and a retraction may have arrived since; re-running the check reads
        projections and is cheap, and the alternative is acting on knowledge its
        author has withdrawn.
        """
        decision = self.enforcer.verify_at_action(token, agent_id, risk=risk)
        if not decision.usable and audit:
            self._emit(
                ev.access_denied(
                    ts=self.now(),
                    memory_id=decision.memory_id,
                    version=decision.version,
                    agent_id=agent_id,
                    verdict=decision.verdict.value,
                    reason_code=decision.reason_code,
                    risk=risk.value,
                    detail=decision.detail,
                )
            )
        return decision

    @_fresh
    def certify(
        self,
        claim_id: str,
        evidence: Sequence[Any],
        agent_id: str,
        tenant_id: str | None = None,
        required_checks: Sequence[str] = (),
        min_independent_sources: int = 1,
        ttl_ms: int | None = 300_000,
    ) -> "EvidenceCertificate":
        """Record the evidence a decision rests on, for re-checking at action
        time (`certificates.py`). Issuing checks nothing; `verify_certificate`
        does, against the store as it is then."""
        from .certificates import ALWAYS, CertificateVerifier

        return CertificateVerifier(self).issue(
            claim_id, evidence, agent_id, tenant_id=tenant_id,
            required_checks=tuple(required_checks) or ALWAYS,
            min_independent_sources=min_independent_sources, ttl_ms=ttl_ms,
        )

    @_fresh
    def verify_certificate(
        self,
        certificate: Any,
        agent_id: str,
        tenant_id: str | None = None,
        risk: "RiskLevel" = RiskLevel.HIGH,
        mode: str = "selective",
    ) -> "CertificateVerification":
        """Re-check every piece of evidence in a certificate, now. Fails closed."""
        from .certificates import CertificateVerifier

        return CertificateVerifier(self, mode=mode).verify(
            certificate, agent_id=agent_id, tenant_id=tenant_id, risk=risk)

    def history(self, memory_id: str) -> list[Memory]:
        self._require(memory_id)
        return list(self.state.history.get(memory_id, ())) + [self.state.memories[memory_id]]

    def lineage(self, memory_id: str) -> LineageView:
        self._require(memory_id)
        return self.lineage_graph.view(memory_id)

    def audit_trail(self, memory_id: str) -> list[ev.Event]:
        """Every event that mentions this memory, in log order."""
        self._require(memory_id)
        out: list[ev.Event] = []
        for event in self.log.read():
            payload = event.payload
            if payload.get("memory_id") == memory_id:
                out.append(event)
            elif memory_id in (payload.get("memory_ids") or ()):
                out.append(event)
            elif isinstance(payload.get("memory"), dict) and payload["memory"].get("id") == memory_id:
                out.append(event)
            elif any(
                c.get("memory_id") == memory_id for c in (payload.get("candidates") or ())
            ):
                out.append(event)
        return out

    def explain(self, memory_id: str) -> "Explanation":
        from .explain import explain_memory

        return explain_memory(self, memory_id)

    def health(self) -> HealthReport:
        by_state: dict[str, int] = {}
        by_scope: dict[str, int] = {}
        by_type: dict[str, int] = {}
        unverified = never_exposed = 0
        self._refresh_estimator()
        for memory in self.state.memories.values():
            by_state[memory.lifecycle_state.value] = by_state.get(memory.lifecycle_state.value, 0) + 1
            by_scope[memory.scope.value] = by_scope.get(memory.scope.value, 0) + 1
            by_type[memory.type.value] = by_type.get(memory.type.value, 0) + 1
            stats = self.state.stats_for(memory.id)
            # The live estimate, not the projected one. `stats.value_estimate` is
            # only populated by value(persist=True), so counting it here would
            # report every memory as unverified in the normal case and contradict
            # anything that asks the estimator directly.
            if self.estimator.estimate(memory.id).n_eff <= 0.0:
                unverified += 1
            if stats.exposures == 0:
                never_exposed += 1
        return HealthReport(
            total=len(self.state.memories),
            by_state=by_state,
            by_scope=by_scope,
            by_type=by_type,
            unverified=unverified,
            contested=by_state.get(LifecycleState.CONTESTED.value, 0),
            quarantined=by_state.get(LifecycleState.QUARANTINED.value, 0),
            never_exposed=never_exposed,
            open_hypothesis_sets=sum(
                1 for h in self.state.hypothesis_sets.values() if not h.resolved
            ),
            episodes=len(self.state.episodes),
            episodes_with_outcome=sum(1 for e in self.state.episodes.values() if e.has_outcome),
            events=len(self.log),
        )

    def sweep_retention(self, apply: bool = False, actor: str = "retention",
                        actions: Iterable[str] | None = None) -> list[RetentionDecision]:
        """The retention policy's decisions; with `apply`, carry them out.

        `actions` limits what is applied (for example `{"deprecate"}`). The
        background manager uses it: `delete` is terminal, so an unattended
        process applies it only when the owner has opted in (`manager.py`).
        """
        now = self.now()
        pairs = [
            (memory, self.state.stats_for(memory.id))
            for memory in self.state.memories.values()
        ]
        decisions = self.retention.sweep(pairs, now)
        if actions is not None:
            allowed = set(actions)
            decisions = [d for d in decisions if d.action in allowed]
        if apply:
            emitted: list[ev.Event] = []
            for decision in decisions:
                to_state = (
                    LifecycleState.DELETED
                    if decision.action == "delete"
                    else LifecycleState.DEPRECATED
                )
                emitted.append(
                    self._transition(decision.memory_id, to_state, decision.reason, actor)
                )
                self._unindex(decision.memory_id)
            if emitted:
                self._emit(*emitted)
        return decisions

    def rebuild(self) -> None:
        """Throw away all derived state and rebuild it from the log."""
        self._replay()

    def close(self) -> None:
        self.log.close()

    def __enter__(self) -> "MemoryFabric":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# Re-exported for typing convenience at the bottom to avoid a circular import.
from .explain import Explanation  # noqa: E402

@dataclass
class TenantView:
    """One tenant's slice of a store, bound to one acting agent.

    Not a security perimeter against a caller holding the `MemoryFabric` — that
    perimeter does not exist inside a library and `identity.py` says so. What
    this is, is the shape that makes the boundary unforgettable: the methods
    here take no `tenant_id`, so there is no call site at which someone can
    omit it, and `agent_id` is supplied once rather than typed again at every
    write.

    `verified` records which door the handle came through. `as_principal`
    checked a signature; `for_tenant` took the caller's word. Keeping the two
    distinguishable matters because an audit question — "was this write made by
    an authenticated principal?" — has a different answer in each case, and a
    view that forgot could only answer it by guessing.
    """

    fabric: "MemoryFabric"
    principal: Principal
    verified: bool = False

    @property
    def tenant_id(self) -> str:
        return self.principal.tenant_id

    @property
    def agent_id(self) -> str:
        return self.principal.agent_id

    # --- writes ----------------------------------------------------------

    def remember(self, content: str, **kwargs: Any) -> str:
        kwargs.pop("tenant_id", None)
        kwargs.pop("agent_id", None)
        return self.fabric.remember(
            agent_id=self.agent_id, content=content, tenant_id=self.tenant_id, **kwargs
        )

    def derive(self, content: str, parents: Sequence[str], **kwargs: Any) -> str:
        """Derive within the tenant, refusing to inherit from outside it.

        Checked rather than assumed: `derive` copies its parents' context, and
        a conclusion drawn from another tenant's premise would carry that
        tenant's provenance into this one. The memory would be labelled with
        this tenant and justified by a memory nobody here may read.
        """
        for parent in parents:
            if self.fabric.tenant_of(parent) != self.tenant_id:
                if self.fabric.conceal_cross_tenant:
                    # Exactly what a missing id raises, so a derive cannot be
                    # used to learn that another tenant's id exists.
                    raise NotFound(f"no memory {parent!r}")
                raise IdentityError(
                    f"{parent} belongs to another tenant; a conclusion cannot "
                    "be justified by a premise this tenant may not read"
                )
        kwargs.pop("agent_id", None)
        kwargs.pop("tenant_id", None)
        return self.fabric.derive(
            agent_id=self.agent_id, content=content, parents=parents,
            tenant_id=self.tenant_id, **kwargs
        )

    # --- reads -----------------------------------------------------------

    def retrieve(self, query: str, **kwargs: Any) -> "RetrievalResult":
        kwargs.pop("tenant_id", None)
        kwargs.pop("agent_id", None)
        return self.fabric.retrieve(
            agent_id=self.agent_id, query=query, tenant_id=self.tenant_id, **kwargs
        )

    def use(self, memory_id: str, **kwargs: Any) -> "EnforcedRead":
        kwargs.pop("tenant_id", None)
        kwargs.pop("agent_id", None)
        return self.fabric.use(
            memory_id, agent_id=self.agent_id, tenant_id=self.tenant_id, **kwargs
        )

    def verify_before_action(self, token: "ExposureToken", **kwargs: Any):
        kwargs.pop("agent_id", None)
        return self.fabric.verify_before_action(token, self.agent_id, **kwargs)

    def certify(self, claim_id: str, evidence: Sequence[Any], **kwargs: Any):
        kwargs.pop("tenant_id", None)
        kwargs.pop("agent_id", None)
        return self.fabric.certify(claim_id, evidence, self.agent_id,
                                   tenant_id=self.tenant_id, **kwargs)

    def verify_certificate(self, certificate: Any, **kwargs: Any):
        kwargs.pop("tenant_id", None)
        kwargs.pop("agent_id", None)
        return self.fabric.verify_certificate(certificate, self.agent_id,
                                              tenant_id=self.tenant_id, **kwargs)

    def memory_ids(self) -> list[str]:
        """Every memory in this tenant, whatever its lifecycle state.

        Deliberately *not* filtered by lifecycle: this is the inventory, and an
        operator asking what a tenant holds needs the quarantined ones too.
        Reading one still goes through `use`.
        """
        return sorted(
            memory_id
            for memory_id, memory in self.fabric.state.memories.items()
            if memory.tenant_id == self.tenant_id
        )
