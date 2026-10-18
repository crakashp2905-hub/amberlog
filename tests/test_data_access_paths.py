"""Every public way to get at a memory, classified — and the classification enforced.

`MemoryFabric` has fifty public members. Three of them return memory content:
`get`, `use` and `retrieve`. Only two of those are safe for an agent, and the
unsafe one is the shortest to type.

The risk is specific rather than theoretical. `get()` returns a withdrawn
memory, because an operator judging whether a withdrawal was justified has to
read what was withdrawn. An adapter holding that method is one autocomplete
away from serving retracted knowledge to a model, and it would look exactly
like working code.

So this file does two things:

* **classifies the whole public surface** into enforced reads, content-free metadata, operator inspection, mutation and plumbing, with a test that fails when a new member appears unclassified — because a document listing the surface drifts the moment someone adds a method, and a test does not;
* **asserts the agent-facing surfaces have no route to the unenforced read**, structurally, so the separation cannot erode by convenience import.

The classification itself is the deliverable. `docs/DATA_ACCESS.md` is generated
from the same table.
"""

from __future__ import annotations

import inspect
import re
import unittest

_UNENFORCED_READ = re.compile(
    r"(fabric|depot|workshop|store|origin|recipient)\.get\("
)
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.enforcement import RiskLevel, Verdict

# --- the classification ----------------------------------------------------
#
# ENFORCED   — returns content, through the enforcement layer. Safe for agents.
# INSPECTION — reads, bypassing enforcement. Operators only.
# MUTATION   — changes state.
# METADATA   — reads *about* memories without returning their content. The
#              category the first version of this file was missing, which is
#              how `lifecycle_of` ended up wanting to be "inspection".
# PLUMBING   — lifecycle of the store object itself.

ENFORCED = {
    "retrieve": "filters on lifecycle and tenant before the index is consulted",
    "reconstruct": (
        "a connected chain of evidence; narrows through the same chokepoint as "
        "`retrieve` BEFORE the search runs, so a retracted memory, a contested "
        "descendant of one, a wrong tenant and an expired validity interval are "
        "never nodes in the graph. Filtering a chain afterwards would put the "
        "boundary downstream of a search"
    ),
    "use": "the single enforced read; returns no memory when the decision refuses",
    "verify_before_action": "re-checks a token immediately before a consequential act",
}

METADATA = {
    "lifecycle_of": "one memory's state, and no content — the safe way to ask",
    "relations_of": (
        "the memories one memory stands in a typed relation to, and no "
        "content. Ids only, like `source_root` and `shared_with`"
    ),
    "tenant_of": "which tenant owns a memory",
    "source_root": "the earliest observation a memory traces to",
    "shared_with": "which stores hold a copy",
    "erasure_status": "whether content was erased, and why",
    "erasure_scope": "what an erasure reached, kept, and could not reach",
    "stats": "exposure counters",
    "value": "a value estimate",
    "tenants": "tenant inventory with counts",
    "certify": (
        "records evidence ids, versions, premises and source roots; no "
        "content. Tenant-scoped: another tenant's id is recorded as if missing"
    ),
    "verify_certificate": (
        "re-checks every piece of evidence through the enforcer; reason codes "
        "and ids, never content"
    ),
}

INSPECTION = {
    "get": "RETURNS WITHDRAWN CONTENT. Operator tooling only — never an adapter",
    "explain": "narrative over one memory, including why it was withdrawn",
    "history": "every version of a memory",
    "audit_trail": "the events touching a memory",
    "lineage": "one memory's derivation view",
    "lineage_graph": "the whole derivation graph",
    "state": "the raw projection",
    "firewall_check": "what the firewall would decide, without acting",
    "integrity_snapshot": "pending retractions and a checksum over them",
    "retractions_since": "what this store has issued, for reconciliation",
    "health": "store health report",
    "justifications": "the support graph",
    "enforcer": "the enforcement layer itself",
    "principals": "the agent registry",
    "store_id": "this store's identity",
    "collections": "collection members and grants; ids and agent names, no content",
}

