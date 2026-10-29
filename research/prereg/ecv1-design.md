# Evidence Completeness v1 — frozen design before threshold selection

Seeds/splits and corpus generation are defined in `benchmarks/completeness_data.py`.
Dev: 11, 23, 37, 41, 53. Test: 101, 127, 149, 163, 181. Never tune on test.
Each seed has 48 records, two queries, and 12 fallback content reads/query.
Gold is computed from latent records independently of the fallback text parser.
The test split uses different identifiers, seeds and text wrappers/formatting.
This is synthetic independent gold authoring, not third-party replication.

Arms: lexical top-budget retrieval, typed-only, typed+fallback over all visible
records with missing query fields, selective fallback over only three-valued
unknowns, oracle. Typed false on any conjunct is a definite nonmatch even if
another field is missing. Both fallback arms use the same evaluator and budget.
All content reads pass through logged retrieval with current eligibility checks.

Primary: set-exact accuracy under the declared read budget. Secondary: answer
recall/precision, coverage certificate soundness and positive issuance, coverage,
content reads, elapsed time and external-model cost (zero; hardware cost unpriced).
The oracle has the same read budget and visible corpus, differing only in knowing
which unknowns are positives; it cannot return more positive unknowns than it reads.

Run baseline arms and oracle on DEV first. If the best baseline saturates the
oracle or no positive ceiling headroom exists, report INCONCLUSIVE and do not
register an unreachable threshold. Otherwise commit a separate registration
with the measured metric, budget, split and a threshold at 40% of attainable
headroom before running selective fallback on frozen test. Require improvement
in at least four of five paired test seeds and zero false completeness claims.
Report the same-harness typed+fallback baseline even if it defeats the proposal.

Coverage certificates assert classification coverage conditional on supplied
typed values/evaluator, not truth, global-corpus completeness or action authority.
Unresolved, unread, ambiguous, newly added or revoked records prevent a positive
certificate. Test both positive and negative certificates so soundness is not
vacuously achieved by always withholding a certificate.
