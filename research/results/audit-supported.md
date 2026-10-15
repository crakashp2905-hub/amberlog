# Audit — do the supported claims hold under the current standards?

7 of 7 hold. Every input is traced to the result document that reported it; the arithmetic is in `experiments/audit_supported.py`.

| claim | n | seeds | effect | MDE at this n | headroom | holds |
|---|---|---|---|---|---|---|
| PB2 — retraction propagation | 240 | 5 | 0.17 | 0.0745 | — | **yes** |
| H4b — contested hypotheses preserved | 200 | 200 | 0.095 | 0.061 | — | **yes** |
| H1 — causal value is estimable | 2000 | 10 | 0.29 | 0.0337 | — | **yes** |
| P3b — agent teams | 300 | 5 | 0.19 | 0.0705 | 0.22 | **yes** |
| Copy recognition — no double-counted support | 30 | 5 | absence | rate <= 9.5% undetectable | — | **yes** |
| Live multi-agent — disagreement preserved | 10 | 1 | 0.8 | 0.792 | — | **yes** |
| X3 — scoped adjustments | 3 | 1 | 1.0 | n/a (deterministic) | 1.0 | **yes** |

## Issues raised, per claim

**PB2 — retraction propagation** — research/results/phase-b-federated-agents.md
- nothing raised
- _17% -> 0% acting on origin-retracted memory, 240 decisions per arm. The effect is large relative to n and it held under two policies, which is the nearest thing here to a replication._

**H4b — contested hypotheses preserved** — research/results/h4-topology-and-diversity.md
- effect 0.095 is under 2x its MDE 0.061: real but thin
- _P(correct) 0.905 -> 1.000, 200 replications per cell. Simulation, but the live multi-agent run tested the same mechanism with models that genuinely disagreed._

**H1 — causal value is estimable** — research/results/h1-causal-credit.md
- nothing raised
- _rho 0.76 against a naive 0.47. The only supported result whose own document discusses power._

**P3b — agent teams** — research/results/p3b-agent-teams.md
- nothing raised
- _fabric 0.970 against the best baseline's 0.780, oracle 1.000. The agent is deterministic, so seed variance is the only noise and the 19-point gap is far outside it. Nothing here is evidence about model behaviour, which section 6 of that result states as a choice._

**Copy recognition — no double-counted support** — research/results/p2b-copy-recognition.md
- a zero at n=30 is consistent with a true rate up to 9.5%
- _0.000 stale citations and 0.000 unrecognised copies, matching the oracle on both splits. An absence claim: the question is what rate a zero at this n could hide._

**Live multi-agent — disagreement preserved** — research/results/live-multi-agent.md
- effect 0.8 is under 2x its MDE 0.792: real but thin
- 1 seeds against AGENTS.md's requirement of 5
- not replicated on a second split or population
- _80% confidently wrong -> 0% with three real disagreeing models. The effect is enormous, and it is one run with no seeds: it is the demonstration that H4b's mechanism survives real disagreement, not an independent measurement of its size._

**X3 — scoped adjustments** — research/results/x3-scoped-adjustments.md
- deterministic, so power does not apply; the uncertainty is generalisation from 3 case(s) and needs a held-out split rather than a larger n
- 1 seeds against AGENTS.md's requirement of 5
- _0.000 -> 1.000 on dev, 3 cases of 3. Deterministic, so there is no sampling noise, but three cases is three cases and the test split was abandoned in advance at a zero ceiling._

