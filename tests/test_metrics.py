"""Prometheus metrics from the log, incrementally; no content, no agent ids."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.actions import ActionGate, ActionPolicy, ToolRule
from amberlog.observability.metrics import StoreMetrics
from amberlog.observability.server import Api


class TestMetrics(unittest.TestCase):
    def test_counts_and_stays_incremental(self):
        f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        mid = f.remember("ag_secretive", "Pump P-14 relief valve is set to 12 bar.", scope="team")
        f.retrieve("ag_reader", "relief valve", k=3)
        gate = ActionGate(f, ActionPolicy(tools={"set_relief": ToolRule("set_relief")},
                                          grants={"ag_ops": frozenset({"set_relief"})}))
        cert = f.certify("x", [mid], "ag_ops")
        gate.authorize("set_relief", "ag_ops", cert)
        m = StoreMetrics()
        text = m.render(f)
        self.assertIn('mf_memories{state="active"} 1', text)
        self.assertIn("mf_retrievals_total 1", text)
        self.assertIn('mf_actions_total{tool="set_relief",allowed="true"} 1', text)
        f.quarantine(mid, reason="wrong", actor="lead", basis="contradicted")
        gate.authorize("set_relief", "ag_ops", cert)
        text = m.render(f)
        self.assertIn('mf_actions_total{tool="set_relief",allowed="false"} 1', text)
        self.assertIn('mf_withdrawals_total{to="quarantined"} 1', text)
        self.assertNotIn("Pump", text)
        self.assertNotIn("ag_secretive", text)
        self.assertNotIn(mid, text)

    def test_served_through_the_dashboard_api(self):
        f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        self.assertIn("mf_events_total", Api(f).metrics_text())


if __name__ == "__main__":
    unittest.main()
