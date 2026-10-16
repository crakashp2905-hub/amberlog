# P1d — link-strength selection on three-hop chains

Registered in [p1d-link-strength-mh3.md](../prereg/p1d-link-strength-mh3.md)
before holdout 3 existed. Produced by `python -m experiments.p1c_strength --p1d`
at commit `ec32f62`; raw numbers in [p1d-strength-mh3.json](p1d-strength-mh3.json).

**SUPPORTED.** On 24 fresh `multi_hop_3` cases (holdout 3), chain
sufficiency goes from **0.417** to **0.917** against an oracle of 1.000
(threshold 0.650). `multi_hop_4` on dev not worse: True.

Cost: nodes explored 208.0 → 208.0.

**What it does not establish.** Same templates as every other split: new
cases, not a new distribution. `reconstruct` is opt-in either way.
