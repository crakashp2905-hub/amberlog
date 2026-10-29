# Pre-registration — S6: no window between verifying evidence and acting on it

**Registered 2026-10-18, after a dev pilot (seeds 100–101) and before the
test seeds (0–4).** This is research direction S6 in
[WORKPLAN.md](../../docs/WORKPLAN.md), and it closes or bounds threat S14 in
[SAFETY_AND_SECURITY.md](../../docs/SAFETY_AND_SECURITY.md). Mechanism:
`ActionGate.execute` in `amberlog/actions.py` (schema 0.11.0). Harness:
`experiments/s6_race_sim.py`. Both are committed with this file.

**Disclosed: the dev pilot changed the harness.**

- The collision rate was raised (fewer memories, longer tools) until the race
  was observable at all. At the first settings, the product's own path
  violated in 1–3% of effects.
- A *targeted* timing was added, because a race-free claim has to survive
  the worst case and not only a random schedule.
- Targeting was made fair. It first aimed at `reverify`'s *first* check, which
  let its second check always win, so it now aims after each arm's last
  verification.
- The overrun tail was lengthened from 0.6 s to 1.5 s, because a starved
  writer could not land inside the shorter one.
- A late-bound closure in the harness was writing an overrunning tool's
  effect time into a later call's record. Fixed.

## 1. Question

With real processes on one store, does a protected action ever take effect
after a withdrawal of its evidence has committed? And what does preventing
that cost the store's writers?

## 2. Design (RaceSim)

The setup:

- Per seed, per timing and per arm, a fresh store file with active memories,
  each certifying one action.
- The actor makes 200 calls. Each side effect takes U(5, 40) ms, with U(1, 10)
  ms of think time between calls.
- A retractor in a separate process withdraws memories, with one of two
  timings:
  - **targeted (primary).** After each arm's last verification, the actor
    names the memory, and the retractor withdraws it at once with probability
    0.25. 60 memories.
  - **random.** Every memory once, one every U(0, 800) ms. 12 memories.

A **violation** is a side effect timestamped after its evidence's withdrawal
committed. The commit time is taken when `quarantine` returns, so violations
are undercounted and never overcounted.

## 3. Arms

| arm | path |
|---|---|
| `authorize_then_act` | `authorize`, then the tool (the product before S6) |
| `reverify` | `authorize`, 90% of the tool, `authorize` again, the remaining 10% |
| `fenced` | `execute`, lease 1.0 s |
| `fenced_overrun` | `execute`, lease 0.25 s; 5% of calls hang 1.5 s past the lease |

**Ceiling (8a).** The oracle has 0 violations. That is trivially reached by
never acting, so the bar (8c) is set on valid effects as well as violations.

## 4. Hypotheses (5 seeds, both timings)

- **S6a.** `fenced` has **0 violations in every seed and timing**, and its
  valid effects (effects that are not violations) are at least 90% of
  `authorize_then_act`'s.
  - **Validity:** if `authorize_then_act` has a violation in fewer than 5 of
    5 targeted seeds, the race was not exercised and S6a is INVALID.
- **S6b.** In `fenced_overrun`, every violation is in a call that timed out
  (0 outside overruns), and `unfenced_changes()` reports every one of them
  (recall 1.000).
- **S6c.** Zero writer failures in every fenced arm. Writers waited, but none
  gave up at the 5 s busy timeout.

## 5. Predictions

1. S6a, S6b and S6c hold.
2. `reverify` cuts violations but does not eliminate them under targeted
   timing (dev: 5.5% against 25.6%).
3. The fence's cost is on writers rather than throughput. Writer wait p95
   rises from about 5 ms to about 0.1–0.5 s, and the maximum approaches 1 s,
   because SQLite's busy handler is not fair to a writer facing a continuously
   acting agent. Actions per second drop by about 10% or less.
4. `unfenced_changes()` precision is below 1. It flags every withdrawal after
   the lease ran out, including ones that landed after the late effect,
   because the store cannot know when the effect happened.

## 6. What this would not establish

One machine, with one actor and one writer process. The tool is a sleep, not
an external system. A tool that keeps running after its lease and takes effect
elsewhere is outside the fence by construction; S6b only shows it is
reported. A crash mid-action records nothing (stated in `actions.py`).
Postgres is not tested: the fence relies on the store's write transaction,
and the Postgres path's locking was not exercised here.
