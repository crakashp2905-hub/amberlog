# Paraphrase links: unlinked restatements of a claim, found for review

`influence.paraphrases(fabric, memory_id)` lists memories that restate a
claim with no recorded link: the same identifiers and values, and at least
two shared content words (`conflicts.claim`). A memory that disagrees (same
identifiers, another value) is a contradiction and is never linked.
`influence.impact()` reports them as `possible_paraphrases`, apart from
recorded descent. Harness: `experiments/paraphrase_links.py`; raw:
[paraphrase-links.json](paraphrase-links.json).

**Fixture**, 5 seeds × 12 claims: 3 unlinked paraphrases each (positives),
an honest contradiction, a same-equipment note about another parameter with
the same value and unit (the hard negative), and an unrelated claim with the
same value.

| | value |
|---|---|
| paraphrases found by copy recognition (already on) | 120 / 180 |
| found only by the claim matcher | 60 / 180 (the loose, reordered template) |
| recall, either route | **1.000** |
| precision | **1.000** after one fix: 0.923 at one shared word |

**Read this as a sanity check, not evidence.** The fixture was written by
the same author as the matcher, and the threshold was changed once *on this
fixture* (one shared word → two) after the hard negative matched on its unit
alone. There is no held-out set. Real paraphrases that change the
identifier's spelling ("pump 1" for "P1") or state the value differently
("twelve bar") are missed, so a missed link still means "not found", never
"not descended".
