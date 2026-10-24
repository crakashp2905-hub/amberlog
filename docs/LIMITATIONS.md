# Known limitations

What Memory Fabric does **not** do, or does only partly. Read this before
relying on it for something that matters. Anything fixed since is in the
[CHANGELOG](../CHANGELOG.md).

## Security

| limitation | what to do |
|---|---|
| **A plausible false claim about something the store has never seen, from a source with a clean record, looks like a true one.** Claims that restate a corrected value, are far out of range, or contradict an established fact *are* caught and held for review; a claim from a new source is marked provisional. | `memory-fabric suspicious` lists held claims. Require independent sources for consequential actions (`ToolRule(min_independent_sources=2)`). |
| **Claim checks read numbers and identifiers** (`P7`, and since 0.12.x codes with separators: `H-14`, `PMP_0012`, `K/31`). A free-text claim with no equipment id or value ("the east wing is safe") is not checked. | Review free-text memories that matter before validating them. |
| **A compromised established account can change its own facts.** If a reviewer had validated the old value, the change is marked provisional (`revises_validated`) until someone validates it; a fact nobody else vouched for still changes freely, as an honest update would. | Set `ToolRule(refuse_provisional=True)` on tools a compromised account must not drive. Revoke the credential (RUNBOOKS §1); `incident` shows what it wrote. |
| **The injection screens are text screens.** They catch common injection patterns and instructions addressed to the reader, not every paraphrase. | Treat them as a filter, not a guarantee. Review imports from untrusted sources (`review`). Untrusted content still cannot authorise an action at the gate. |
| **A source caught injecting is withheld everywhere its memories went**, which can also hide a correct note it wrote. Only an injection finding triggers it, never an ordinary correction. | `MemoryFabric(withhold_hostile_sources=False)` to turn it off; review the source's other memories with `incident`. |
| **An offline peer serves withdrawn knowledge until it reconnects.** A store cannot see through a partition. | For consequential tools, `ToolRule(require_fresh=True)` with a `LeaseBook`: imported evidence needs a signed, unexpired lease from its origin, so no action relies on a withdrawal more than one lease lifetime old (`freshness.py`). Watch `doctor` and `maintain --status` for pending deliveries. |
| **Tenancy within one store is an authorisation boundary.** Someone holding the database file or the process can read every tenant. | Pick an isolation pattern (DEPLOYMENT.md, tenant isolation patterns): store, process or host per tenant. |
| **A database administrator can rewrite the log and its hash chain together.** Tampering is detected only against a checkpoint kept elsewhere. | Anchor checkpoints off the host: `memory-fabric anchor --to git:... --to https://...` from cron, then `anchor --verify`. |
| **The action fence covers only tools run through `ActionGate.execute`.** `authorize` followed by acting separately leaves a window, and a crash mid-action records nothing. | Run protected tools through `execute`, and give them idempotency keys. |
| **Writers wait while a fenced action or a maintenance cycle holds the store**, up to about 2 seconds. | Keep tool calls short. Put agents behind one `agent-api` per store. |
| **Strict evidence independence** blocks some genuinely independent evidence along with false corroboration. | Off by default; turn it on only where corroboration is the main risk. |
| **No independent security review** has taken place. | Treat security properties as tested, not certified. |

## Retrieval and memory quality

| limitation | what to do |
|---|---|
| **It does not make answers more accurate than a good retriever.** It governs what is remembered; it does not find better memories. | Pair it with the best retriever you have (`Embedder`, rerankers). |
| **It rarely says "I don't know".** If nothing relevant is stored, retrieval returns the closest memories. | Use `min_relevance`, or check the scores before acting. |
| **The built-in hashing embedder is weak on real text.** | Plug in a real embedding model through the `Embedder` protocol. |
| **Model-compiled objectives can drop alternatives** a session needed. | State the objective in the agent's prompt; use compiled filters only after review. |
| **A session summary larger than the context budget is skipped, not shortened.** | Give handoffs a budget of at least ~80 words, or retrieve the session's notes directly. |

## Scope

- **Tested on one machine** for every performance figure, on Linux, macOS
  and Windows in CI for correctness.
- **Small local models** for the model-in-the-loop checks so far. The same
  checks run on Claude (`.github/workflows/frontier-eval.yml`) once an
  `ANTHROPIC_API_KEY` repository secret is set; they have not run yet.
- **Several physical machines** have not been measured; separate processes
  and separate containers have.
- **Not on PyPI** yet, pending a final name.
