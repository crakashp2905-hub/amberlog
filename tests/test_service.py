"""The service trust boundary: escalation, revocation, and what it cannot do.

`MemoryFabric` trusts its caller completely and has to, because inside a
library the check and the bypass sit on the same side. `MemoryService` is where
that stops being true for application code: it owns the fabric, does not expose
it, and hands out only handles derived from a verified credential.

These tests are mostly attacks. Each one is an escalation an application bug or
a compromised adapter would attempt, and the assertion is that the service
refuses. The last group is the honest part: what this boundary does *not* do,
pinned so nobody reads the rest as a sandbox.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import MemoryFabric
from memory_fabric.enforcement import RiskLevel, Verdict
from memory_fabric.identity import (
    ROLE_AGENT,
    ROLE_AUDITOR,
    ROLE_OPERATOR,
    IdentityError,
)
from memory_fabric.service import MemoryService, Session


class ServiceCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.service = MemoryService(
            MemoryFabric(Path(self._tmp.name) / "store.db", auto_activate=True)
        )
        self.addCleanup(self.service.close)

        self.service.register_agent("acme-bot", key=b"k-acme", tenant_id="tn_acme")
        self.service.register_agent("globex-bot", key=b"k-globex", tenant_id="tn_globex")
        self.service.register_agent(
            "acme-ops", key=b"k-ops", tenant_id="tn_acme",
            roles=(ROLE_AGENT, ROLE_OPERATOR),
        )

        self.acme = self.service.session(self.service.issue("acme-bot"))
        self.globex = self.service.session(self.service.issue("globex-bot"))
        self.ops = self.service.session(self.service.issue("acme-ops"))
        self.memory_id = self.acme.remember("valve 7 is upstream of the pump")


class TheHappyPath(ServiceCase):
    def test_a_session_can_write_and_read_its_own_tenant(self) -> None:
        self.assertEqual(len(self.acme.retrieve("valve").exposed), 1)
        read = self.acme.use(self.memory_id)
        self.assertIs(read.decision.verdict, Verdict.USABLE)
        self.assertIn("valve 7", read.memory.content)

    def test_an_operator_can_read_a_withdrawn_memory(self) -> None:
        """The reason the operator role exists: judging a withdrawal means
        reading what was withdrawn."""
        self.ops.quarantine(self.memory_id, reason="contradicted", basis="contradicted")
        self.assertIn("valve 7", self.ops.inspect(self.memory_id).content)
        # And the agent path still refuses it.
        self.assertFalse(self.acme.use(self.memory_id).usable)


class Escalation(ServiceCase):
    def test_an_agent_cannot_use_operator_operations(self) -> None:
        for label, call in (
            ("quarantine", lambda: self.acme.quarantine(self.memory_id, reason="x")),
            ("release", lambda: self.acme.release(self.memory_id)),
            ("validate", lambda: self.acme.validate(self.memory_id)),
            ("inspect", lambda: self.acme.inspect(self.memory_id)),
            ("explain", lambda: self.acme.explain(self.memory_id)),
            ("erase", lambda: self.acme.erase_content(self.memory_id, reason="x")),
            (
                "retract",
                lambda: self.acme.request_retraction(
                    self.memory_id, reason="x", recipients=[]
                ),
            ),
        ):
            with self.subTest(label):
                with self.assertRaises(IdentityError):
                    call()

    def test_an_agent_cannot_forge_a_role_into_its_credential(self) -> None:
        forged = replace(
            self.acme.credential, roles=(ROLE_AGENT, ROLE_OPERATOR)
        )
        with self.assertRaises(IdentityError):
            self.service.session(forged)

    def test_the_registry_refuses_to_issue_a_role_it_does_not_hold(self) -> None:
        """Widening at issue time would make the issuer the authority rather
        than the registry, and then anything able to ask for a credential could
        ask for an operator's."""
        with self.assertRaises(IdentityError):
            self.service.issue("acme-bot", roles=(ROLE_OPERATOR,))
        # Narrowing is fine.
        narrowed = self.service.issue("acme-ops", roles=(ROLE_AGENT,))
        session = self.service.session(narrowed)
        with self.assertRaises(IdentityError):
            session.inspect(self.memory_id)

    def test_an_agent_cannot_reach_another_tenant(self) -> None:
        self.assertEqual(self.globex.retrieve("valve").exposed, [])
        self.assertFalse(self.globex.use(self.memory_id).usable)
        self.assertNotIn(self.memory_id, self.globex.memory_ids())

    def test_an_operator_cannot_reach_another_tenant(self) -> None:
        """"May see withdrawn memories" must not become "may see every
        tenant's memories" — these are the paths that deliberately bypass the
        enforcement layer, so the tenant check has to be on them directly."""
        self.service.register_agent(
            "globex-ops", key=b"k-gops", tenant_id="tn_globex",
            roles=(ROLE_AGENT, ROLE_OPERATOR),
        )
        other_ops = self.service.session(self.service.issue("globex-ops"))
        for label, call in (
            ("inspect", lambda: other_ops.inspect(self.memory_id)),
            ("explain", lambda: other_ops.explain(self.memory_id)),
            ("quarantine", lambda: other_ops.quarantine(self.memory_id, reason="x")),
            ("erase", lambda: other_ops.erase_content(self.memory_id, reason="x")),
        ):
            with self.subTest(label):
                with self.assertRaises(IdentityError):
                    call()

    def test_a_cross_tenant_refusal_does_not_name_the_owning_tenant(self) -> None:
        """Otherwise the check is an enumeration oracle."""
        self.service.register_agent(
            "globex-ops", key=b"k-gops", tenant_id="tn_globex",
            roles=(ROLE_AGENT, ROLE_OPERATOR),
        )
        other_ops = self.service.session(self.service.issue("globex-ops"))
        with self.assertRaises(IdentityError) as caught:
            other_ops.inspect(self.memory_id)
        self.assertNotIn("tn_acme", str(caught.exception))

    def test_a_session_cannot_mint_credentials(self) -> None:
        """Registering agents and issuing credentials *create* privilege, so
        they belong to whatever bootstraps the service. A session that could
        issue credentials could issue itself a better one."""
        for forbidden in ("issue", "register_agent", "revoke", "revoke_agent"):
            with self.subTest(forbidden):
                self.assertFalse(
                    hasattr(self.acme, forbidden),
                    f"Session should not expose {forbidden}",
                )

    def test_a_session_exposes_no_route_to_the_raw_fabric(self) -> None:
        """An API boundary, not a sandbox — see `TheBoundaryIsNotASandbox`.

        What this asserts is that no *public* attribute hands the fabric over,
        so reaching it is visibly deliberate rather than a plausible accident.
        """
        public = [
            name
            for name in dir(self.acme)
            if not name.startswith("_") and isinstance(getattr(self.acme, name, None), MemoryFabric)
        ]
        self.assertEqual(public, [])

    def test_an_agent_cannot_record_its_own_outcome(self) -> None:
        episode = self.acme.start_episode("task-1")
        with self.assertRaises(Exception) as caught:
            self.acme.record_outcome(episode.id, outcome=1.0, verifier_id="acme-bot")
        self.assertNotIsInstance(caught.exception, AssertionError)


