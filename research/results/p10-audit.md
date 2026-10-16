# P10 — periodic, event-triggered and risk-budgeted auditing

Produced by `python -m experiments.p10_audit` at commit `3163ec3`; raw numbers
in [p10-audit.json](p10-audit.json). 10 seeds, 200 steps,
audits every 20 steps, a budget of 3 audits a window for the
budgeted policies, and a second run at a budget of 1, where the budget binds. Not pre-registered: a measurement of a diagnostic tool.

The auditor is **observation only**. It writes nothing, and no check consults
it. "Benign flags" are audits that returned a finding on a subject that was not
a planted problem. Each would be an operator's wasted look, never an automatic
quarantine, because nothing quarantines automatically.

| policy | problems detected | median delay (steps) | audits a seed | benign flags a seed | events read a seed |
|---|---|---|---|---|---|
| `periodic` | 32% | 59 | 30.0 | 2.7 | 753 |
| `event_triggered` | 100% | 39.0 | 25.5 | 1.0 | 129 |
| `risk_budgeted` | 100% | 39.0 | 14.5 | 1.0 | 118 |
| `periodic_budget_1` | 15% | 39.0 | 10.0 | 1.1 | 250 |
| `risk_budgeted_budget_1` | 50% | 39.0 | 9.0 | 1.0 | 105 |

**Reading.** Blind periodic sampling spends the most reading and finds the
fewest problems. Event-triggered and risk-budgeted auditing find the same
problems here. At a budget of 3 the risk-budgeted policy did not use its whole
allowance, because there were fewer triggers than that. The budget-1 rows show
the trade once the budget binds. Delays are long for the compromised writer:
its burst is flagged at once, but the audit finds nothing wrong until its
claims are withdrawn. A burst alone is not evidence of compromise, and the
auditor does not treat it as such.

**Limits.** Four planted problems a seed, all of kinds the triggers were
written for. That measures how the policies spend a budget on known signals.
It says nothing about problems no trigger describes. A periodic audit can find
those in principle, and here it mostly does not, because it samples blindly.
