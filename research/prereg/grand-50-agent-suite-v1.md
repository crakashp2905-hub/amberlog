# Grand 50-agent suite v1 — confirmation protocol

Registered after the exploratory 50-agent TeamWorld run and the compact
LongMemEval oracle run. Those observations are development evidence only and
cannot confirm this protocol. Confirmation uses unseen TeamWorld seeds
101–105 and LongMemEval's full-history `s` split.

## Question

Can Memory Fabric support 50 independently identified agents while improving
decision quality under changing and adversarial evidence, without buying
safety by refusing useful evidence?

## Fixed workloads

1. **Externally authored long memory:** a stratified 100-instance qualification
   run from LongMemEval `s`, followed by all 500 instances if qualification
   completes without harness errors. Arms: lexical, hybrid, oracle; `k=10`.
2. **Changing-evidence team:** TeamWorld, 50 agents, 60 rounds, seeds 101–105.
   Arms: isolated, plain shared, blanket invalidation, Memory Fabric, oracle.
3. **Authenticated service load:** 50 agents, 20 operations each, one agent API,
   SQLite, 200 team-visible seed memories. Every run must contain remember,
   recall, and fetch-plus-verify operations or it is invalid.
4. **Security and governance:** the repository adversarial gate, including
   action, tenant, retraction, injection, and governed-code families.

## Primary acceptance rules

- No stale action in the Memory Fabric TeamWorld arm.
- Memory Fabric task success must exceed the best non-oracle baseline and close
  at least 40% of measured baseline-to-oracle headroom. If a baseline reaches
  the oracle, the comparison is abandoned rather than called a failure.
- False blocking (`valid_evidence_withheld`) must be at most 5%.
- LongMemEval hybrid turn recall must exceed lexical turn recall on the same
  instances and budget. Correct abstention is reported separately and has no
  pass threshold because the exploratory result showed the current mechanism
  is not calibrated.
- The 50-agent API run must complete all 1,000 logical operations with zero
  errors, exercise all three operation families, sustain at least 100 logical
  operations/s, and keep p99 below 1,500 ms on the recorded machine.
- The adversarial gate must report zero critical family failures.

## Required reporting

Bind results to commit, dirty-worktree state, dataset filename and SHA-256,
machine, Python version, seeds, agent count, operation mix, wall time, and every
metric above. Report failures and invalid runs beside successes. Deterministic
agents measure the memory system, not model reasoning; a real-model arm remains
separate and requires a named model, prompt hash, token count, and cost.