class Revocation(ServiceCase):
    def test_a_revoked_credential_stops_working_immediately(self) -> None:
        """The reason a `Session` holds a credential rather than a principal.

        `as_principal` verifies once and returns a view that keeps working, so
        a credential revoked at 10:00 would still be acting at 11:00 through a
        view minted at 09:00 — revocation that does not revoke.
        """
        self.assertEqual(len(self.acme.retrieve("valve").exposed), 1)
        self.service.revoke(self.acme.credential)
        for label, call in (
            ("retrieve", lambda: self.acme.retrieve("valve")),
            ("remember", lambda: self.acme.remember("anything")),
            ("use", lambda: self.acme.use(self.memory_id)),
            ("principal", self.acme.principal),
        ):
            with self.subTest(label):
                with self.assertRaises(IdentityError):
                    call()

    def test_revoking_one_credential_leaves_the_others_working(self) -> None:
        """Without per-credential ids the only remedy was rotating the agent's
        key, which takes the whole agent offline to deal with one leaked
        token."""
        second = self.service.session(self.service.issue("acme-bot"))
        self.service.revoke(self.acme.credential)
        with self.assertRaises(IdentityError):
            self.acme.principal()
        self.assertEqual(second.principal().agent_id, "acme-bot")

    def test_revoking_is_idempotent_and_reports_whether_it_was_new(self) -> None:
        self.assertTrue(self.service.revoke(self.acme.credential))
        self.assertFalse(self.service.revoke(self.acme.credential))

    def test_revoking_an_agent_stops_every_credential_including_future_ones(self) -> None:
        second = self.service.session(self.service.issue("acme-bot"))
        self.service.revoke_agent("acme-bot")
        for label, session in (("first", self.acme), ("second", second)):
            with self.subTest(label):
                with self.assertRaises(IdentityError):
                    session.principal()
        # A credential issued *after* the revocation is refused too, which is
        # what makes this the right tool for a compromised agent.
        fresh = self.service.issue("acme-bot")
        with self.assertRaises(IdentityError):
            self.service.session(fresh)

    def test_a_revoked_agent_can_be_reinstated_deliberately(self) -> None:
        self.service.revoke_agent("acme-bot")
        self.service.principals.reinstate_agent("acme-bot")
        self.assertEqual(self.acme.principal().agent_id, "acme-bot")

    def test_a_credential_lasts_its_lifetime_in_seconds(self) -> None:
        """Through the real path: the store's millisecond clock. Credentials
        used to expire 1000x early, which only a slow caller exposed."""
        now = [1_800_000_000_000]
        service = MemoryService(MemoryFabric(":memory:", clock=lambda: now[0]))
        self.addCleanup(service.close)
        service.register_agent("slow-bot", key=b"k-slow", tenant_id="tn_acme")
        session = service.session(service.issue("slow-bot", ttl_seconds=60))
        now[0] += 30_000  # thirty seconds of thinking
        session.remember("still allowed after thirty seconds")
        now[0] += 31_000
        with self.assertRaises(IdentityError):
            session.remember("refused after sixty-one seconds")

    def test_an_expired_credential_stops_working(self) -> None:
        expired = replace(self.acme.credential, expires_at=0)
        with self.assertRaises(IdentityError):
            self.service.session(expired)

    def test_a_credential_with_no_id_cannot_be_revoked_individually(self) -> None:
        """An honest refusal rather than a silent no-op. A credential from
        before ids existed can only be dealt with by rotating the key, and
        pretending otherwise would report a revocation that did nothing."""
        legacy = replace(self.acme.credential, credential_id="")
        with self.assertRaises(IdentityError):
            self.service.revoke(legacy)

    def test_revocation_is_checked_after_the_signature(self) -> None:
        """A revocation lookup on an unverified id is a lookup on
        attacker-controlled data."""
        self.service.revoke(self.acme.credential)
        tampered = replace(self.acme.credential, signature="00" * 32)
        with self.assertRaises(IdentityError) as caught:
            self.service.session(tampered)
        self.assertIn("signature", str(caught.exception))


