# Work plan

The task list for the requests of 2026-10-18: the six release gates, the six
research directions, the ten product capabilities, and then the
memory-objective experiment, which is deliberately **last**. One row per task,
each with a definition of done that names evidence, not effort. Status is kept
current as the work lands. This is a working document, not a claim: "done"
means the row's own definition is met and linked.

Status: ⬜ not started · 🔄 in progress · ✅ done · ⛔ blocked (needs something
outside this environment, named) · 🔶 done with a stated gap.

## Blockers outside this environment

| | Needs | Blocks |
|---|---|---|
| **X-CI** | GitHub Actions billing fixed. Every job on `main` since 2026-10-16 failed before starting: "recent account payments have failed" | G1, the tag in G6 |
| **X-API** | A frontier model: `ANTHROPIC_API_KEY`, or the Claude Code CLI on this machine. Neither is present | Frontier-model arms in G4, S3, M1; the live Claude-adapter check in G2 |
| **X-DKR** | A Docker daemon | Container smoke test in G6 |

Everything else runs here: Windows, 8 cores, CPU only, Python 3.12/3.13, a local
PostgreSQL 16, and local Ollama models from 1.5B to 14B (`qwen2.5:7b`,
`llama3.1:8b`, `phi4`, `deepseek-r1:14b`, `gemma3:4b`, ...). The ⛔ rows are
the parts that need the items above. The rest of each task proceeds.

## Order, and why

1. **G2, then G3**: lint, types and packaging first, because every later task
   adds code that should be checked by them. Then the capacity work, because
   P12 is the largest product gap and four product capabilities (console,
   review queue, incident response, integrations) assume many agents on one
   store.
2. **G5**: the security review runs after the capacity changes, so it reviews
   the code that ships.
3. **P1–P10**: the product capabilities. Several reuse modules that already
   exist (`observability/`, `incident.py`, `auditor.py`, `doctor`), so each
   starts with what is there.
4. **G4 with S3**: one independently designed adversarial benchmark serves both
   the release gate and the federated-benchmark research direction.
5. **S1, S2, S4, S5, S6**: research, each pre-registered with a ceiling,
   baselines measured in the run and a power estimate (AGENTS.md 8–8d), and
   checked by `memeval`.
6. **G6**: final acceptance against a frozen release candidate.
7. **M1**: the memory objective.

## Release gates

| ID | Task | Definition of done | Status |
|---|---|---|---|
| G1 | Pin the exact `main` SHA and get a verified, fully passing CI run. Reconcile all test counts and release records | A green CI run on a named SHA. Every test count in README, VALIDATION, IMPLEMENTATION_STATUS and RELEASE_EVALUATION derived from one command at that SHA, and a test that fails when a doc's count drifts | ⛔ X-CI for the run. 🔶 Reconciliation done: `tools/count_tests.py` and `tests/test_suite_hygiene.py` (one checked count; no pytest-only files, after `test_memeval.py` was found invisible to CI); VALIDATION's baseline rows re-run |
| G2 | Resolve the Claude API adapter, metadata, lint/type-checking, migration and packaging gaps | ruff and mypy configured, clean, and in CI. Package metadata complete, with the wheel built and installed in a clean venv. The Claude adapter's contract test passes, with model ids current. The migration path from every shipped schema tested | 🔶 ruff and mypy configured, clean (25 and 27 findings before) and in CI job `lint`; PEP 639 licence metadata; both wheels built and installed in a clean venv (`demo`, `doctor` sound); migration covered by the shipped-schema test. Live adapter call ⛔ X-API; its contract test runs in CI |
| G3 | Profile and improve the multi-agent workload. Publish measured supported capacity and latency limits | A profile attributing P12's latency to causes. A change that moves the measured numbers, re-measured at 10/50/100 agents on both backends. A supported-capacity table in the deployment docs, derived from the run | ✅ [P12b](../research/results/p12b-catch-up.md): profiled (95% full replays), incremental fold with a 500-seed equivalence test, 23×/32× at 100 agents, agent-api shape measured, limits in DEPLOYMENT §3. Open-loop load not measured |
| G4 | An independently designed adversarial benchmark against real models and fair baselines. Publish successes and failures | A scenario family not derived from DepotWorld or PoisonWorld templates. Real (local) models as the agents. At least two external-style baselines (a plain vector store; a framework-style memory). Pre-registered; failures published beside successes | ⬜ (frontier arm ⛔ X-API) |
| G5 | Finish the security review and deployment runbooks. No unresolved critical or high release blockers | Every threat-register row is closed, accepted with a reason, or a named blocker. Runbooks for install, upgrade, backup/restore, key rotation, erasure, incident and capacity. A findings table with severities, and zero open critical/high | ✅ [SECURITY_REVIEW.md](SECURITY_REVIEW.md): 10 findings, 3 high (F10, scope not enforced on reads, reopened and closed it), all fixed and tested; 0 open critical/high; runbooks in [RUNBOOKS.md](RUNBOOKS.md) |
| G6 | Final acceptance against a frozen release candidate. Tag only after the gates pass. A clear release note with limitations | An RC branch, the acceptance suite run against it, and a release note. The tag is created only when G1 is green | ⬜ (tag ⛔ X-CI) |

