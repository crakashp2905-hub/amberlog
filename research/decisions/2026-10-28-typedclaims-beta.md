# 2026-10-28 — `typedclaims` promoted from experimental to beta

**Problem.** `TypedClaimChecker` became the default claim checker in the
`personal` and `team` presets when O1 passed (research/results/o1-typed-claims.md).
That left an *experimental* module on by default, which the masterplan
(§0, "do not enable experimental intelligence by default") and STABILITY.md's
tiering both treat as a contradiction. `tools/status_at_head.py` lists it.

**Decision.** Promote the module to **beta**: its interface (`contradicts`,
`proposition`, `TypedClaimChecker.check`) is covered by unit tests, it makes no
model call, it only *holds* writes for review (never deletes), and its default
was a registered consequence of a passed, pre-registered experiment with a
measured oracle and a held-out world.

**Alternatives.** Revert the default (discards a registered pass); keep it
experimental and on (the contradiction stays).

**Expected failure mode.** Paraphrase and quantity contradictions are missed
(documented in docs/LIMITATIONS.md); a false hold costs a reviewer click.

**Rollback.** `open_store(..., claim_checker=None)` per store; reverting the
preset line removes the default.
