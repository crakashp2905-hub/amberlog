"""The core every MemoryFabric service builds on: the store's identity, the event log,
refresh across processes, transactions and replay. Methods moved verbatim from
`fabric.py`, where `MemoryFabric` composes this core with the services."""

from __future__ import annotations

__stability__ = "stable"



import random
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from ..fabric import MemoryFabric  # noqa: F401
    pass

from .. import events as ev
from ..estimators import ValueEstimator, build_estimator
from ..eventlog import EventLog
from ..exposure import ExposurePolicy, build_policy
from ..governance.firewall import Firewall
from ..governance.retention import RetentionPolicy
from .. import duplicates
from .. import extraction as extracting
from ..lineage import LineageGraph
import json

from ..justification import JustificationGraph
from ..enforcement import (
    Enforcer,
)
from ..governance.erasure import (
    ContentVault,
    KeyProvider,
)
from ..outbox import Outbox
from ..protocol import (
    PROTOCOL_VERSION,
    new_store_id,
)
from ..identity import (
    PrincipalRegistry,
)
from ..model import (
    SCHEMA_VERSION,
    ValueEstimate,
    WithdrawalBasis,
    LifecycleState,
    Memory,
)
from ..projections import Projection
from ..vectors import (
    Embedder,
    LexicalIndex,
    VectorIndex,
)


from .common import NotFound, PolicyViolation, _fresh


