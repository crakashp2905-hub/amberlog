# V2 — claim checks on separated equipment codes

Registered in [v2-separated-codes.md](../prereg/v2-separated-codes.md) before this
world existed. Produced by `python -m experiments.v2_codes --seeds 700 705` at commit `7ec68aa`;
raw numbers in [v2-codes-amend1.json](v2-codes-amend1.json). Seeds 700–704, 20 cases per
family per seed, deterministic, no model.

**V2-D SUPPORTED. V2-F SUPPORTED.** False-alarm rate on honest writes:
0.000.

Rate at which the later write is assessed **suspicious** (held for review):

| family | parser before the fix | parser now |
|---|---|---|
| `poison_new_author` | 0.220 | **1.000** |
| `poison_established_author` | 0.160 | **1.000** |
| `honest_same_author` | 0.000 | **0.000** |
| `honest_new_equipment` | 0.000 | **0.000** |
| `honest_other_parameter` | 0.130 | **0.000** |
| `risk_two_codes` | 0.210 | **0.000** |

`risk_two_codes` decides nothing. It measures the registered risk of taking the
first code in a sentence as its subject.
