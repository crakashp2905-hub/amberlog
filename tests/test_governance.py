"""Governance: sensitive-data detection, the firewall, and retention."""

from __future__ import annotations

import unittest

from amberlog.governance.firewall import (
    Firewall,
    FirewallRequest,
    strictest,
)
from amberlog.governance.retention import (
    RetentionPolicy,
    expected_value,
    should_keep_for_rarity,
)
from amberlog.governance.sensitive import SensitiveDataDetector, shannon_entropy
from amberlog.model import (
    FirewallDecision,
    LifecycleState,
    Memory,
    MemoryStats,
    MemoryType,
    Provenance,
    Scope,
    SecurityClass,
    ValueEstimate,
)

DAY_MS = 86_400_000


def memory(
    content: str = "A useful fact.",
    *,
    state: LifecycleState = LifecycleState.ACTIVE,
    type: MemoryType = MemoryType.SEMANTIC,
    security: SecurityClass = SecurityClass.INTERNAL,
    capabilities: tuple[str, ...] = (),
    context: dict | None = None,
    created_at: int = 0,
    hypothesis_set: str | None = None,
) -> Memory:
    return Memory(
        id="M1",
        version=1,
        type=type,
        content=content,
        provenance=Provenance(created_by="agent-a"),
        context=context or {},
        lifecycle_state=state,
        security_class=security,
        capabilities=capabilities,
        created_at=created_at,
        hypothesis_set=hypothesis_set,
    )


def value(mean: float, ci_low: float, n_eff: float = 20.0, contrastive: bool = True) -> ValueEstimate:
    return ValueEstimate(
        mean=mean,
        ci_low=ci_low,
        ci_high=mean + (mean - ci_low),
        n_eff=n_eff,
        estimator="ips" if contrastive else "naive_usage",
        contrastive=contrastive,
    )


