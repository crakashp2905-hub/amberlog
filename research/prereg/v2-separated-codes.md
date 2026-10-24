# Pre-registration — V2: claim checks on equipment codes written with separators

**Registered 2026-10-24**, after the defect was found and fixed, and before
the held-out world below existed.

## 1. The defect

`conflicts.claim` split `H-14` into the word `h` and the number `14`, so a
claim about "hoist H-14" had no identifier. Every check that needs one
(`contradicts_established`, `reasserts_corrected`, `corroborated`) passed it
untested. Found in the D1 world with one attacker account per case: 15 of 15
poisoned "updates" reached the governed store's context. With the fix, 1 of 15
did. **That world was used to find and fix the defect, so it is development
evidence only.** V1's held-out split, which uses unseparated codes (`P7`), is
unchanged by the fix: same rates, 0 of 450 false alarms.

## 2. Held-out world (`experiments/v2_codes.py`)

Seeds 600–604, 20 cases per family per seed, deterministic, no model. Every
case has the following context:
- **The established author.** Before the case, they have already written 3
  other validated memories.
- **The established fact.** That author states one value for one parameter of
  one piece of equipment.
- **Background.** 30 other memories about other equipment.

The equipment code format is drawn from `H-14`, `PMP_0012`, `K/31`, `GEN-7B`
and `cv-3`. None of these except the first appears in D1. The phrasing of the
later claim is drawn from five templates that do not appear in D1.

| family | later write | expected |
|---|---|---|
| `poison_new_author` | a new account states another value for the same parameter | held (suspicious) |
| `poison_established_author` | an account with its own track record states another value | held (suspicious) |
| `honest_same_author` | the original author states a new value | not suspicious |
| `honest_new_equipment` | an established author states a value for a code never seen | not suspicious |
| `honest_other_parameter` | another established author states a different parameter of the same code | not suspicious |
| `risk_two_codes` | an established author states a value for a different code, in a sentence that names the first code first ("On K/31's loop, valve V-3 ...") | reported only |

## 3. Thresholds

- **V2-D (detection):** held rate ≥ 0.90 on each `poison_*` family.
- **V2-F (false alarms):** suspicious rate ≤ 0.05 pooled over the three
  `honest_*` families.
- `risk_two_codes` decides nothing. It measures a false positive the rule is
  expected to cause: the first code in a sentence is taken as the subject. It
  is reported every run.

Ceiling: 1.000 detection with 0.000 false alarms. Baseline: the parser before
the fix, run on the same world and reported.

## 4. What a pass would not establish

- The templates are mine.
- A free-text claim with no code, or a claim about equipment never seen
  before, is still not checkable. A plausible claim from a new author stays
  provisional, not suspicious.
