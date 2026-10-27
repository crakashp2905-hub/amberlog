# Release readiness

The masterplan's definition of done (§10) and hard blockers (§7A.12), checked against this tree.
The commit-specific evidence is the release bundle (`tools/release_bundle.py`), which now includes
`STATUS_AT_HEAD.md` and a `versions consistent` check.

## Hard blockers

| Blocker | State |
|---|---|
| Confirmed tenant escape | **one found and fixed** (cross-tenant copy links, schema 0.14.0); GOV-07 tests guard it |
| Protected action after committed withdrawal inside the fence | none known; GOV-12 tests |
| Lost or suppressed retraction | none known; GOV-02/03/04 tests |
| False independence authorising a protected action | none known; GOV-05/06/08 tests |
| Secrets in logs or receipts | none known; GOV-10 tests and the secret scan |
| Compiler bypassing ingest validation | none: compiled sections go through `remember` and its screens |
| Benchmark gold contamination | E1/INT-01/INT-04 write no gold into the store |
| Unverifiable experiment traces | 33 older results lack a commit (listed in the manifest) |
| Schema change without migration | 0.14.0 changes a projection rule only; replay applies it |
| Unsafe ontology promotion | no ontology promotion exists |

## Definition of done for a release

| Requirement | State |
|---|---|
| CI green on the exact commit | per PR; a release needs it on the tagged commit |
| Versions consistent (package ≥ schema = SPEC) | checked by `tools/status_at_head.py --check` |
| Every stability tier accurate | `tools/gen_stability.py`; no experimental module on by default (typedclaims promoted to beta) |
| Known gaps published | [KNOWN_GAPS.md](KNOWN_GAPS.md) |
| External security review | **not done** (blocked) |
| Owner sign-off and tag | **not done**; nothing is tagged or published |

Verdict: **not release-ready as 1.0**; suitable as an alpha candidate once CI is green on the commit
to be tagged and the owner signs off.