class FabricCore:
    if TYPE_CHECKING:
        # Implemented by the services (`MemoryFabric` composes them all) and
        # called across them. Declared here for the type checker only, so they
        # cannot shadow the implementations at runtime. Generated from the real
        # signatures; `tests/test_fabric_structure.py` checks they still match.
        def _unseal_content(self, content: str, memory_id: str, version: int=1) -> str: ...
        def _seal_content(self, content: str, memory_id: str, version: int=1) -> str: ...
        def _suspicious(self, agent_id: str, content: str, context: Any, tenant_id: str) -> bool: ...
        def shared_with(self, memory_id: str) -> dict[str, str]: ...
        def _index(self, memory_id: str, text: str) -> None: ...
        def _unindex(self, memory_id: str) -> None: ...
        @staticmethod
        def _index_text(memory: Memory) -> str: ...
        def value(self, memory_id: str, context: Mapping[str, Any] | None=None, persist: bool=False) -> ValueEstimate: ...
        def _transition(self, memory_id: str, to_state: LifecycleState, reason: str, actor: str, basis: str | None=None) -> ev.Event: ...
        def quarantine(self, memory_id: str, reason: str, actor: str='operator', propagate: bool=True, basis: str | WithdrawalBasis | None=None) -> list[str]: ...
        def get(self, memory_id: str) -> Memory: ...


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
        rerank: "bool | str | Any" = False,
        conceal_cross_tenant: bool = False,
        limits: "Any" = None,
        withhold_hostile_sources: bool = True,
        hold_suspicious: bool = True,
        crypto_profile: str | None = None,
        contest_restatements: bool = True,
        claim_checker: Any = None,
    ) -> None:
        # Off by default to keep the documented reason code. On, a request
        # from another tenant is refused exactly as a missing id is, so the
        # refusal does not confirm that the id exists anywhere (plan Task 11).
        self.conceal_cross_tenant = conceal_cross_tenant
        from ..limits import Limits, Meter

        self.limits = Meter(limits or Limits())
        # On by default (T2b, supported: safe success 0.732 -> 0.949, honest
        # sources unharmed). Withholds memories whose author an ingest screen
        # caught injecting, here or at a peer that sent a signed notice. Only
        # the hostile signal: T2 measured that withholding on any withdrawal
        # destroys honest authors' notes.
        self.withhold_hostile_sources = withhold_hostile_sources
        # On by default: a write that contradicts what the store knows is held
        # as a candidate even where clean writes activate at once (V1:
        # detection 1.00 on three poison families, 0 of 450 honest writes held).
        self.hold_suspicious = hold_suspicious
        # On by default: correcting or withdrawing a fact contests the other
        # notes that repeat its old value (validation.restatements). Contested
        # is withheld from retrieval and visible to an operator; nothing is
        # deleted, and a reviewer can resolve it.
        self.contest_restatements = contest_restatements
        # Checked at open, not at the first write: a production deployment
        # without the maintained library must fail to start, not fall back.
        from ..governance import cipher

        if crypto_profile is not None:
            cipher.set_profile(crypto_profile)
        if encrypt_content:
            cipher.require_profile()
        self._hostile_cache: tuple[int, frozenset[str]] = (-1, frozenset())
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
        # constructor argument. An object with a `score(query, texts)` method
        # (`retrievers.CrossEncoderReranker`) is a model reranker instead.
        self.rerank = rerank
        # Optional model-backed check for free-text claims (`claimcheck.py`).
        self.claim_checker = claim_checker
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
            # Vectors are built only when something searches them: lazily in
            # lexical mode (the default), eagerly otherwise (vectors.py).
            self.index = VectorIndex(embedder, lazy=retrieval == "lexical")
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

    @property
    def store_id(self) -> str:
        """This store's identity. Never a path: the old origin record used
        `log.path`, so two containers each holding `./store.db` were
        indistinguishable and `:memory:` identified every in-memory store."""
        assert self.state.store_id is not None, "store identity not minted"
        return self.state.store_id

    @_fresh
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
        tracked = self.state.memories
        tracked.begin()  # type: ignore[attr-defined]
        for event in stored:
            self.projection.apply(event)
        self._reindex_changed(dict(tracked.before))  # type: ignore[attr-defined]
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
        tracked = self.state.memories
        tracked.begin()  # type: ignore[attr-defined]
        events = list(self.log.read(since_seq=self._seen_seq))
        self.projection.apply_all(events)
        self._reindex_changed(dict(tracked.before))  # type: ignore[attr-defined]
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

        `before` holds only the memories the fold touched, with their prior
        versions (`projections.ChangeTrackingDict`), so the cost is the size of
        the change, not of the table.
        """
        warm = None if self.index.lazy else getattr(self.index.embedder, "warm", None)
        if warm is not None and len(before) > 1:
            # A trained embedder batches: one call for a replayed log rather
            # than one per memory. Already-embedded texts are skipped by it.
            warm([self._index_text(m) for mid in before
                  if (m := self.state.memories.get(mid)) is not None
                  and m.lifecycle_state is not LifecycleState.DELETED])
        for memory_id in before:
            memory = self.state.memories.get(memory_id)
            old = before[memory_id]
            if memory is None:  # removed from the table: nothing to serve
                self._unindex(memory_id)
                continue
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
        # A rolled-back write left its memory in the indexes. Unindexed here,
        # or the copy index goes on "recognising" a memory the log never
        # committed and the next similar write looks it up and fails
        # (found by concurrent branch commits, tests/test_branching.py).
        for memory_id in set(self.chain_terms) - set(self.state.memories):
            self._unindex(memory_id)
            self.copy_index.remove(memory_id)
        warm = None if self.index.lazy else getattr(self.index.embedder, "warm", None)
        if warm is not None:
            # One batched pass for a trained embedder instead of a model
            # call per memory on every open.
            warm([self._index_text(m) for m in self.state.memories.values()
                  if m.lifecycle_state is not LifecycleState.DELETED])
        for memory in self.state.memories.values():
            if memory.lifecycle_state is not LifecycleState.DELETED:
                self._index(memory.id, self._index_text(memory))
        # Read before the rebuild: an event appended during it is picked up by
        # the next `refresh` rather than counted as seen and never folded.
        self._seen_seq = head
        self._estimator_dirty = True

    def _contest(self, memory_ids: list[str], reason: str, actor: str) -> None:
        """Contest stale restatements of a corrected or withdrawn fact (validation.restatements)."""
        for mid in memory_ids:
            if self.state.memories[mid].lifecycle_state is LifecycleState.ACTIVE:
                self._emit(self._transition(mid, LifecycleState.CONTESTED, reason, actor))

    def _require(self, memory_id: str) -> Memory:
        memory = self.state.memories.get(memory_id)
        if memory is None:
            raise NotFound(f"no memory {memory_id!r}")
        return memory

    def _refresh_estimator(self) -> None:
        if self._estimator_dirty:
            self.estimator.fit(self.state)
            self._estimator_dirty = False

    # --- identity --------------------------------------------------------

    @property
    def principals(self) -> PrincipalRegistry:
        """Who this store will act as. The authorisation boundary for agents,
        the way `PeerRegistry` is for stores."""
        if self._principals is None:
            self._principals = PrincipalRegistry()
        return self._principals

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

    def rebuild(self) -> None:
        """Throw away all derived state and rebuild it from the log."""
        self._replay()

    def close(self) -> None:
        self.log.close()
