"""Privacy-aware federation (plan Task 11).

Authorisation is traced through write, retrieval, summary and disclosure.
Acceptance: unauthorised content is not exposed directly or through a summary,
and a refusal does not confirm that a record exists unless policy permits it.

Found while writing this file: `derive` wrote every conclusion at the default
security class, so a summary of a `restricted` memory came out `internal` and
could be shared. It now inherits the strictest class of its premises.
"""

from __future__ import annotations

import json
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.enforcement import RiskLevel
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (
    Firewall,
    FirewallDecision,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)
from memory_fabric.model import Scope, SecurityClass

PRICE = "Acme renewal price is 1.2M, agreed on the call"


def permissive() -> Firewall:
    """Without the value rule, so a refusal can only be the privacy rules."""
    return Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                           rule_capabilities_must_be_granted))


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.origin = MemoryFabric(auto_activate=True, firewall=permissive())
        self.recipient = MemoryFabric(auto_activate=True, firewall=permissive())
        self.addCleanup(self.origin.close)
        self.addCleanup(self.recipient.close)
        self.restricted = self.origin.remember("ag", PRICE, security_class="restricted")


class TestDerivedContent(Fixture):
    def test_a_summary_inherits_the_strictest_class(self) -> None:
        summary = self.origin.derive("ag", "Acme summary: price 1.2M", parents=[self.restricted], scope="team")
        self.assertIs(self.origin.get(summary).security_class, SecurityClass.RESTRICTED)

    def test_a_caller_cannot_lower_the_class_of_a_summary(self) -> None:
        summary = self.origin.derive("ag", "Acme summary", parents=[self.restricted],
                                     security_class="public", scope="team")
        self.assertIs(self.origin.get(summary).security_class, SecurityClass.RESTRICTED)

    def test_a_caller_can_raise_it(self) -> None:
        open_fact = self.origin.remember("ag", "yard opens at 6", security_class="public", scope="team")
        summary = self.origin.derive("ag", "yard hours", parents=[open_fact],
                                     security_class="restricted")
        self.assertIs(self.origin.get(summary).security_class, SecurityClass.RESTRICTED)

    def test_ordinary_summaries_keep_the_default(self) -> None:
        fact = self.origin.remember("ag", "yard opens at 6", scope="team")
        summary = self.origin.derive("ag", "yard hours", parents=[fact], scope="team")
        self.assertIs(self.origin.get(summary).security_class, SecurityClass.INTERNAL)

    def test_a_summary_of_restricted_content_cannot_be_shared(self) -> None:
        summary = self.origin.derive("ag", "Acme summary: price 1.2M", parents=[self.restricted], scope="team")
        self.assertIs(self.origin.share(summary, Scope.TEAM).decision, FirewallDecision.DENY)

    def test_a_summary_of_restricted_content_cannot_be_federated(self) -> None:
        summary = self.origin.derive("ag", "Acme summary: price 1.2M", parents=[self.restricted], scope="team")
        result = offer(self.origin, summary, self.recipient, recipient_agent="b")
        self.assertFalse(result.accepted)
        self.assertTrue(any("restricted" in r for r in result.reasons), result.reasons)
        # Metadata before content: nothing of the refused memory arrived.
        dump = json.dumps([e.payload for e in self.recipient.log.read()], default=str)
        self.assertNotIn("1.2M", dump)


class TestDisclosureOfExistence(unittest.TestCase):
    def make(self, conceal: bool) -> tuple[MemoryFabric, str]:
        fabric = MemoryFabric(auto_activate=True, conceal_cross_tenant=conceal)
        self.addCleanup(fabric.close)
        return fabric, fabric.remember("ag", "tenant A fact", tenant_id="tn_a", scope="team")

    def decision_shape(self, decision) -> tuple:
        return (decision.verdict, decision.reason_code, decision.version,
                decision.detail, decision.lifecycle_state)

    def test_by_default_a_cross_tenant_refusal_is_documented_as_wrong_tenant(self) -> None:
        """The existing policy, pinned: it confirms the id exists elsewhere and
        says nothing else. docs/SAFETY_AND_SECURITY.md records the choice."""
        fabric, mid = self.make(conceal=False)
        decision = fabric.use(mid, agent_id="b", tenant_id="tn_b").decision
        self.assertEqual(decision.reason_code, "wrong_tenant")

    def test_concealed_a_cross_tenant_refusal_is_identical_to_a_missing_id(self) -> None:
        fabric, mid = self.make(conceal=True)
        theirs = fabric.use(mid, agent_id="b", tenant_id="tn_b").decision
        missing = fabric.use("01NOTAREALMEMORYID00000000", agent_id="b",
                             tenant_id="tn_b").decision
        self.assertEqual(self.decision_shape(theirs), self.decision_shape(missing))

    def test_concealed_the_owning_tenant_still_reads_it(self) -> None:
        fabric, mid = self.make(conceal=True)
        self.assertTrue(fabric.use(mid, agent_id="a", tenant_id="tn_a",
                                   risk=RiskLevel.HIGH).usable)

    def test_concealed_a_certificate_names_it_as_missing(self) -> None:
        fabric, mid = self.make(conceal=True)
        theirs = fabric.verify_certificate(
            fabric.certify("c", [mid], "b", tenant_id="tn_b"), "b", tenant_id="tn_b")
        missing = fabric.verify_certificate(
            fabric.certify("c", ["01NOTAREALMEMORYID00000000"], "b", tenant_id="tn_b"),
            "b", tenant_id="tn_b")
        self.assertEqual(theirs.reason_codes, missing.reason_codes)


if __name__ == "__main__":
    unittest.main()
