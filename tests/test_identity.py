"""Tenant and agent identity.

Two things are being tested and they are not the same claim.

**Isolation** is a property of the store: no path that returns a memory may
return one belonging to another tenant. That is testable and the tests here are
the real assurance — one per path, because the paths are where this breaks.

**Authentication** is a property of a *boundary*, and the boundary is the
handle rather than the store. A caller holding a `MemoryFabric` can act as
anyone; nothing in this file pretends otherwise, and
`test_the_raw_fabric_is_still_unauthenticated` pins that honestly rather than
leaving a reader to assume a perimeter that does not exist.

The distinction matters for what the product can claim. Isolation holds against
bugs — a ranking policy, an index query, a federation import. Neither holds
against a caller with the file.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.enforcement import WRONG_TENANT, RiskLevel, Verdict
from memory_fabric.federation import offer
from memory_fabric.identity import (
    DEFAULT_TENANT,
    ROLE_AGENT,
    ROLE_OPERATOR,
    Credential,
    IdentityError,
    Principal,
    PrincipalRegistry,
)
from memory_fabric.model import MemoryType


class CredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = PrincipalRegistry()
        self.registry.register("agent-acme", key=b"k-acme", tenant_id="tn_acme")
        self.registry.register(
            "root", key=b"k-root", tenant_id="tn_acme",
            roles=(ROLE_AGENT, ROLE_OPERATOR),
        )

    def test_a_credential_round_trips_and_verifies(self) -> None:
        issued = self.registry.issue("agent-acme", now=1_000)
        restored = Credential.from_json(json.loads(json.dumps(issued.to_json())))
        principal = self.registry.verify(restored, now=1_500)
        self.assertEqual(principal.agent_id, "agent-acme")
        self.assertEqual(principal.tenant_id, "tn_acme")

    def test_an_unsigned_credential_does_not_verify(self) -> None:
        issued = self.registry.issue("agent-acme", now=1_000)
        with self.assertRaises(IdentityError):
            self.registry.verify(replace(issued, signature=""), now=1_500)

    def test_a_tampered_body_does_not_verify(self) -> None:
        """Changing the tenant is the attack the signature exists to stop."""
        issued = self.registry.issue("agent-acme", now=1_000)
        forged = replace(issued, tenant_id="tn_globex")
        with self.assertRaises(IdentityError) as caught:
            self.registry.verify(forged, now=1_500)
        self.assertIn("signature", str(caught.exception))

    def test_a_credential_resigned_with_the_wrong_key_does_not_verify(self) -> None:
        issued = self.registry.issue("agent-acme", now=1_000)
        forged = replace(issued, tenant_id="tn_globex").sign(b"k-attacker")
        with self.assertRaises(IdentityError):
            self.registry.verify(forged, now=1_500)

    def test_an_expired_credential_does_not_verify(self) -> None:
        issued = self.registry.issue("agent-acme", now=1_000, ttl_seconds=10)
        self.registry.verify(issued, now=1_005)  # still inside the window
        with self.assertRaises(IdentityError) as caught:
            self.registry.verify(issued, now=1_010)
        self.assertIn("expired", str(caught.exception))

    def test_the_signature_is_checked_before_the_expiry(self) -> None:
        """An expiry check on an unverified body is a check on attacker data.

        Asserted through the error message, which is the only way the order is
        observable — and the order is the point, so it is worth observing.
        """
        issued = self.registry.issue("agent-acme", now=1_000, ttl_seconds=1)
        forged = replace(issued, signature="00" * 32)
        with self.assertRaises(IdentityError) as caught:
            self.registry.verify(forged, now=9_999_999)
        self.assertIn("signature", str(caught.exception))

    def test_an_unknown_agent_is_refused(self) -> None:
        with self.assertRaises(IdentityError):
            self.registry.issue("nobody", now=1_000)
        stolen = self.registry.issue("agent-acme", now=1_000)
        with self.assertRaises(IdentityError):
            self.registry.verify(replace(stolen, agent_id="nobody"), now=1_001)

    def test_a_credential_can_narrow_but_not_widen_a_registration(self) -> None:
        narrowed = self.registry.issue("root", now=1_000, roles=(ROLE_AGENT,))
        self.assertEqual(
            self.registry.verify(narrowed, now=1_001).roles, frozenset({ROLE_AGENT})
        )
        with self.assertRaises(IdentityError) as caught:
            self.registry.issue("agent-acme", now=1_000, roles=(ROLE_OPERATOR,))
        self.assertIn("narrow", str(caught.exception))

    def test_a_registration_moving_tenant_invalidates_old_credentials(self) -> None:
        """Authentic but wrong: the registration wins, not the signature."""
        issued = self.registry.issue("agent-acme", now=1_000)
        self.registry.register("agent-acme", key=b"k-acme", tenant_id="tn_moved")
        with self.assertRaises(IdentityError) as caught:
            self.registry.verify(issued, now=1_001)
        self.assertIn("tn_moved", str(caught.exception))

    def test_a_registration_needs_a_key(self) -> None:
        with self.assertRaises(IdentityError):
            self.registry.register("keyless", key=b"")


class TenantIsolationTests(unittest.TestCase):
    """One test per path that can return a memory."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "shared.db"
        self.fabric = MemoryFabric(self.path, auto_activate=True)
        self.fabric.principals.register(
            "agent-acme", key=b"k-acme", tenant_id="tn_acme"
        )
        self.fabric.principals.register(
            "agent-globex", key=b"k-globex", tenant_id="tn_globex"
        )
        self.acme = self.fabric.as_principal(
            self.fabric.principals.issue("agent-acme", now=self.fabric.now())
        )
        self.globex = self.fabric.as_principal(
            self.fabric.principals.issue("agent-globex", now=self.fabric.now())
        )
        self.acme_memory = self.acme.remember("valve 7 is upstream of the pump")

    def tearDown(self) -> None:
        self.fabric.close()
        self._tmp.cleanup()

    def test_retrieval_does_not_cross(self) -> None:
        self.assertEqual(len(self.acme.retrieve("valve").exposed), 1)
        other = self.globex.retrieve("valve")
        self.assertEqual(other.exposed, [])
        # Withheld too, not just unexposed: a memory excluded before the index
        # is queried cannot appear in either list, or in the retrieval event.
        self.assertEqual(other.withheld, [])

    def test_the_enforced_read_does_not_cross(self) -> None:
        read = self.globex.use(self.acme_memory)
        self.assertIs(read.decision.verdict, Verdict.DENY)
        self.assertEqual(read.decision.reason_code, WRONG_TENANT)
        self.assertIsNone(read.memory)

    def test_the_refusal_leaks_nothing_about_the_memory(self) -> None:
        """A reason code naming the owning tenant would be an enumeration oracle.

        The refusal says "not yours" and nothing else — not the version, not
        the lifecycle state, not that it was withdrawn on weak evidence, each
        of which is a true statement about another tenant's data.
        """
        self.fabric.quarantine(
            self.acme_memory, reason="in context when it failed",
            actor="operator", basis="co_occurrence",
        )
        decision = self.globex.use(self.acme_memory).decision
        self.assertEqual(decision.reason_code, WRONG_TENANT)
        self.assertEqual(decision.version, 0)
        self.assertEqual(decision.detail, "")
        # The owning tenant does get the informative reason.
        own = self.acme.use(self.acme_memory).decision
        self.assertNotEqual(own.reason_code, WRONG_TENANT)

    def test_an_action_token_cannot_be_replayed_across_a_tenant(self) -> None:
        """The time-of-use check is scoped the same way the time-of-check was.

        A token is already bound to an agent, so this is belt and braces — but
        the whole point of `verify_at_action` is that the second check is not
        weaker than the first, and an unscoped re-check would have been.
        """
        read = self.acme.use(self.acme_memory, risk=RiskLevel.LOW)
        self.assertIsNotNone(read.token)
        self.assertEqual(read.token.tenant_id, "tn_acme")
        decision = self.fabric.verify_before_action(
            read.token, agent_id="agent-acme", risk=RiskLevel.HIGH
        )
        self.assertNotEqual(decision.reason_code, WRONG_TENANT)

        smuggled = replace(read.token, tenant_id="tn_globex", agent_id="agent-globex")
        self.assertEqual(
            self.fabric.verify_before_action(
                smuggled, agent_id="agent-globex", risk=RiskLevel.HIGH
            ).reason_code,
            WRONG_TENANT,
        )

    def test_a_conclusion_cannot_be_justified_across_a_tenant(self) -> None:
        """`derive` copies its parents' context, federation origin and all.

        A conclusion drawn from another tenant's premise would be labelled with
        this tenant and justified by a memory nobody here may read — and then a
        retraction at the premise would recompute support for a conclusion in a
        tenant that never saw it.
        """
        with self.assertRaises(IdentityError):
            self.globex.derive("therefore the pump is at fault", parents=[self.acme_memory])
        # And within a tenant it still works.
        mine = self.globex.remember("the east gate closes at 1800")
        derived = self.globex.derive("so deliveries must arrive by 1730", parents=[mine])
        self.assertEqual(self.fabric.tenant_of(derived), "tn_globex")

    def test_the_inventory_is_scoped(self) -> None:
        self.globex.remember("the east gate closes at 1800")
        self.assertEqual(self.acme.memory_ids(), [self.acme_memory])
        self.assertNotIn(self.acme_memory, self.globex.memory_ids())
        self.assertEqual(self.fabric.tenants(), {"tn_acme": 1, "tn_globex": 1})

    def test_isolation_survives_a_rebuild(self) -> None:
        """The tenant is a projection of the log, not a runtime label."""
        self.fabric.close()
        reopened = MemoryFabric(self.path, auto_activate=True)
        try:
            self.assertEqual(reopened.tenant_of(self.acme_memory), "tn_acme")
            self.assertEqual(reopened.tenants(), {"tn_acme": 1})
        finally:
            reopened.close()

    def test_the_raw_fabric_is_still_unauthenticated(self) -> None:
        """Recorded, not fixed.

        A caller holding the fabric can write into any tenant as any agent.
        That is not a bug to be patched inside the object — the check and the
        bypass would be on the same side of the boundary — and SECURITY.md says
        so. What the handle buys is that code written against a view cannot
        *forget* to scope a read.
        """
        smuggled = self.fabric.remember(
            agent_id="agent-acme",
            content="planted",
            type=MemoryType.SEMANTIC,
            tenant_id="tn_globex",
        )
        self.assertEqual(self.fabric.tenant_of(smuggled), "tn_globex")
        self.assertFalse(self.fabric.for_tenant("tn_globex", "x").verified)

    def test_an_unverifiable_credential_raises_rather_than_scoping_to_nothing(self) -> None:
        """An empty view would read as "this tenant has no memories"."""
        stale = self.fabric.principals.issue(
            "agent-acme", now=self.fabric.now(), ttl_seconds=1
        )
        expired = replace(stale, expires_at=0)
        with self.assertRaises(IdentityError):
            self.fabric.as_principal(expired)


