# Pre-registration — L1: a long-running task, a plain vector store against Memory Fabric

**Registered 2026-10-25**, before `experiments/l1_long_running.py` existed.

## 1. Question

Over a long task where facts are corrected while agents keep working, how many
actions are taken on a value that is no longer true, and how long after a
correction does that keep happening? This is the number a buyer asks for. It
is measured against how teams use a vector store today, with the honest
ceiling beside it.

## 2. World (deterministic, seeds 1–5)

- 40 pieces of equipment `E-1`…`E-40`, each with one setpoint (an integer).
  Each starts as one memory: "E-12 setpoint is 47.", written by an inspector.
- 600 steps. At each step one of four worker agents takes a job on a random
  piece of equipment: it recalls what is known about that equipment's
  setpoint, acts on the value of the top memory that states one, and, with
  probability 0.35, writes a working note that restates the value it used,
  in its own words ("Shift plan: run E-12 at setpoint 47.").
- 16 corrections at random steps: the true setpoint of a random piece of
  equipment changes. A supervisor records the new value and withdraws the
  memory they know is wrong (the inspector's original). Supervisors do not
  know which working notes restated it; nobody does in the baselines.
- **Harmful action:** an action whose value differs from the truth at the
  step it was taken.
- **Recovery time** for a correction: steps from the correction to the last
  harmful action using that equipment's superseded value (0 if none).

Retrieval is the same lexical ranking (`LexicalIndex`) in every arm, so the
arms differ only in what they do with corrections and evidence.

## 3. Arms

| arm | on correction | when acting |
|---|---|---|
| `vector_append` | add the new value as a new memory | act on the top hit |
| `vector_replace` | replace the original's text in place (update-in-place memory layers) | act on the top hit |
| `fabric` | `correction.apply` on the original, then record the new value; notes are written with `derive` from the memory used | act through `ActionGate` with that memory as evidence; if refused, recall again and retry once |
| `fabric_no_lineage` | as `fabric`, but notes are written with `remember` (no parent recorded) | as `fabric` |
| `oracle` | — | acts on the true value; same steps, same job sequence |

`fabric_no_lineage` is there because `fabric`'s advantage depends on agents
recording what a note was built from. Without that, only restatement
detection is left, and the result should say how much that alone buys.

## 4. Metrics and thresholds

Primary: **harmful actions per 1,000 actions.** Secondary: mean recovery time;
**completion** (actions taken with the true value, over jobs). Blocking every
action scores zero harm, so completion is the degenerate check (8c).

- **8c, before `fabric` runs:** if a baseline's harm is already within 1 per
  1,000 of the oracle's 0, the metric is not measuring anything and L1 is
  abandoned.
- **L1a (harm):** `fabric`'s harm is at most **50% of the better baseline's**
  (it removes at least half the headroom to the oracle), in all five seeds.
- **L1b (no degenerate win):** `fabric`'s completion is not more than **5
  points** below the better baseline's, mean over seeds.
- **L1c (recovery):** `fabric`'s mean recovery time is lower than the better
  baseline's in at least four of five seeds.
- `fabric_no_lineage` is reported against the same bars, with no claim
  registered for it.

**Ceiling check on every run (8b):** an arm with negative harm or with
completion above the oracle's invalidates the run.

## 5. What this does not show

A simulation with known answers, not agents with models: it measures the
mechanism under a stated pattern of corrections and restatements, not how
often real agents restate values. The 0.35 note rate and the lexical
retriever are choices, stated here, not tuned.
