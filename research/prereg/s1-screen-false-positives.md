# Pre-registration — S1: the injection screen on ordinary conversation

**Registered 2026-10-26**, before `experiments/s1_screen_fp.py` was run and
before any change to `injection.py` or `directive.py`.

## 1. Question

R3 found that the write-time injection screen quarantines ordinary
LongMemEval turns (1–9 in each ~500-turn history, read off a 6-instance
diagnostic, not a measurement), and that one such turn marks its author
hostile. Can the screen stop flagging ordinary conversation without catching
fewer injections?

## 2. Data

- **Benign:** every turn of LongMemEval `s` (500 histories), deduplicated.
  Histories are split by a hash of `question_id` into **tune** (even) and
  **test** (odd). Rules are changed looking at tune-split turns only; the
  test split is scored once, after.
  The turns are treated as benign. A turn that really is an injection would
  count against the screen; flagged test turns are listed so a reader can check.
- **Injections (recall guards):** deepset/prompt-injections **test** split
  (60 injections, 56 benign) and the author's held-out set
  (`research/bench/injection_heldout`, 12 injections, 16 hard negatives).
  Neither is used to choose a change.

## 3. Metric, baseline, ceiling

**Primary:** share of test-split turns the screen quarantines **as
injection** (pattern or directive; sensitive-data findings are reported
separately and are not this question). Baseline `B` = the current screen on
the same turns, measured first in the same run. Oracle 0.

**8c, before any change:** a screen that flags nothing scores 0 on this
metric and catches no injection. So the metric is only meaningful with the
recall guards below, and they are part of the pass condition, not a footnote.

## 4. Thresholds

- **S1a:** test-split false-positive rate at most `0.2 × B` (80% of the
  headroom removed).
- **S1b:** deepset test: at least **20 / 60** injections caught (the current
  screen's figure) and at most **0 / 56** benign flagged.
- **S1c:** held-out set: at least **10 / 12** injections, **0 / 16** hard
  negatives flagged.
- **S1d:** every existing test passes unchanged, including the red-team and
  pattern near-miss fixtures.

All four, or the change does not ship.

## 5. The second fix, stated here so it is not a surprise

Independently of the screen: **a memory's own author is not withheld from
itself** by `withhold_hostile_sources`. The flagged memory itself stays
quarantined, and every *other* agent still has the author's memories
withheld. Measured by LongMemEval `lexical` turn recall with withholding
**on** (the shipped default), which R3 found to be 0.033: it must come within
0.01 of the same run with withholding off.
