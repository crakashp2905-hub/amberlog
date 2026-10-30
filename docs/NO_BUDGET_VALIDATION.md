# Zero-budget validation

Owner constraints on 30 October 2026: no paid services, no package upload and
no public recruitment or outreach. These instructions prepare execution and
handoff; they do not identify a volunteer or claim an external acceptance.

## Reproduce the frozen engineering evidence

Use a clean checkout of the recorded commit, Python 3.11+ and existing Git
history including `v0.11.0`. No optional Python dependencies are required:

```bash
python tools/reproduce_readiness.py --out dist/independent-reproduction
```

The full profile runs focused regressions, the existing five-seed three-agent
comparison, mapped conformance, delayed network/reconnect checks in separate
processes and the historical upgrade/rollback drill. `--quick` omits the last
two drills. The tool captures commands, return codes, platform, Python, exact
source SHA, logs, deterministic outcome comparison and file hashes. It refuses
tracked modifications and nonempty output directories. Compare counts with
the frozen reference, not timings across machines.

`execution_status=PASS` means this execution matched the requested checks.
`independence=NOT_ESTABLISHED` and `release_decision=INCONCLUSIVE` remain so:
an implementer's rerun or a second CI job does not become independent review.
An outside reproducer must later return their identity/relationship declaration,
source SHA, exact commands, raw bundle and any differences. Do not send private
customer data, credentials or machine-identifying environment dumps.

## Run the local model rehearsal

Use an already-installed Ollama and already-cached `qwen2.5:1.5b` weights.
Start a task-owned loopback server with `OLLAMA_HOST=127.0.0.1:11439` and
`OLLAMA_NO_CLOUD=1`; do not change the user's system-wide configuration.

```bash
python -m experiments.no_budget_rehearsal --host http://127.0.0.1:11439 --model qwen2.5:1.5b --out dist/local-model-rehearsal.json
```

The code fixes five seeds before execution and calls the existing logged model
wrapper for inspector, planner and executor roles. The executor is measured
against cached evidence and a current-check prompt. Shared-current-metadata and
governed arms reuse the same model proposal. A truth oracle is reported.
Real model tokens, prompt hashes, decoding parameters, model digest, elapsed
call times, malformed outputs and all four joint outcomes are preserved.
The cached and host-recheck arms are descriptive decisions; only the governed
arm invokes the fenced in-process callback. No arm deploys anything externally.

This is a small synthetic shadow rehearsal, not a customer task, independent
held-out evaluation or pilot. There is no improvement threshold or supported
superiority claim. Model-call cash cost is zero; electricity and hardware costs
are not measured. Shut down the task-owned server after the run. The harness
rejects remote endpoints, missing weights and cloud-tagged models and never
downloads a model. Ollama configuration follows its
[official FAQ](https://docs.ollama.com/faq).

## Handoff requirements that still need another person or resource

| Gate | Prepared scope and acceptance | Current limitation |
|---|---|---|
| Independent security review | Freeze source SHA; assess tenant reads/writes, authority laundering, action races, replay, erasure/backup custody and transport; return private findings, exclusions and remediation retests | Reviewer not assigned; public recruitment on hold |
| Independent reproduction | Run the clean-checkout command above and return raw artifacts and a relationship declaration | No outside reproducer assigned |
| Separate physical hosts | Run the documented federation service on two owner-authorized machines over their real network; record operator-attested physical separation, latency, partitions and recovery | One local machine and hosted CI do not prove distinct physical hardware; no self-hosted runners registered |
| Real workflow and two pilots | Obtain consenting task/data owners; freeze tasks, baseline, correction schedule, safe actions, abort rules and joint metrics; run shadow mode before side effects | No participants enrolled; the local rehearsal is excluded |
| Customer-data upgrade | Obtain a sanitized, authorized staging copy plus separate key backup; preserve originals; record pre-upgrade invariants, migration, restoration and rollback | Synthetic rollback exists; no customer fixture supplied |
| Index ownership | Owner configures the pending publishers described in [publishing](PYPI_PUBLISHING.md); verify through signed-in index accounts | Account-side publisher ownership unverified; no credential sharing or upload |
| Naming and commercial rights | Owner resolves existing brand usage and licensing questions using the existing [review brief](product/LEGAL_PRIVACY_REVIEW_BRIEF.md) | No legal clearance, domain ownership or commercial permission invented |

## Private disclosure

GitHub private vulnerability reporting is enabled. Reports can use the
[private form](https://github.com/crakashp2905-hub/amberlog/security/advisories/new)
or the maintainer email in [SECURITY.md](../SECURITY.md). This configuration
accepts private submissions; it does not contact reviewers, offer a bounty or
change the owner's hold on outreach. See
[GitHub's configuration guidance](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).

Publication approvals remain false. No release is qualified by this document.

## Recorded execution

The [local-model result](../research/results/no-budget-local-model.md) records
five frozen cases and measured tokens, including false blocking. The
[replication summary](../research/results/no-budget-replication.json) and
[raw manifest](../research/results/no-budget-replication/manifest.json) preserve
the full-profile rerun: branding, credential scan, regressions, five-seed
outcome comparison, conformance, network recovery and rollback. All recorded
steps passed; outside independence, actual pilots and physical separation remain
NOT_ESTABLISHED or NOT_RUN. No outside person was contacted.
