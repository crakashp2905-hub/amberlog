# Known limitations

What Memory Fabric does **not** do, or does only partly, with the evidence for
each. Read this before relying on it for something that matters. Every row
links to the measurement or the review that found it. Nothing here is
hypothetical, and anything that has since been fixed is in
[SECURITY_REVIEW.md](SECURITY_REVIEW.md), not here.

## Security

| limitation | evidence | what to do instead |
|---|---|---|
| **Paraphrased prompt injection passes the ingest screen.** The screen matches known injection forms. | G4: 0.05 safe success on paraphrased injection, against 1.00 on matched ([g4-labnet](../research/results/g4-labnet.md)) | Review imports from untrusted sources (`review`). Treat the screen as a filter, not a guarantee |
| **Before a poison is detected, retrieval can show it.** Nothing distinguishes an undetected false claim from a true one. | G4: the poison ranked first in 35/40 questions. Contradiction surfacing cuts acting on it from 63% to 51–55%, which is significant but not solved ([g4b](../research/results/g4b-contradiction-surfacing.md)) | Contradiction flagging (`conflicts.py`, opt-in); review conflicts the manager lists |
| **What the injection screen learns about a source stays in that store.** Other stores never hear that a source was caught injecting. | T2: the hostile signal never reaches the stores that answer questions ([t2](../research/results/t2-hindsight.md)) | Withdraw a hostile source's other shared memories explicitly (`incident`) |
| **Discrediting a source on any withdrawal punishes honest mistakes.** | T2: withholding cost an honest author 0.92 → 0.12 of their valid notes | Not enabled. `hindsight.py` stays experimental |
| **An offline peer serves withdrawn knowledge until it reconnects.** | G4 stage 2, by design | Watch `doctor` and `maintain --status` for pending deliveries; they are reported, never hidden |
| **Tenancy is logical.** A privileged database or process holder can read every tenant. | Threat model ([SAFETY_AND_SECURITY.md](SAFETY_AND_SECURITY.md)) | One store per tenant where isolation must survive an administrator |
| **A database administrator can rewrite the log and its hash chain together.** | The integrity chain detects tampering only against a checkpoint kept elsewhere | Run the manager with `--checkpoint-dir` on separate storage |
| **The action fence covers only tools run through `ActionGate.execute`.** `authorize` followed by acting still has a window. A crash mid-action records nothing. | S6 ([s6](../research/results/s6-action-fence.md)) | Run protected tools through `execute`. Give tools idempotency keys |
| **Writers wait while a fenced action or a maintenance cycle holds the store.** | S6: up to about 2 s. A cycle that delivers to a slow peer holds the lock for that delivery | Keep tool calls short. Run one `agent-api` per store |
| **Evidence independence trades false corroboration for blocked real evidence.** | S2: false corroboration 0.83 → 0.28, blocked independent evidence 0.02 → 0.25 ([s2](../research/results/s2-launder-sim.md)) | Not enabled by default |
| **No independent security audit.** The review is internal. | [SECURITY_REVIEW.md](SECURITY_REVIEW.md) | Treat claims as tested, not certified |

## Retrieval and memory quality

| limitation | evidence |
|---|---|
| **Better retrieval does not reliably beat a plain lexical baseline.** The project's accuracy claims were tested and mostly failed. | [SCORECARD §1–2](../research/SCORECARD.md) (H2, R6, P1) |
| **The fabric almost never says it does not know.** | LongMemEval, on 500 third-party questions ([longmemeval](../research/results/longmemeval.md)) |
| **The hashing embedder is weak on real text**: 0.315 nDCG@10 against lexical's 0.621. | SciFact ([scifact-external](../research/results/scifact-external.md)) |
| **Model-compiled objectives drop alternatives.** Compiled filters lose to stating the objective in the prompt. | M1 ([m1](../research/results/m1-memory-objective.md)) |
| **Self-revised rules improve slowly**, and without a gate they make agents worse. | M2 ([m2](../research/results/m2-reflective-rulebooks.md)) |

## Scope of the evidence

- **Most results come from worlds this project wrote** (LabNet, ObjectiveWorld,
  TransferSim and the others). They are independent of each other's templates,
  not of their author. The external datasets are listed in
  [INDEPENDENT_EVALUATION.md](INDEPENDENT_EVALUATION.md).
- **Small local models only**: qwen2.5:3b, gemma3:4b and similar. No
  frontier model has been evaluated (no API access in this environment).
- **One machine** for every performance number.
