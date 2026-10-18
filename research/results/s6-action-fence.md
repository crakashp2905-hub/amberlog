# S6 result — the action fence: **SUPPORTED** (S6a, S6b, S6c)

Registration: [prereg/s6-action-fence.md](../prereg/s6-action-fence.md)
(`c0ef841`, after a disclosed dev pilot). Mechanism: `ActionGate.execute`.
Run: `python -m experiments.s6_race_sim --seeds 5` in a worktree pinned at
`c0ef841`. Seeds 0–4, 8 runs per seed (4 arms × 2 timings), real processes on
a real store file. Raw output: [s6-race-sim.json](s6-race-sim.json).

**Disclosed: the machine was not idle.** The G4 model run (Ollama, `gemma3:4b`)
was running throughout. That affects the latency and throughput numbers. It
cannot affect whether the fence admits a violation, which is structural.

## Results

**Targeted timing (primary).** The withdrawal is aimed at the moment after
each arm's last verification:

| arm | effects | violations | rate | seeds with one | writer wait p95 (max over seeds) | writer wait max | actions/s |
|---|---|---|---|---|---|---|---|
| `authorize_then_act` (the product before S6) | 662 | **188** | **0.284** | 5/5 | 0.006 s | 0.010 s | 26.8 |
| `reverify` | 662 | 69 | 0.104 | 5/5 | 0.005 s | 0.008 s | 25.5 |
| **`fenced`** | 677 | **0** | **0.000** | **0/5** | 0.559 s | 1.868 s | 23.7 |
| `fenced_overrun` | 671 | 15 | 0.022 | 5/5 | 0.543 s | 1.843 s | 19.8 |

**Random timing:**

| arm | effects | violations | rate | writer wait p95 | writer wait max | actions/s |
|---|---|---|---|---|---|---|
| `authorize_then_act` | 526 | 3 | 0.006 | 0.007 s | 0.018 s | 29.7 |
| `reverify` | 501 | 0 | 0.000 | 0.051 s | 0.061 s | 28.4 |
| **`fenced`** | 552 | **0** | **0.000** | 0.407 s | 1.352 s | 24.9 |
| `fenced_overrun` | 529 | 15 | 0.028 | 0.971 s | 2.391 s | 23.0 |

Overruns:

| timing | overruns | flagged by `unfenced_changes` | violations | violations flagged | precision |
|---|---|---|---|---|---|
| targeted | 38 | 23 | 15 | **15** | 0.65 |
| random | 29 | 29 | 15 | **15** | 0.52 |

## Hypotheses

- **S6a: holds.** `fenced` had 0 violations across 1,229 effects, in every
  seed and both timings. Its valid effects were above
  `authorize_then_act`'s: 677 against 474 under targeted timing. The validity
  check holds: `authorize_then_act` violated in 5/5 targeted seeds, so the
  race was exercised.
- **S6b: holds.** All 30 `fenced_overrun` violations were in calls that timed
  out (0 outside overruns), and `unfenced_changes()` reported all 30
  (recall 1.000).
- **S6c: holds.** Zero writer failures in every arm. The longest a writer
  waited was 2.4 s, against a 5 s busy timeout.

## Predictions

1. *S6a–c hold.* **Held.**
2. *`reverify` cuts violations without eliminating them.* **Held.** Under
   targeted timing: 0.104 against 0.284. A second check shrinks the window and
   does not close it.
3. *The cost falls on writers, at ≤ 10% of throughput.* **Partly wrong.**
   - Writer wait rose as predicted, from about 5 ms to a p95 of 0.4–0.6 s.
   - The maximum was **1.9 s**, not "approaching 1 s".
   - Throughput fell **12% (targeted) and 16% (random)**, not ≤ 10%.
   - The reason is the one the registration named: SQLite's busy handler is
     not fair, so a writer facing an agent that acts continuously misses the
     gaps between fences.
4. *`unfenced_changes()` has precision below 1.* **Held: 0.52–0.65.** It flags
   every withdrawal after the lease ran out, including ones that landed after
   the late effect, because the store cannot know when the effect happened.

## What changed

- **Threat S14 moves from "accepted residual race" to controlled for tools
  run through `execute`.** The window is closed for the fenced path. On a
  lease overrun it is bounded and every instance is reported. `authorize` +
  act still has the window, and `SAFETY_AND_SECURITY.md` says so.
- **The fence has a real cost on writers.** A deployment whose agents act
  continuously will see retractions wait up to about 2 s. That is under the
  busy timeout here, but not far under it.
  - **Not tested:** a fairness gap between fences, which would trade
    actions per second for writer latency.
  - **Not tested:** the Postgres path.
  - Both are stated in the registration.

## What this does not establish

One machine, one actor and one writer process. The tool is a sleep, not an
external system. A crash mid-action records nothing; the idempotency key is
how the tool deduplicates a retry.