def _permissive():
    from memory_fabric.governance.firewall import (
        Firewall,
        rule_capabilities_must_be_granted,
        rule_must_be_active,
        rule_restricted_stays_private,
    )

    return Firewall(
        rules=[
            rule_must_be_active,
            rule_restricted_stays_private,
            rule_capabilities_must_be_granted,
        ]
    )


class FederationTenancyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        # The default firewall's value gate refuses an unevaluated memory, and
        # Phase B measured that gate down to 42 imports of a possible 630 — so
        # leaving it on here would mostly be testing the gate.
        self.source = MemoryFabric(
            self.dir / "a.db", auto_activate=True, firewall=_permissive()
        )
        self.target = MemoryFabric(
            self.dir / "b.db", auto_activate=True, firewall=_permissive()
        )

    def tearDown(self) -> None:
        self.source.close()
        self.target.close()
        self._tmp.cleanup()

    def test_an_import_lands_in_the_tenant_the_recipient_names(self) -> None:
        """A tenant id is local to a store.

        Nothing in the protocol makes `tn_acme` at one store the same customer
        as `tn_acme` at another, so the recipient names the tenant rather than
        inheriting a string that happens to match.
        """
        origin = self.source.remember(
            agent_id="a", content="valve 7 is upstream of the pump",
            type=MemoryType.SEMANTIC, tenant_id="tn_acme",
        )
        result = offer(
            self.source, origin, self.target, "b",
            activate=True, tenant_id="tn_customer_7",
        )
        self.assertTrue(result.accepted, result.reasons)
        self.assertEqual(
            self.target.tenant_of(result.imported_memory_id), "tn_customer_7"
        )

    def test_without_a_tenant_an_import_keeps_the_senders_label(self) -> None:
        """Which is right for a single-tenant federation and the only thing it
        can be: the recipient has no other information to go on."""
        origin = self.source.remember(
            agent_id="a", content="valve 7 is upstream of the pump",
            type=MemoryType.SEMANTIC,
        )
        result = offer(self.source, origin, self.target, "b", activate=True)
        self.assertEqual(
            self.target.tenant_of(result.imported_memory_id), DEFAULT_TENANT
        )


class LegacyStoreTests(unittest.TestCase):
    def test_a_store_written_before_tenancy_replays_into_the_default(self) -> None:
        """Simulated by stripping the field from the payload, which is exactly
        what an older writer produced."""
        from memory_fabric.model import Memory

        payload = {
            "id": "01OLD",
            "version": 1,
            "type": "semantic",
            "content": "x",
            "provenance": {"created_by": "a", "method": "observed"},
        }
        self.assertEqual(Memory.from_json(payload).tenant_id, DEFAULT_TENANT)
        self.assertNotIn("tenant_id", payload)

    def test_the_default_tenant_is_a_real_id_not_none(self) -> None:
        """A nullable boundary is one every comparison has to remember to
        handle, and the first place that forgot would be a cross-tenant read."""
        self.assertIsInstance(DEFAULT_TENANT, str)
        self.assertTrue(DEFAULT_TENANT)
        self.assertEqual(Principal(agent_id="a").tenant_id, DEFAULT_TENANT)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