class TheBoundaryIsNotASandbox(ServiceCase):
    """What this does not do, pinned so the rest is not over-read."""

    def test_the_fabric_is_reachable_by_anyone_who_insists(self) -> None:
        """Python has no private attributes. The boundary makes the safe path
        the obvious one; it does not make the unsafe one impossible.

        Asserted rather than apologised for, because a reader who assumes
        otherwise would deploy this as an isolation mechanism.
        """
        fabric = self.service._fabric
        planted = fabric.remember(
            agent_id="anyone", content="planted", tenant_id="tn_globex"
        )
        self.assertEqual(fabric.tenant_of(planted), "tn_globex")

    def test_revocation_survives_a_restart(self) -> None:
        """It did not, and that was the wrong default for a service.

        A `MemoryService` is the thing that restarts, and an in-memory list
        un-revokes every leaked credential still inside its lifetime at exactly
        the moment revocation exists for. The service now keeps revocations on
        disk by default, sharing the event log's connection.
        """
        self.assertTrue(self.service.revocations_are_durable)
        self.service.revoke(self.acme.credential)
        credential = self.acme.credential
        self.service.revoke_agent("globex-bot")
        self.service.close()

        reopened = MemoryService(
            MemoryFabric(Path(self._tmp.name) / "store.db", auto_activate=True)
        )
        self.addCleanup(reopened.close)
        reopened.register_agent("acme-bot", key=b"k-acme", tenant_id="tn_acme")
        reopened.register_agent("globex-bot", key=b"k-globex", tenant_id="tn_globex")

        with self.assertRaises(IdentityError):
            reopened.session(credential)
        # The agent-level revocation survives too, including for a credential
        # minted after the restart.
        with self.assertRaises(IdentityError):
            reopened.session(reopened.issue("globex-bot"))
        # And an unrevoked agent is unaffected.
        self.assertEqual(
            reopened.session(reopened.issue("acme-bot")).agent_id, "acme-bot"
        )

    def test_a_bare_registry_still_keeps_revocations_in_memory(self) -> None:
        """The library primitive keeps the cheap default; the *service* is
        where durability is the right call. A one-process tool should not be
        made to write a table it will never read again."""
        from memory_fabric.identity import PrincipalRegistry

        bare = PrincipalRegistry()
        self.assertFalse(bare.revocations.durable)

    def test_durability_can_be_turned_off_deliberately(self) -> None:
        plain = MemoryService(
            MemoryFabric(":memory:"), durable_revocations=False
        )
        self.addCleanup(plain.close)
        self.assertFalse(plain.revocations_are_durable)

    def test_a_credential_is_a_bearer_token(self) -> None:
        """Holding it is sufficient; it is not bound to a channel or a client.
        That is why lifetimes are short and why revocation exists."""
        stolen = self.service.session(self.acme.credential)
        self.assertEqual(stolen.principal().agent_id, "acme-bot")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
