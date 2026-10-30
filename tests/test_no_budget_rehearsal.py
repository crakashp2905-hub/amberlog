"""Non-vacuous controls for the optional local-model shadow rehearsal."""
import json
import unittest

from experiments.no_budget_rehearsal import local_endpoint, run_case


class ApprovingModel:
    def chat(self, *args, **kwargs):
        # Deliberately ignores corrections: the host gate must still stop it.
        return {"message": {"content": json.dumps({"approve": True})}}


class LocalRehearsal(unittest.TestCase):
    def test_loopback_only(self):
        self.assertEqual(local_endpoint("http://127.0.0.1:11439/"), "http://127.0.0.1:11439")
        for endpoint in ("https://api.example.com", "http://192.0.2.1", "http://user@localhost",
                         "http://localhost/path", "http://localhost?token=anything"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                local_endpoint(endpoint)

    def test_withdrawn_evidence_blocks_even_when_model_approves(self):
        row = run_case(ApprovingModel(), "local-test-double", 601, corrected=True)
        self.assertEqual(row["outcomes"]["shared_cached"]["stale_actions"], 1)
        self.assertEqual(row["outcomes"]["shared_recheck"]["stale_actions"], 0)
        self.assertEqual(row["outcomes"]["governed"]["stale_actions"], 0)
        self.assertEqual(row["outcomes"]["governed"]["correct_abstention"], 1)
        self.assertEqual(row["governed_shadow_effects"], 0)

    def test_valid_evidence_executes_positive_control(self):
        row = run_case(ApprovingModel(), "local-test-double", 607, corrected=False)
        self.assertEqual(row["outcomes"]["governed"]["task_success"], 1)
        self.assertEqual(row["governed_shadow_effects"], 1)

    def test_model_abstention_is_measured_as_false_blocking_on_valid_evidence(self):
        class AbstainingModel(ApprovingModel):
            def chat(self, *args, **kwargs):
                return {"message": {"content": '{"approve":false}'}}
        row = run_case(AbstainingModel(), "local-test-double", 607, corrected=False)
        self.assertEqual(row["outcomes"]["governed"]["false_blocking"], 1)
        self.assertEqual(row["outcomes"]["oracle"]["task_success"], 1)
