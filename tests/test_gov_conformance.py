"""GOV-01..GOV-24 (masterplan §7A.7): every governance assertion maps to tests that exist and run.

`GOV` names, for each assertion, the tests that check it. Most predate the
masterplan; `test_every_mapped_test_exists` keeps the map honest (a renamed or
deleted test fails here), and the classes below add the direct checks that
were missing. Status is one of COVERED, PARTIAL (what is not covered is said),
BLOCKED (cannot be tested here, with the reason).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.model import EXPOSABLE_STATES

ROOT = Path(__file__).resolve().parents[1]

GOV: dict[str, tuple[str, list[str], str]] = {
    "GOV-01": ("COVERED", ["test_withdrawn_memory_is_never_exposed"], ""),
    "GOV-02": ("COVERED", ["test_a_diamond_withdraws_both_copies", "test_a_mesh_with_cycles_converges"], ""),
    "GOV-03": ("COVERED", ["test_an_offline_recipient_stays_pending_and_visible",
                           "test_no_lease_means_strict_refuses_and_lenient_allows",
                           "test_partition_bounds_staleness_to_one_lease_lifetime"], ""),
    "GOV-04": ("COVERED", ["test_a_replay_is_applied_in_the_origins_order"], ""),
    "GOV-05": ("COVERED", ["test_independent_support_survives_the_poison_being_withdrawn"], ""),
    "GOV-06": ("COVERED", ["test_laundering_through_a_second_store_is_still_one_source"], ""),
    "GOV-07": ("COVERED", ["test_same_content_in_two_tenants_never_shares_a_source_root",
                           "test_a_withdrawal_in_one_tenant_never_contests_another",
                           "test_a_cross_tenant_copy_in_an_old_log_is_ignored_on_replay",
                           "test_cross_tenant_changes_are_refused"], ""),
    "GOV-08": ("COVERED", ["test_a_compromised_peer_cannot_vouch_for_another_store",
                           "test_a_new_source_is_provisional_and_independent_agreement_corroborates"], ""),
    "GOV-09": ("COVERED", ["test_the_summary_inherits_the_lowest_authority",
                           "test_an_injection_written_by_the_summariser_is_quarantined"], ""),
    "GOV-10": ("COVERED", ["test_no_memory_content_leaks_in_any_refusal"], ""),
    "GOV-11": ("COVERED", ["test_a_revoked_credential_stops_the_action",
                           "test_a_revoked_credential_is_refused_at_the_next_call"], ""),
    "GOV-12": ("COVERED", ["test_withdrawn_evidence_stops_it_before_the_side_effect",
                           "test_a_concurrent_retraction_waits_for_the_action"], ""),
    "GOV-13": ("COVERED", ["test_an_unknown_outcome_needs_an_explicit_retry_that_re_verifies",
                           "test_the_next_call_refuses_until_someone_says_to_retry"], ""),
    "GOV-14": ("COVERED", ["test_tampering_with_stored_content_is_detected_on_replay",
                           "test_a_consistent_rewrite_is_caught_by_an_earlier_anchor"], ""),
    "GOV-15": ("COVERED", ["test_an_erased_memory_is_not_resurrected_by_a_restored_key",
                           "test_erasing_a_source_erases_its_summaries"], ""),
    "GOV-16": ("PARTIAL", ["test_the_copy_replays_to_the_same_state", "test_restore_brings_back_readable_content_keys_and_config"],
               "backup/restore round-trips everything; a cross-store export/import that keeps tombstones is not built"),
    "GOV-17": ("COVERED", ["test_an_instruction_is_never_evidence",
                           "test_preamble_frames_memories_as_evidence_not_instructions"], ""),
    "GOV-18": ("PARTIAL", ["test_the_stated_false_positive_is_pinned"],
               "false-hold rates are measured per screen (S1, O1, C3 results); no single collateral-damage report"),
    "GOV-19": ("COVERED", ["test_concurrent_writers_serialise_without_losing_writes",
                           "test_a_retraction_killed_mid_transaction_leaves_no_trace"], ""),
    "GOV-20": ("BLOCKED", ["test_partition_bounds_staleness_to_one_lease_lifetime"],
               "simulated on one host; multi-physical-host faults need a second machine"),
    "GOV-21": ("COVERED", ["test_a_contradiction_keeps_both_sides_and_deletes_neither"], ""),
    "GOV-22": ("COVERED", ["test_as_of_gives_the_state_at_that_moment",
                           "test_believed_at_differs_from_true_at_after_a_correction"], ""),
    "GOV-23": ("PARTIAL", ["test_the_proposer_cannot_verify_its_own_rules"],
               "no procedural-skill asset exists yet; rulebook revisions are gated and reviewed"),
    "GOV-24": ("COVERED", ["test_the_full_path_is_reconstructed", "test_writers_are_named_and_decoys_are_not_on_the_path"], ""),
}


class Map(unittest.TestCase):
    def test_every_assertion_is_mapped(self) -> None:
        self.assertEqual(sorted(GOV), [f"GOV-{i:02d}" for i in range(1, 25)])

    def test_every_mapped_test_exists(self) -> None:
        defined = set()
        for path in (ROOT / "tests").glob("test_*.py"):
            defined |= set(re.findall(r"def (test_\w+)", path.read_text(encoding="utf-8")))
        for gid, (status, names, why) in GOV.items():
            self.assertIn(status, ("COVERED", "PARTIAL", "BLOCKED"))
            if status != "COVERED":
                self.assertTrue(why, f"{gid} {status} needs a reason")
            for name in names:
                self.assertIn(name, defined, f"{gid}: {name} no longer exists")


class Direct(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(":memory:", recognise_copies=True)
        self.addCleanup(self.f.close)

    def test_withdrawn_memory_is_never_exposed(self) -> None:
        mid = self.f.remember("a", "The north gate code is changed weekly.", scope="team")
        self.f.validate(mid, actor="r")
        self.assertIn(mid, [m.id for m in self.f.retrieve("b", "north gate code", min_relevance=0.0).exposed])
        self.f.quarantine(mid, reason="wrong", actor="r", basis="contradicted")
        for agent in ("a", "b"):
            got = self.f.retrieve(agent, "north gate code", k=20, min_relevance=0.0, include_contested=True)
            self.assertNotIn(mid, [m.id for m in got.exposed])

    def test_same_content_in_two_tenants_never_shares_a_source_root(self) -> None:
        a = self.f.remember("a", "Pump P-3 relief is 12 bar.", tenant_id="t1")
        b = self.f.remember("a", "Pump P-3 relief is 12 bar.", tenant_id="t2")
        self.assertNotEqual(self.f.source_root(a), self.f.source_root(b))
        self.assertNotEqual(self.f.state.copy_of.get(b), a)
        self.assertNotEqual(self.f.state.copy_of.get(a), b)

    def test_a_withdrawal_in_one_tenant_never_contests_another(self) -> None:
        a = self.f.remember("a", "Pump P-3 relief is 12 bar.", tenant_id="t1")
        b = self.f.remember("z", "Pump P-3 relief is 12 bar.", tenant_id="t2")
        for m in (a, b):
            self.f.validate(m, actor="r")
        self.f.quarantine(a, reason="wrong", actor="r", basis="contradicted")
        self.assertIs(self.f.get(b).lifecycle_state, LifecycleState.ACTIVE)
        # Re-ingesting text withdrawn in another tenant is not a re-ingestion.
        c = self.f.remember("y", "Pump P-3 relief is 12 bar.", tenant_id="t3")
        self.assertIsNot(self.f.get(c).lifecycle_state, LifecycleState.CONTESTED)

    def test_a_cross_tenant_copy_in_an_old_log_is_ignored_on_replay(self) -> None:
        from memory_fabric import events as ev

        a = self.f.remember("a", "Pump P-3 relief is 12 bar.", tenant_id="t1")
        b = self.f.remember("z", "Pump P-3 relief is 12 bar.", tenant_id="t2")
        # What a pre-fix store recorded.
        self.f._emit(ev.copy_recognised(ts=self.f.now(), memory_id=b, original_memory_id=a,
                                        containment=1.0, agent_id="z", episode_id=None))
        self.f.rebuild()
        self.assertNotIn(b, self.f.state.copy_of)
        self.assertNotEqual(self.f.source_root(a), self.f.source_root(b))

    def test_a_contradiction_keeps_both_sides_and_deletes_neither(self) -> None:
        a = self.f.remember("a", "The canteen opens at 8.", scope="team")
        b = self.f.remember("b", "The canteen opens at 9.", scope="team")
        for m in (a, b):
            self.f.validate(m, actor="r")
        self.f.challenge([a, b], evidence="two opening times")
        for m in (a, b):
            self.assertIs(self.f.get(m).lifecycle_state, LifecycleState.CONTESTED)
        got = self.f.retrieve("c", "canteen opens", k=10, min_relevance=0.0, include_contested=True)
        self.assertEqual({a, b} & {m.id for m in got.exposed}, {a, b})

    def test_believed_at_differs_from_true_at_after_a_correction(self) -> None:
        from memory_fabric.incident import replay_until

        wrong = self.f.remember("a", "Rate R is 15 per cent.", structured={"rate": 15},
                                valid_from=0, valid_to=None)
        self.f.validate(wrong, actor="r")
        before = self.f.log.head_seq
        self.f.quarantine(wrong, reason="recorded wrong", actor="auditor", basis="contradicted")
        right = self.f.remember("a", "Rate R is 12 per cent.", structured={"rate": 12}, valid_from=0)
        self.f.validate(right, actor="r")
        then = replay_until(self.f, before).memories
        self.assertIn(then[wrong].lifecycle_state, EXPOSABLE_STATES)
        self.assertNotIn(right, then)
        self.assertNotIn(self.f.get(wrong).lifecycle_state, EXPOSABLE_STATES)


if __name__ == "__main__":
    unittest.main()
