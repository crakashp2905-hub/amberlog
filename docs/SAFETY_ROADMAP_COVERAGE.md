# AI-safety and security roadmap: coverage

The owner's roadmap ("Amberlog: AI Safety, Security, and Novel Research
Roadmap", 2026-10-19), item by item.

- **done**: implemented and tested here, with the evidence named.
- **partial**: something exists, with a named gap.
- **open**: not built.

"Done" never means certified: there has been no independent review
([INDEPENDENT_EVALUATION.md](INDEPENDENT_EVALUATION.md)).

## Capabilities (roadmap §4)

| | capability | status | evidence |
|---|---|---|---|
| A | **Compromise and influence graph**: copies, summaries, derived claims, agents, actions; exposure, influence, reliance and action kept apart | **done (structure)**, partial (semantic) | `influence.py`: typed edges `derived_from`, `summarized_from`, `copied_from`, `imported_from`, `exposed_to`, `relied_on`, `authorized`, `invalidated_by`; `impact()` keeps potentially contaminated, actually retrieved and confirmed use apart (`tests/test_influence.py`). Lineage, copy recognition, the provenance chain, `incident.reconstruct` (P9: precision 0.996, recall 1.000). **Gap:** paraphrases with no lineage or copy link are joined only through exposure |
| B | **Proof-carrying memory**: a verifiable evidence envelope per record | **partial** | Every record carries a version, provenance (creator, method, versioned parents), scope, tenant, security class, lifecycle and validity; a hash chain over every event; evidence certificates for actions; correction receipts (S5). **Gap:** no single exported, versioned envelope schema per record |
| C | **Temporal trust and delayed attacks** | **partial** | Bitemporal validity (`as_of`, `until`), supersession, version-scoped correction (S1), learned staleness (T1: detects drift, adds +0.004). **Gap:** delayed-activation and progressive-poisoning attack families are not in a benchmark |
| D | **Collusion-resistant corroboration** | **partial, experimental** | `independence.py` (S2): false corroboration 0.83 → 0.28, at 0.02 → 0.25 blocked independent evidence. Kept opt-in, as the roadmap advises |
| E | **Decision-specific trust** | **done (policy)**, **partial (learned)** | Action gating with per-tool evidence rules, independent-source minimums and human approval (`actions.py`); recipient trust per (source, context) (S4, supported on the bar, opt-in) |
| F | **Verified recovery coordinator** | **done** | `response.py`: detect, assess, contain, record, and `verify_recovery` (containment checked from state; offline peers *unresolved*; external actions never called resolved). The flagship incident is a test (`tests/test_verified_recovery.py`); `incident --verify` |
| G | **Privacy-preserving federation** | **partial** | Peer authentication (HMAC), scopes, replay protection (deduplication), cycle refusal (F12), minimal acknowledgements (F13), receipts that bind at audit (S5), the signed hostile-source notice. Key rotation drilled with an overlap window. **Gap:** there is no protection against a privileged database holder |
| H | **Safe adaptation without silent weakening** | **done** | Every adaptive or research mechanism is opt-in and experimental (STABILITY.md, enforced by `test_stability.py`); hard controls are not learned; the gated rulebook (M2) adopts only on held-out verified evidence, and its rules can only narrow retrieval |

## Memory poisoning: prevention and detection

| layer | mechanism | measured |
|---|---|---|
| Admission | pattern injection screen + secret screen | matched injection caught; **0/12** held-out paraphrases |
| Admission | **directive detector** (new): flags *what an injection does*, not its wording | **10/12** held-out paraphrases, **0/16** benign hard negatives ([injection-heldout](../research/results/injection-heldout.md)); **on by default** at ingest and share since 0.12.0. Third-party set (deepset, test): **20/60, 0/56 benign** after an override family; 0/60 before ([third-party](../research/results/injection-thirdparty.md)) |
| Admission | review queue: imports land as candidates | by design |
| Retrieval | **contradiction surfacing** (`conflicts.py`) | acting on an undetected poison 63% → 51–55%, held-out (G4b); **on by default** in context and recall since 0.12.0 |
| Retrieval | source-root grouping, copy recognition | copies do not count as corroboration |
| Cross-store | **hostile-source notice**: a source caught injecting at one store is withheld where its memories travelled | T2b held-out: safe success 0.732 → **0.949** (81% of headroom), collateral up ([t2b](../research/results/t2b-source-notice.md)); withholding on receipt opt-in |
| Action | action fence, evidence certificates, **origin-bound authority**, exact-action grants | 0 / 1,229 violations (S6); `tests/test_authority.py` |
| Recovery | retraction across stores, verified recovery | P3, B2; `verify_recovery` |
| Background | the manager: audit triggers, contradiction scan, checkpoints, notices | `tests/test_manager.py` |

**The attack that no mechanism here can see: a plain false claim from a
source that has never misbehaved.** Before detection it is indistinguishable
from truth (G4). Contradiction surfacing and review narrow the window, and
retraction closes it afterwards. Nothing closes it beforehand, and this
document does not claim otherwise.

## Risks to revalidate (roadmap §7)

| # | risk | status at 0.12.0 |
|---|---|---|
| 1 | Semantic or paraphrased injection | **partly addressed**: the directive detector (10/12 held-out), on by default; origin-bound authority keeps a laundered copy from acting |
| 2 | Poison ranking | **partly addressed**: G4b, significant but not solved |
| 3 | Offline propagation window | **by design, reported**: `verify_recovery` marks it unresolved; the manager retries delivery |
| 4 | Storage-administrator threat | **mitigated only with off-host checkpoints** (`--checkpoint-dir`) |
| 5 | Logical tenancy | **open, documented** ([LIMITATIONS.md](LIMITATIONS.md)) |
| 6 | Federation key rotation | **done**: overlap window (`Peer.accepted`, `previous_keys`), drilled over HTTP in four phases including a refused leaked old key (`tests/test_key_rotation_drill.py`, RUNBOOKS §3) |
| 7 | Audit integrity and privacy | hash chain plus external checkpoints; content-free audit export (P6) |
| 8 | Resource exhaustion | agent-api rate limits, bounded body sizes, bounded connect (0.11.0); no load-shedding beyond these |
| 9 | Action races | **closed for `execute`** (S6), including lease expiry, retry and cross-process on Postgres |
| 10 | Correction-receipt leakage | **fixed** (F13), re-measured at 0.000 |
| 11 | Evidence-independence trade-off | **measured** (S2), kept opt-in |
| 12 | External assurance | **open**: no independent audit |

## Roadmap phases

| phase | status |
|---|---|
| 0 Release qualification | **done** for 0.11.0 (`v0.11.0`); 0.12.0 follows the same gate |
| 1 Close memory-poisoning gaps | **done to the measured extent**: directive detector (on), contradiction surfacing (on), hostile-source notice (supported), origin-bound authority (tested); the plain false claim from a clean source remains open, as stated above |
| 2 Compromise graph | **done (structure)**: typed influence edges and `impact()`; semantic paraphrase links remain partial (A) |
| 3 Recovery orchestration | **done** (F) |
| 4 Proof-carrying memory and decision policy | **partial** (B, E) |
| 5 Privacy and federation | **partial** (G) |
| 6 Independent red team | **open**: needs a third party |