MUTATION = {
    "remember": "write a new memory",
    "index_extraction": (
        "record the structure extracted from a memory's content. A mutation "
        "because it populates an index; deliberately not on the write path, "
        "since extraction is a model call per memory"
    ),
    "relate": (
        "declare a typed non-derivation relation between two memories. A "
        "mutation because it appends an event the relation index projects from"
    ),
    "derive": "write a memory with recorded premises",
    "revise": "new version of an existing memory",
    "validate": "candidate to active",
    "quarantine": "withdraw, recording why",
    "release": "return a quarantined memory to candidate",
    "forget": "deprecate",
    "share": "promote scope, through the firewall",
    "challenge": "open a contradiction",
    "resolve": "close one",
    "cite": "record a self-reported use; never feeds value estimation",
    "record_outcome": "a verified outcome, third-party verifier required",
    "record_share": "record that a memory left for another store",
    "start_episode": "open an episode",
    "end_episode": "close one",
    "sweep_retention": "apply the retention policy",
    "request_retraction": "withdraw locally and owe every recipient, atomically",
    "supersede_copies": "owe holders of an older version's copy a retraction of that version",
    "receive_retraction": "apply one arriving from another store",
    "erase_content": "destroy a content key. Irreversible",
    "rebuild": "replay the projection from the log",
    "collection_add": "put a memory in a collection, widening who reads it; audited",
    "collection_remove": "take one out; audited",
    "collection_grant": "attach an agent to a collection, or grant it more; audited",
    "collection_revoke": "detach an agent, or take permissions back; audited",
}

PLUMBING = {
    "close": "release the database handle",
    "refresh": "fold in other processes' log writes; returns no data",
    "now": "the clock",
    "for_tenant": "a tenant-scoped handle; asserted, not verified",
    "as_principal": "a tenant-scoped handle from a verified credential",
    "session": "an agent session",
}

CLASSIFIED = {**ENFORCED, **METADATA, **INSPECTION, **MUTATION, **PLUMBING}


class TheSurfaceIsFullyClassified(unittest.TestCase):
    def test_every_public_member_is_classified(self) -> None:
        """A document listing the surface drifts the moment someone adds a
        method. This does not."""
        public = {
            name for name in dir(MemoryFabric) if not name.startswith("_")
        }
        unclassified = public - set(CLASSIFIED)
        self.assertEqual(
            unclassified, set(),
            f"new public member(s) need a classification in this file: "
            f"{sorted(unclassified)}",
        )

    def test_nothing_is_classified_that_does_not_exist(self) -> None:
        """The other direction: a stale entry would describe a surface that is
        gone and quietly stop testing anything."""
        public = {name for name in dir(MemoryFabric) if not name.startswith("_")}
        self.assertEqual(set(CLASSIFIED) - public, set())

    def test_a_member_is_in_exactly_one_category(self) -> None:
        counts: dict[str, int] = {}
        for group in (ENFORCED, METADATA, INSPECTION, MUTATION, PLUMBING):
            for name in group:
                counts[name] = counts.get(name, 0) + 1
        self.assertEqual([n for n, c in counts.items() if c > 1], [])

    def test_only_four_members_return_content_through_enforcement(self) -> None:
        """Pinned so a fifth cannot appear without this test being updated and
        read.

        `reconstruct` is the fourth, added 2026-10-12, and updating this
        assertion is the deliberate act the pin exists to force. Two things
        about it are worth stating here rather than in a commit message:

        * It narrows through `_eligible_ids` and `_applicable_at` **before** the
          search runs, so the enforcement is upstream of the code most likely
          to be wrong -- the same argument `retrieve` makes.
        * It returns **less** than `retrieve` does: an `EvidenceChain` carries
          memory ids, reason codes, and the query/link terms a step supplied.
          No `Memory` object and no content. The terms it does expose come only
          from memories the gates already allowed.
        """
        self.assertEqual(
            set(ENFORCED),
            {"retrieve", "reconstruct", "use", "verify_before_action"})


