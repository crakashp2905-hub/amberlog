import unittest

from memory_fabric.decision_models import (
    DecisionContext,
    DecisionModelError,
    DecisionOption,
    DecisionProposal,
    DeterministicDecisionModel,
    EscalationPolicy,
    CallableDecisionModel,
    brier_score,
    route_decision,
)


class DecisionModels(unittest.TestCase):
    def setUp(self):
        self.context = DecisionContext("deploy?", (
            DecisionOption("ship", "ship", action="deploy"),
            DecisionOption("hold", "hold"),
        ), evidence_ids=("m1",))

    def test_typed_probability_and_abstention_contract(self):
        proposal = DeterministicDecisionModel({"ship": 3, "hold": 1}).decide(self.context)
        self.assertEqual(proposal.selected, "ship")
        self.assertAlmostEqual(sum(proposal.probabilities.values()), 1)
        self.assertFalse(proposal.abstained)

    def test_tie_abstains_and_escalates(self):
        proposal = route_decision(DeterministicDecisionModel({"ship": 1, "hold": 1}),
                                  self.context, EscalationPolicy())
        self.assertTrue(proposal.abstained)
        self.assertTrue(proposal.requires_system2)

    def test_consequential_action_always_escalates(self):
        proposal = route_decision(DeterministicDecisionModel({"ship": 9, "hold": 1}),
                                  self.context,
                                  EscalationPolicy(consequential_actions=frozenset({"deploy"})))
        self.assertTrue(proposal.requires_system2)

    def test_malformed_probability_is_rejected(self):
        with self.assertRaises(DecisionModelError):
            DecisionProposal("ship", {"ship": .9, "hold": .9}, False, .9).validate(self.context)

    def test_brier_score(self):
        proposal = DeterministicDecisionModel({"ship": 3, "hold": 1}).decide(self.context)
        self.assertAlmostEqual(brier_score([proposal], ["ship"], ["ship", "hold"]), .125)

    def test_external_model_adapter_is_still_validated(self):
        model = CallableDecisionModel("jev-test", lambda _: {"ship": .8, "hold": .2})
        self.assertEqual(model.decide(self.context).selected, "ship")
        broken = CallableDecisionModel("broken", lambda _: {"ship": 2, "hold": 0})
        with self.assertRaises(DecisionModelError):
            broken.decide(self.context)


if __name__ == "__main__":
    unittest.main()
