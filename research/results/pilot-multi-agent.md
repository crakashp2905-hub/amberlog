# Multi-agent pilot: three real Claude agents, one agent-api, one correction

Produced by `python -m experiments.pilot_multi_agent --runs 3` at commit `de5c715`;
raw record in [pilot-multi-agent.json](pilot-multi-agent.json), with the two earlier
versions kept: [v1](pilot-multi-agent-v1-validate-only.json),
[v2](pilot-multi-agent-v2-before-verify-fix.json). A deployment rehearsal, not an
experiment: there are no thresholds, and the point is the record of what failed.

The setup: one `memory-fabric agent-api` process and three Claude agents (Claude Code
headless, `curl` only), each with its own credential. **Inspector** stores facts
from field notes. A reviewer script validates them. **Planner** answers a
maintenance question from memory. **Operator** withdraws the relief-setting fact
through the CLI, in its own process. **Executor** must verify everything the
plan relies on before confirming it.

## v3 (current): the documented review flow, after the verify fix

| run | facts written | shared | plan used the later-withdrawn value | executor's verify of it | executor's verdict | failures recorded |
|---|---|---|---|---|---|---|
| 0 | 4 | 4 | yes | refused | not confirmed | none |
| 1 | 5 | 5 | yes | refused | not confirmed | none |
| 2 | 4 | 4 | yes | refused | not confirmed | none |

Cost: $0.15 for three runs.

## What failed on the way, and what changed

**v1, the reviewer validated but did not share.** Memories written through the
agent API are private to their author, and validating does not widen them. So
the planner recalled **nothing** in all three runs and correctly said it could
not answer. This is a workflow trap for teams, now written into OPERATIONS (§4a):
a team needs a reviewer who validates **and** shares (`share <id> team`). v1's
harm check also flagged a confirmation of a plan that rested on nothing as
harm. That was my error, and the check now looks for the withdrawn value.

| run | facts written | shared | plan used the later-withdrawn value | executor's verify of it | executor's verdict | failures recorded |
|---|---|---|---|---|---|---|
| 0 | 5 | — | no | never refused | CONFIRMED | executor never had the withdrawn memory refused (it did not verify it, or the refusal was not logged); executor CONFIRMED a plan resting on a withdrawn fact |
| 1 | 5 | — | no | never refused | not confirmed | executor never had the withdrawn memory refused (it did not verify it, or the refusal was not logged) |
| 2 | 5 | — | no | never refused | not confirmed | executor never had the withdrawn memory refused (it did not verify it, or the refusal was not logged) |

**v2, the verify gap: a product defect, fixed.** With sharing in place the
planner answered from memory, and its plan used the 12-bar setting, which was
correct when written. After the operator withdrew it, the executor's `mf verify`
of that memory returned "recall or fetch this memory before verifying it".
A withdrawn memory no longer comes back from recall, so the API never said
"withdrawn". Two runs inferred it from silence, and only the run that happened
to try `fetch` got an explicit refusal. Every executor still declined to
confirm, but on weaker grounds than it should have had.

| run | facts written | shared | plan used the later-withdrawn value | executor's verify of it | executor's verdict | failures recorded |
|---|---|---|---|---|---|---|
| 0 | 5 | 5 | yes | never refused | not confirmed | executor never had the withdrawn memory refused (it did not verify it, or the refusal was not logged) |
| 1 | 5 | 5 | yes | never refused | not confirmed | executor never had the withdrawn memory refused (it did not verify it, or the refusal was not logged) |
| 2 | 4 | 4 | yes | refused | not confirmed | none |

The fix (commit `0b09045`): `verify` on a memory the agent holds no token for
now fetches it under the agent's own permission check. A withdrawn memory comes
back `usable: false` with its reason, and unknown or other-tenant ids keep the
same opaque answer. In v3 the executor got the explicit refusal in every run.

**Not shown.** One task shape, three runs, one model family, one machine, a
permissive scripted reviewer, and no human in the loop. This is a rehearsal
that found two real problems, not evidence of reliability in production.