class TheAgentSurfacesCannotReachTheUnenforcedRead(unittest.TestCase):
    """Structural, so the separation cannot erode by convenience."""

    def test_the_agent_client_has_no_get(self) -> None:
        from memory_fabric.sdk import AgentClient

        for forbidden in ("get", "state", "history", "audit_trail", "quarantine"):
            with self.subTest(forbidden):
                self.assertFalse(
                    hasattr(AgentClient, forbidden),
                    f"AgentClient must not expose {forbidden}",
                )

    def test_the_tenant_view_has_no_get(self) -> None:
        from memory_fabric.fabric import TenantView

        for forbidden in ("get", "state", "explain", "erase_content"):
            with self.subTest(forbidden):
                self.assertFalse(hasattr(TenantView, forbidden))

    def test_a_session_reaches_get_only_through_an_operator_role(self) -> None:
        """`Session.inspect` is the one route, and it requires the operator
        role *and* stays inside the session's tenant."""
        from memory_fabric.service import Session

        self.assertTrue(hasattr(Session, "inspect"))
        source = inspect.getsource(Session.inspect)
        self.assertIn("_require_operator", source)
        self.assertIn("_require_tenant", source)

    def test_the_examples_and_adapters_do_not_call_get(self) -> None:
        """The failure this whole classification exists to prevent: shipped
        example code teaching an adapter author to use the unenforced read."""
        root = Path(__file__).resolve().parent.parent
        offenders = []
        for directory in ("examples", "memory_fabric/adapters"):
            path = root / directory
            if not path.exists():
                continue
            for source_file in path.rglob("*.py"):
                text = source_file.read_text(encoding="utf-8")
                for line_number, line in enumerate(text.splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    # Precise: a fabric-like receiver calling `.get(`. The
                    # first version matched any line containing both ".get("
                    # and "fabric", which flagged `state.withdrawal_basis.get(...)`
                    # — an ordinary dict lookup — in every file that mentioned
                    # the word.
                    if _UNENFORCED_READ.search(line):
                        offenders.append(f"{source_file.name}:{line_number} {stripped}")
        self.assertEqual(
            offenders, [],
            "use `use()`/`recall()` for agent reads, `lifecycle_of()` for "
            "metadata, or `operator(fabric, actor).inspect()` when an operator "
            "view really is intended",
        )


class TheEnforcedReadActuallyEnforces(unittest.TestCase):
    """The classification is only worth anything if `use` differs from `get`."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fabric = MemoryFabric(
            Path(self._tmp.name) / "store.db", auto_activate=True
        )
        self.addCleanup(self.fabric.close)
        self.memory_id = self.fabric.remember(
            agent_id="ag", content="valve 7 is upstream of the pump"
        )

    def test_get_returns_a_withdrawn_memory_and_use_does_not(self) -> None:
        self.fabric.quarantine(
            self.memory_id, reason="contradicted", actor="ops", basis="contradicted"
        )
        # Inspection: still readable, deliberately.
        self.assertIn("valve 7", self.fabric.get(self.memory_id).content)
        self.assertIs(
            self.fabric.get(self.memory_id).lifecycle_state,
            LifecycleState.QUARANTINED,
        )
        # Enforced: refused, with no content handed back.
        read = self.fabric.use(self.memory_id, agent_id="ag")
        self.assertIs(read.decision.verdict, Verdict.DENY)
        self.assertIsNone(read.memory)

    def test_retrieve_never_surfaces_a_withdrawn_memory(self) -> None:
        self.fabric.quarantine(
            self.memory_id, reason="contradicted", actor="ops", basis="contradicted"
        )
        result = self.fabric.retrieve(agent_id="ag", query="valve 7 pump")
        self.assertEqual(result.exposed, [])
        self.assertEqual(result.withheld, [])

    def test_a_refused_read_is_audited_without_the_content(self) -> None:
        self.fabric.quarantine(
            self.memory_id, reason="contradicted", actor="ops", basis="contradicted"
        )
        self.fabric.use(self.memory_id, agent_id="ag")
        denials = [
            event
            for event in self.fabric.log.read()
            if event.type == "AccessDenied"
        ]
        self.assertTrue(denials)
        payload = denials[-1].payload
        self.assertNotIn("content", payload)
        self.assertNotIn("valve 7", str(payload))

    def test_the_high_risk_path_is_stricter_than_the_low(self) -> None:
        """A candidate is usable-with-revalidation at low risk and refused at
        high, so the classification's "safe for agents" depends on the risk the
        caller declares."""
        candidate = MemoryFabric(":memory:")
        self.addCleanup(candidate.close)
        memory_id = candidate.remember(agent_id="ag", content="unvalidated claim")
        low = candidate.use(memory_id, agent_id="ag", risk=RiskLevel.LOW)
        high = candidate.use(memory_id, agent_id="ag", risk=RiskLevel.HIGH)
        self.assertIs(low.decision.verdict, Verdict.REVALIDATE)
        self.assertIs(high.decision.verdict, Verdict.DENY)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
