# Pre-registration — O1: typed claims, extracted once, to catch free-text contradictions without a model

**Registered 2026-10-27**, before `typedclaims.py` existed. The held-out templates below are fixed
here and were written before the extractor.

## 1. Question

The built-in claim check reads identifiers and values, so "the east wing is not safe to enter"
against "the east wing is safe to enter" is never caught (C3: structural recall 0.00). C3 showed a
model can catch it, at a model call per write. Can a typed reading of each claim, extracted when it
is written (subject, predicate, polarity), catch most of these for free?

## 2. Worlds (seeds 1–5, the C3 procedure)

Per seed: 24 established facts by an inspector with a track record, then 32 new claims by other
authors (8 contradictions, 8 paraphrases, 8 new details, 8 contradiction-worded claims about a
subject with no established fact), each written to a fresh store.

- **C3 world:** C3's own templates. Reported, **not** used for the thresholds: the author has seen them.
- **Held-out world H (thresholds):** the 8 subjects and 6 kinds below, with C3's sampling.

Subjects: the north gate, the pump house, the main lift, lab freezer F2, the staff canteen, the
visitor car park, the rear fire exit, the courier desk.

| kind | established | contradiction | paraphrase | new detail |
|---|---|---|---|---|
| locked | The {s} is locked overnight. | The {s} is never locked overnight. | Overnight, the {s} gets locked. | The {s} was fitted with a new handle. |
| staffed | The {s} is staffed on weekends. | The {s} is not staffed on weekends. | On weekends there is staff at the {s}. | The {s} got a new rota system. |
| accessible | The {s} is wheelchair accessible. | The {s} is not wheelchair accessible. | Wheelchair users can reach the {s}. | The {s} has a ramp near the entrance. |
| monitored | The {s} is covered by CCTV. | The {s} has no CCTV coverage. | CCTV covers the {s}. | The {s} cameras were cleaned last month. |
| heated | The {s} is heated in winter. | The {s} is unheated in winter. | In winter the {s} has heating. | The {s} heater is a gas model. |
| smoking | Smoking is permitted at the {s}. | Smoking is prohibited at the {s}. | People may smoke at the {s}. | The {s} has a new bin by the door. |

## 3. Arms

`structural` (the product today), `typed` (`TypedClaimChecker`, no model), `oracle`.

## 4. Thresholds (on H, pooled over seeds)

- **O1a:** `typed` recall ≥ `structural` + 50% of the headroom to 1.0.
- **O1b:** `typed` false holds ≤ 0.10 of non-contradictions.
- **O1c:** both in at least 4 of 5 seeds.

Pass: `TypedClaimChecker` may become the default claim checker in the `personal` and `team` presets
(it costs no model call; a hold is a review, never a deletion). Fail: it stays opt-in and the result
says so. **8b:** no arm above the oracle's recall or below its 0 false holds.

## 5. Limits stated in advance

Both worlds are templated English written by the author; this measures "catches these kinds of
contradiction", not contradictions in general. The model checker (C3) remains the option for
open-ended text.
