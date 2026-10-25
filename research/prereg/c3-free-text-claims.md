# Pre-registration — C3: a model-backed check for free-text claims

**Registered 2026-10-25**, before `experiments/c3_free_text.py` existed and
before `ModelClaimChecker` was measured.

## 1. Question

The built-in claim check reads identifiers and values, so a free-text claim
("the east wing is not safe to enter") is never checked (LIMITATIONS.md). Does
a model the user chooses, asked whether a new claim contradicts the most
related established memories, hold contradictions without holding honest
writes?

## 2. World (seeds 1–5)

Per seed, a store with 8 places (east wing, west wing, north lab, loading
bay, server room, cafeteria, archive, roof terrace) and 6 kinds of fact
(safe to enter, open to visitors, backup generator works, dogs allowed, fire
alarm monitored, night shift runs). An inspector with a track record records
one established fact for each of 24 sampled (place, kind) pairs, in free
text without identifiers or numbers.

Then 32 new claims by other authors, 8 of each type, drawn per seed:

| type | example | correct outcome |
|---|---|---|
| contradiction | "The east wing is not safe to enter; the ceiling is unstable." | held |
| paraphrase | "It is fine to go into the east wing." | not held |
| new detail | "The east wing was repainted last week." | not held |
| other place | the contradiction's wording about a place with no established fact | not held |

## 3. Arms

| arm | |
|---|---|
| `structural` | the product today: the built-in rules only (baseline) |
| `haiku` | `ModelClaimChecker("claude-cli:haiku")`, k = 5 |
| `sonnet` | `ModelClaimChecker("claude-cli:sonnet")`, k = 5 |
| `oracle` | holds exactly the contradictions |

**8c, before any model arm runs:** if `structural` already holds at least
90% of contradictions, there is nothing to measure and C3 is abandoned.

## 4. Metrics and thresholds

Pooled over seeds: **recall** (contradictions held) and **false holds**
(non-contradictions held, over all non-contradictions).

- **C3a:** a model arm's recall is at least `structural`'s plus **50% of the
  headroom** to the oracle's 1.0.
- **C3b:** its false-hold rate is at most **0.10**.
- **C3c:** both hold in at least 4 of 5 seeds individually.

An arm passing all three may be recommended in LIMITATIONS.md as the answer
to "free-text claims are not checked", **as an opt-in**, naming the model it
was measured with. It does not become a default: every write would then make
a model call, and a default that costs money and sends content to a provider
is the user's choice, not ours. Cost per write is reported.

**Ceiling check on every run (8b):** an arm above the oracle's recall or
below its 0 false holds invalidates the run.

## 5. Limits stated in advance

I wrote the templates and the labels, so the result is "works on these kinds
of contradiction", not on contradictions in general. Models are called
through the `claude` command line, which is the only model access here; the
same checker runs on any provider through `models.py`, and other models are
not measured by this.
