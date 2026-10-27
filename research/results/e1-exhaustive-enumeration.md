# E1 — exhaustive enumeration: typed filter vs search (INT-03)

Registered in [e1-exhaustive-enumeration.md](../prereg/e1-exhaustive-enumeration.md). Produced by
`python -m benchmarks.enumeration` at commit `8fde780d6ab6`; seeds 1, 2, 3, 4, 5; 1000 records,
10% written untyped, k = 50 for the search arms. No model. Raw numbers:
[e1-exhaustive-enumeration.json](e1-exhaustive-enumeration.json).

| arm | set-exact | narrow | broad | recall | precision | memories read / query |
|---|---|---|---|---|---|---|
| lexical | 0.613 | 0.753 | 0.473 | 0.772 | 1.000 | 50.0 |
| nav | 0.017 | 0.033 | 0.000 | 0.546 | 0.997 | 50.0 |
| typed | 0.100 | 0.180 | 0.020 | 0.896 | 1.000 | 39.8 |
| typed+fallback | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 198.6 |
| oracle | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 44.2 |

| B (lexical) | bar E1a | typed | typed > B in seeds | E1a | E1b certificate soundness | 8b/8c sanity | decision |
|---|---|---|---|---|---|---|---|
| 0.613 | 0.768 | 0.100 | 0/5 | fail | 1.00 (pass) | ok | **FAIL** |

`typed` called its answer complete on 0% of queries: a visible
memory without typed fields makes every answer incomplete, and the certificate says so rather than
treating unknown as no.

## Reading

**E1 fails as registered.** The typed filter alone answers fewer queries exactly than search plus a
text filter (0.100 vs 0.613). It loses where the world puts it at a disadvantage on purpose: with
10% of records written untyped, almost every broad answer set contains a record it cannot check.
It never claimed otherwise: no answer was called complete, so E1b passed — but only vacuously,
because the 60 untyped notes made every answer incomplete. Soundness on answers the filter *does*
call complete is untested here.

Two descriptive observations, not claims:

- Search's failures are the k cut-off: broad queries (gold sets of tens to ~100) are exact 0.47 of
  the time against 0.75 for narrow ones. That is the Sarvam "enumeration is not top-k" effect.
- `typed+fallback` (secondary, unthresholded) was exact on every query, reading ~199 memories a
  query against search's 50. That is partly by construction: the text filter matches this
  generator's sentence grammar exactly, which a real corpus will not. Claiming it needs its own
  registration on text the filter's author did not write.

Consequence, as registered: `typed_query` stays **experimental** and out of user guides; E2 does
not proceed to beta on this evidence.