class TestSensitiveDataDetector(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = SensitiveDataDetector()

    def test_detects_high_severity_secrets(self) -> None:
        cases = {
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIE...",
            "aws_access_key": "key is AKIAIOSFODNN7EXAMPLE here",
            "github_token": "ghp_" + "a" * 36,
            "anthropic_key": "sk-ant-" + "x" * 30,
            "password_assignment": "password: hunter2swordfish",
            "ssn_us": "ssn 123-45-6789",
        }
        for kind, text in cases.items():
            with self.subTest(kind=kind):
                findings = self.detector.scan(text)
                self.assertIn(kind, {f.kind for f in findings})
                self.assertTrue(self.detector.has_high_severity(text))

    def test_detects_medium_severity_pii(self) -> None:
        findings = self.detector.scan("contact ada@example.com about it")
        self.assertEqual([f.kind for f in findings], ["email"])
        self.assertFalse(self.detector.has_high_severity("contact ada@example.com"))

    def test_card_numbers_need_a_valid_checksum(self) -> None:
        # Valid Luhn test number.
        self.assertTrue(self.detector.has_high_severity("card 4242424242424242"))
        # A long run of digits that is not a card number must not trip it.
        self.assertNotIn(
            "credit_card", {f.kind for f in self.detector.scan("order 1234567890123456789")}
        )

    def test_clean_text_produces_nothing(self) -> None:
        self.assertEqual(self.detector.scan("Prefer email follow-up after onboarding."), [])

    def test_findings_never_echo_the_full_secret(self) -> None:
        """An audit record that quotes the secret has leaked it again."""
        secret = "ghp_" + "b" * 36
        findings = self.detector.scan(f"token {secret}")
        self.assertTrue(findings)
        for finding in findings:
            self.assertNotIn(secret, finding.excerpt)
            self.assertIn("*", finding.excerpt)

    def test_redaction_replaces_every_finding(self) -> None:
        text = "email ada@example.com and key AKIAIOSFODNN7EXAMPLE"
        redacted = self.detector.redact(text)
        self.assertNotIn("ada@example.com", redacted)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", redacted)
        self.assertIn("[REDACTED:email]", redacted)
        self.assertIn("[REDACTED:aws_access_key]", redacted)

    def test_overlapping_matches_are_attributed_once(self) -> None:
        findings = self.detector.scan("api_key = AKIAIOSFODNN7EXAMPLE")
        spans = [(f.start, f.end) for f in findings]
        for i in range(len(spans)):
            for j in range(i + 1, len(spans)):
                a, b = spans[i], spans[j]
                self.assertFalse(a[0] < b[1] and a[1] > b[0], "spans must not overlap")

    def test_high_entropy_strings_are_flagged(self) -> None:
        findings = SensitiveDataDetector(entropy_threshold=3.5).scan(
            "value Xq7X9sLpZ2mWvT4bKrY8nCjH3dFg"
        )
        self.assertIn("high_entropy_string", {f.kind for f in findings})

    def test_entropy_check_can_be_disabled(self) -> None:
        detector = SensitiveDataDetector(check_entropy=False)
        self.assertEqual(detector.scan("Xq7X9sLpZ2mWvT4bKrY8nCjH3dFg"), [])

    def test_entropy_of_uniform_text_is_low(self) -> None:
        self.assertLess(shannon_entropy("aaaaaaaa"), 0.1)
        self.assertGreater(shannon_entropy("abcdefgh"), 2.9)


class TestFirewall(unittest.TestCase):
    def setUp(self) -> None:
        self.firewall = Firewall()

    def evaluate(self, **kwargs) -> "object":
        request = FirewallRequest(**kwargs)
        return self.firewall.evaluate(request)

    def test_clean_active_memory_with_evidence_is_allowed(self) -> None:
        ruling = self.evaluate(
            memory=memory(), target_scope=Scope.TEAM, value=value(0.3, 0.1)
        )
        self.assertIs(ruling.decision, FirewallDecision.ALLOW)
        self.assertTrue(ruling.permits_sharing)

    def test_restricted_memory_may_not_leave_private_scope(self) -> None:
        ruling = self.evaluate(
            memory=memory(security=SecurityClass.RESTRICTED),
            target_scope=Scope.TEAM,
            value=value(0.9, 0.8),
        )
        self.assertIs(ruling.decision, FirewallDecision.DENY)
        self.assertFalse(ruling.permits_sharing)

    def test_non_active_memory_is_denied(self) -> None:
        for state in (LifecycleState.CANDIDATE, LifecycleState.DEPRECATED, LifecycleState.QUARANTINED):
            with self.subTest(state=state):
                ruling = self.evaluate(
                    memory=memory(state=state), target_scope=Scope.TEAM, value=value(0.5, 0.3)
                )
                self.assertIs(ruling.decision, FirewallDecision.DENY)

    def test_contested_memory_travels_with_a_warning(self) -> None:
        ruling = self.evaluate(
            memory=memory(state=LifecycleState.CONTESTED),
            target_scope=Scope.TEAM,
            value=value(0.5, 0.3),
        )
        self.assertIs(ruling.decision, FirewallDecision.ALLOW_WITH_WARNING)
        self.assertTrue(ruling.permits_sharing)
        self.assertTrue(any("sibling" in r for r in ruling.reasons))

    def test_missing_evidence_asks_for_validation(self) -> None:
        ruling = self.evaluate(memory=memory(), target_scope=Scope.FEDERATED, value=None)
        self.assertIs(ruling.decision, FirewallDecision.REQUIRE_VALIDATION)
        self.assertIn("no value evidence yet", ruling.reasons)

    def test_the_team_needs_no_value_evidence(self) -> None:
        ruling = self.evaluate(memory=memory(), target_scope=Scope.TEAM, value=None)
        self.assertIs(ruling.decision, FirewallDecision.ALLOW)

    def test_non_contrastive_evidence_is_not_enough(self) -> None:
        """A high average outcome is not proof that a memory helped.

        This is the value/relevance confusion in its most tempting form: the
        number looks strong and positive, so the rule must reject it on grounds
        of *kind*, not magnitude.
        """
        ruling = self.evaluate(
            memory=memory(),
            target_scope=Scope.FEDERATED,
            value=value(0.95, 0.90, contrastive=False),
        )
        self.assertIs(ruling.decision, FirewallDecision.REQUIRE_VALIDATION)
        self.assertTrue(any("not contrastive" in r for r in ruling.reasons))

    def test_value_must_clear_zero(self) -> None:
        ruling = self.evaluate(
            memory=memory(), target_scope=Scope.FEDERATED, value=value(0.05, -0.20)
        )
        self.assertIs(ruling.decision, FirewallDecision.REQUIRE_VALIDATION)
        self.assertTrue(any("does not clear zero" in r for r in ruling.reasons))

    def test_private_scope_needs_no_value_evidence(self) -> None:
        ruling = self.evaluate(memory=memory(), target_scope=Scope.PRIVATE, value=None)
        self.assertIs(ruling.decision, FirewallDecision.ALLOW)

    def test_procedure_with_ungranted_capabilities_is_denied(self) -> None:
        ruling = self.evaluate(
            memory=memory(type=MemoryType.PROCEDURAL, capabilities=("shell", "http")),
            target_scope=Scope.TEAM,
            value=value(0.4, 0.2),
            granted_capabilities=frozenset({"http"}),
        )
        self.assertIs(ruling.decision, FirewallDecision.DENY)
        self.assertTrue(any("shell" in r for r in ruling.reasons))

    def test_procedure_with_granted_capabilities_is_allowed(self) -> None:
        ruling = self.evaluate(
            memory=memory(type=MemoryType.PROCEDURAL, capabilities=("http",)),
            target_scope=Scope.TEAM,
            value=value(0.4, 0.2),
            granted_capabilities=frozenset({"http", "shell"}),
        )
        self.assertIs(ruling.decision, FirewallDecision.ALLOW)

    def test_correlated_evidence_blocks_federation(self) -> None:
        ruling = self.evaluate(
            memory=memory(),
            target_scope=Scope.FEDERATED,
            value=value(0.4, 0.2),
            evidence_independent=False,
        )
        self.assertIs(ruling.decision, FirewallDecision.REQUIRE_VALIDATION)
        self.assertTrue(any("shares ancestry" in r for r in ruling.reasons))

    def test_sensitive_content_is_quarantined(self) -> None:
        ruling = self.evaluate(
            memory=memory(content="the deploy key is AKIAIOSFODNN7EXAMPLE"),
            target_scope=Scope.PRIVATE,
            value=value(0.4, 0.2),
        )
        self.assertIs(ruling.decision, FirewallDecision.QUARANTINE)

    def test_strictest_decision_governs(self) -> None:
        """A memory that trips several rules gets the harshest outcome, and all
        reasons are kept for the audit trail."""
        ruling = self.evaluate(
            memory=memory(
                content="password: hunter2swordfish",
                state=LifecycleState.CONTESTED,
                security=SecurityClass.RESTRICTED,
            ),
            target_scope=Scope.FEDERATED,
            value=None,
        )
        self.assertIs(ruling.decision, FirewallDecision.DENY)
        self.assertGreaterEqual(len(ruling.reasons), 3)

    def test_ingest_screen_quarantines_only_high_severity(self) -> None:
        self.assertIs(
            self.firewall.screen_ingest("key ghp_" + "c" * 36).decision,
            FirewallDecision.QUARANTINE,
        )
        self.assertIs(
            self.firewall.screen_ingest("write to ada@example.com").decision,
            FirewallDecision.ALLOW_WITH_WARNING,
        )
        self.assertIs(
            self.firewall.screen_ingest("a perfectly ordinary fact").decision,
            FirewallDecision.ALLOW,
        )

    def test_severity_ordering(self) -> None:
        self.assertIs(
            strictest([FirewallDecision.ALLOW, FirewallDecision.DENY, FirewallDecision.QUARANTINE]),
            FirewallDecision.DENY,
        )
        self.assertIs(
            strictest([FirewallDecision.ALLOW, FirewallDecision.ALLOW_WITH_WARNING]),
            FirewallDecision.ALLOW_WITH_WARNING,
        )


class TestRetention(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = RetentionPolicy()
        self.now = 1_700_000_000_000

    def stats(self, exposures: int = 0) -> MemoryStats:
        return MemoryStats(memory_id="M1", exposures=exposures)

    def aged(self, days: float, **kwargs) -> Memory:
        """A memory created `days` before `self.now`."""
        return memory(created_at=int(self.now - days * DAY_MS), **kwargs)

    def test_old_deprecated_memories_are_deleted(self) -> None:
        decision = self.policy.decide(
            self.aged(200, state=LifecycleState.DEPRECATED), self.stats(), self.now
        )
        self.assertEqual(decision.action, "delete")

    def test_recent_deprecated_memories_are_kept(self) -> None:
        decision = self.policy.decide(
            self.aged(5, state=LifecycleState.DEPRECATED), self.stats(), self.now
        )
        self.assertEqual(decision.action, "keep")

    def test_quarantined_memories_get_a_longer_grace_period(self) -> None:
        """Quarantine is an investigation, so it outlasts deprecation."""
        self.assertEqual(
            self.policy.decide(
                self.aged(45, state=LifecycleState.QUARANTINED), self.stats(), self.now
            ).action,
            "keep",
        )
        self.assertEqual(
            self.policy.decide(
                self.aged(120, state=LifecycleState.QUARANTINED), self.stats(), self.now
            ).action,
            "delete",
        )

    def test_unknown_creation_time_is_reported_not_guessed(self) -> None:
        """An unset timestamp must not silently read as 'brand new', which
        would make the memory immortal without anyone noticing."""
        decision = self.policy.decide(
            memory(state=LifecycleState.DEPRECATED, created_at=0), self.stats(), self.now
        )
        self.assertEqual(decision.action, "keep")
        self.assertIn("unknown", decision.reason)

    def test_unused_candidates_are_deprecated(self) -> None:
        decision = self.policy.decide(
            self.aged(30, state=LifecycleState.CANDIDATE), self.stats(exposures=0), self.now
        )
        self.assertEqual(decision.action, "deprecate")

    def test_used_candidates_are_kept(self) -> None:
        decision = self.policy.decide(
            self.aged(30, state=LifecycleState.CANDIDATE), self.stats(exposures=3), self.now
        )
        self.assertEqual(decision.action, "keep")

    def test_a_protected_tag_overrides_every_rule(self) -> None:
        """The rare-but-critical case: a memory that matters once a year never
        accumulates evidence, so frequency-based rules would delete it
        (CRITICAL_REVIEW section 2.5)."""
        decision = self.policy.decide(
            self.aged(500, state=LifecycleState.DEPRECATED, context={"tags": ["critical"]}),
            self.stats(),
            self.now,
        )
        self.assertEqual(decision.action, "keep")
        self.assertIn("critical", decision.reason)

    def test_high_stated_impact_protects_an_unused_memory(self) -> None:
        decision = self.policy.decide(
            self.aged(500, state=LifecycleState.CANDIDATE, context={"impact": 0.9}),
            self.stats(exposures=0),
            self.now,
        )
        self.assertEqual(decision.action, "keep")
        self.assertIn("impact", decision.reason)

    def test_low_stated_impact_does_not_protect(self) -> None:
        decision = self.policy.decide(
            self.aged(500, state=LifecycleState.DEPRECATED, context={"impact": 0.1}),
            self.stats(),
            self.now,
        )
        self.assertEqual(decision.action, "delete")

    def test_explicit_protection_by_id(self) -> None:
        policy = RetentionPolicy(protected_ids={"M1"})
        decision = policy.decide(
            self.aged(500, state=LifecycleState.DEPRECATED), self.stats(), self.now
        )
        self.assertEqual(decision.action, "keep")

    def test_sweep_reports_only_actionable_decisions(self) -> None:
        pairs = [
            (self.aged(200, state=LifecycleState.DEPRECATED), self.stats()),
            (self.aged(200, state=LifecycleState.ACTIVE), self.stats(exposures=5)),
        ]
        decisions = self.policy.sweep(pairs, self.now)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].action, "delete")

    def test_expected_value_ranks_rarity_against_impact(self) -> None:
        self.assertAlmostEqual(expected_value(0.001, 1000.0), 1.0)
        self.assertGreater(expected_value(0.001, 1000.0), expected_value(0.5, 1.0))

    def test_rare_high_impact_memory_is_kept_despite_weak_evidence(self) -> None:
        weak = ValueEstimate(
            mean=0.0, ci_low=-1.0, ci_high=1.0, n_eff=1.0, estimator="ips", contrastive=True
        )
        self.assertTrue(should_keep_for_rarity(weak, probability=0.001, impact=500.0, threshold=0.1))

    def test_proven_harmful_memory_is_not_kept_for_rarity(self) -> None:
        harmful = ValueEstimate(
            mean=-0.4, ci_low=-0.6, ci_high=-0.2, n_eff=50.0, estimator="ips", contrastive=True
        )
        self.assertFalse(
            should_keep_for_rarity(harmful, probability=0.001, impact=500.0, threshold=0.1)
        )


if __name__ == "__main__":
    unittest.main()