## Research directions

Each one starts with a real literature check: the citations in the request are
verified to exist, and what they establish is read, before a question is
registered.

| ID | Direction | Definition of done | Status |
|---|---|---|---|
| S1 | Federated semantic retraction with precise recovery | Registered question on convergence under partitions, replay, cycles and concurrent corrections. A harness extending `faultsim` and the transitive-retraction tests. Measured stale use and unnecessary invalidation, against baselines | ⬜ Includes: the protocol defines `verified` (origin-confirmed enforcement) and nothing sets it |
| S2 | Evidence independence under collusion and copy laundering | Transformed copies (paraphrase, summary, multi-store), with independent-but-similar reports as the control. Measured false corroboration against blocked independent evidence | ⬜ |
| S3 | A federated extension to memory-security benchmarks | Merged with G4: write → share → act → retract → recover across stores and offline recipients, scoring safety, success and valid-evidence retention together | ⬜ |
| S4 | Recipient-specific trust under changing context | Can a recipient estimate transferability from its own verified outcomes, without importing the sender's value score, and improve utility without more harmful reliance? Registered against B1's inconclusive result | ⬜ |
| S5 | Privacy-preserving correction receipts | A receipt that proves enforcement without revealing content or unrelated graph structure. A measured leakage analysis of what the receipts themselves reveal | ⬜ |
| S6 | Race-free authorization at external action time | A tested protocol coupling a fresh memory state to a tool side effect, including timeout and retry. Closes or bounds S14 | ⬜ |

## Product capabilities

| ID | Capability | Definition of done | Status |
|---|---|---|---|
| P1 | Memory governance console | One view per memory: source, history, status and confidence, and which agents and stores can reach it. Answers "why does this agent know this?" in the dashboard | ✅ memory page and `show`: source, versions, audit, status (P9), value with n_eff, and reach (`reach.py`: may read / has seen / other stores). Building it found F10 |
| P2 | Review queue for proposed memories | Approve, reject, correct or limit candidates before they spread, each decision logged with its reviewer | ✅ `review.py`: queue (candidates, screen quarantines, secrets redacted) and approve / limit / correct / reject, each naming its reviewer; `review` command; read-only Review tab with each item's commands |
| P3 | Safe correction and retraction | Preview the copies and dependents a change would touch, apply it, and see which stores confirmed | ✅ `correction.py`: preview (contested / still standing on independent support / copies / stores owed) computed by the rules quarantine uses — a 40-graph test checks preview = outcome; `correct --apply` owes every store; `--status` per store; on the memory page |
| P4 | Access and sharing controls | Attach or detach a collection to agents. Read, write, approve and retract permissions, audited | ✅ collections (schema 0.10.0): attach/detach agents, read/write/approve/retract grants enforced on the authenticated service path, every change an audited event; `collection` command; reach shows collection readers. Rests on scope enforced on reads (F10) |
| P5 | Integrations that fit existing stacks | At least two framework adapters with a policy boundary and a migration path, tested end to end | ✅ `integrations/`: function tools (OpenAI and Anthropic formats, dispatching to the MCP server's own handlers) and a LangChain retriever with `verify`, both at the agent-facing boundary; `import` from Mem0 / LangChain / plain exports as reviewable candidates. CI job `langchain-contract` |
| P6 | Security posture and audit export | Export decisions, changes, access events and deletion receipts. A posture page listing which controls are on and which gaps exist | ✅ `posture.py`: controls read from the live store plus the review's accepted gaps (`posture`, dashboard Posture tab); `audit-export` writes decisions / changes / access / deletion receipts as content-free JSONL ending with a chain checkpoint (tested: no content or secret leaves; the log verifies against it) |
| P7 | A low-friction first run | `init` with a guided setup and working demo, and a `doctor` that explains every failure in plain language with its fix | ⬜ |
| P8 | Lifecycle and deletion center | Retention rules, stale and sensitive finders, and deletion/revocation progress across stores | ⬜ |
| P9 | Honest, explainable status labels | Distinct labels: source recorded, reviewed, policy-checked, verified in destination. Each says what it does and does not establish, everywhere a memory is shown | ✅ `status.py`, on `show` and the dashboard; 'verified in destination' is self-reported because the protocol's `verified` state is never set (→ S1) |
| P10 | Guided incident response | Detect → show propagation → contain → retract → reviewable incident record, as one workflow | ⬜ |

## Last

| ID | Task | Definition of done | Status |
|---|---|---|---|
| M1 | **Memory objective**: before a session, state what counts as relevant and what as irrelevant, as rules given to the agent and to retrieval | Pre-registered against plain retrieval and an oracle on a family where relevance is decided by the objective, not by similarity. At least two ways of using the objective (prompt only; retrieval filter; both). Measured on real models | ⬜ |
