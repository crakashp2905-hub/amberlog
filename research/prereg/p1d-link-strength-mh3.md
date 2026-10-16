# Pre-registration — P1d: link-strength selection on three-hop chains

**Registered 2026-10-16, after P1c and before holdout 3 is built.**

P1c's change (`chains.LINK_STRENGTH_SELECTION`) missed its pooled bar. The
`multi_hop_3` gain (0.500 → 0.917) was read from holdout 2 after the verdict,
so it is a hypothesis and not a result. This tests it once on fresh cases.

- **Change:** unchanged from P1c. No edit to `chains.py`.
- **Primary metric:** `multi_hop_3` chain sufficiency, k = 5.
- **Data:** holdout 3 is generator indices **300–323** for `multi_hop_3`
  only (24 cases), built at run time and scored once. Dev, holdouts 1–2 and
  the frozen test split are reported as contaminated.
- **SUPPORTED** if S ≥ B + 0.4 × (C − B) on holdout 3, where B is the chain
  with the switch off and C the oracle, **and** `multi_hop_4` does not fall
  on dev. INCONCLUSIVE if B ≥ 0.9.
- **If SUPPORTED:** the switch becomes the default for `reconstruct`. That is
  still opt-in for callers; `retrieve` is unchanged. **If not:** it stays off.
