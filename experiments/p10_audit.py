"""P10 — where to spend verification: periodic, event-triggered, risk-budgeted.

Plan Task 10. Each seed builds a store with ordinary traffic and four planted
problems, plus benign look-alikes that a naive trigger also fires on:

| planted problem (ground truth) | benign look-alike |
|---|---|
| a compromised agent's write burst, later found writing false claims | an honest agent's batch import |
| a high-impact action whose evidence is withdrawn afterwards | high-impact actions whose evidence stays good |
| a retraction that a peer never acknowledges | (none) |
| an unresolved contradiction | a contradiction resolved quickly |

The three policies get the same auditor (`memory_fabric/auditor.py`, read-only)
and differ only in which subjects they audit, and when. A problem counts as
detected when an audit of its subject returns a finding.

    python -m experiments.p10_audit           # 10 seeds, writes the result
    python -m experiments.p10_audit --quick   # 2 seeds, prints only

Not pre-registered: a comparison of policies for a diagnostic tool. It tests
no hypothesis about outcomes and is reported as a measurement.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence

from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
from memory_fabric.auditor import SAMPLE, Auditor, Trigger
from memory_fabric.certificates import CHECK_INDEPENDENT_SUPPORT
from memory_fabric.outbox import MAX_ATTEMPTS, now_ms

STEPS = 200
WINDOW = 20
BUDGET = 3
AGENTS = [f"a{i}" for i in range(8)]
SEEDS = tuple(range(10))


def build(seed: int) -> tuple[MemoryFabric, list[tuple[int, int, set[str]]], dict[int, int]]:
    """Returns the store, the ground-truth problems as (step, seq, subjects),
    and a map from step to log head at the end of that step."""
    rng = random.Random(seed)
    f = MemoryFabric(auto_activate=True, seed=seed)
    gate = ActionGate(f, ActionPolicy(
        tools={"override": ToolRule("override", min_independent_sources=2,
                                    required_checks=(CHECK_INDEPENDENT_SUPPORT,))},
        grants={"ops": frozenset({"override"})}))
    problems: list[tuple[int, int, set[str]]] = []
    head_at: dict[int, int] = {}
    compromised: list[str] = []
    n = 0

    def write(agent: str, text: str) -> str:
        nonlocal n
        n += 1
        return f.remember(agent, f"{text} #{seed}-{n}")

    def act(evidence: list[str]) -> int:
        decision = gate.authorize("override", "ops", f.certify("c", evidence, "ops"))
        assert decision.allowed
        return f.log.head_seq

    for step in range(STEPS):
        for _ in range(rng.randint(0, 2)):
            write(rng.choice(AGENTS), f"routine reading {rng.randint(1, 999)} at bay {rng.randint(1, 40)}")
        if step == 30:
            a, b = write("a1", "pump 4 runs 3 bar"), write("a3", "pump 4 runs 5 bar")
            f.challenge([a, b], evidence="conflicting pressure")
        if step == 34:
            open_set = next(s for s in f.state.hypothesis_sets.values() if not s.resolved)
            f.resolve(open_set.id, sorted(open_set.memory_ids)[0], design={"method": "re-measured"}, results={"bar": 3}, actor="sup")
        if step == 40:  # benign batch import
            for i in range(14):
                write("a2", f"imported manual page {i}")
        if step in (60, 90, 150):  # benign high-impact actions
            act([write("a4", f"gauge A reading {step}"), write("a5", f"gauge B reading {step}")])
        if step == 80:  # compromised burst
            for i in range(16):
                compromised.append(write("a7", f"bulletin {i}: clearance is 9.9 m"))
        if step == 100:  # unresolved contradiction
            a, b = write("a1", "crane 2 max 10 t"), write("a6", "crane 2 max 14 t")
            f.challenge([a, b], evidence="conflicting rating")
            hs = next(s for s in f.state.hypothesis_sets.values()
                      if not s.resolved and a in s.memory_ids)
            problems.append((step, f.log.head_seq, {hs.id}))
        if step == 120:  # high-impact action resting on a compromised write
            seq = act([compromised[3], write("a5", "gauge B reading 120")])
            problems.append((step, seq, {str(seq)}))
        if step == 140:  # a retraction a peer never acknowledges
            target = write("a6", "valve 3 setting 7")
            r = f.request_retraction(target, reason="wrong", recipients=["st_" + "9" * 26],
                                     actor="a6")
            row = next(x for x in f.outbox.due(now_ms() + 10**12) if x.retraction_id == r.retraction_id)
            for _ in range(MAX_ATTEMPTS):
                f.outbox.record_attempt(row, now_ms(), "connection refused")
                row = f.outbox._row(f.outbox._conn.execute(
                    "SELECT * FROM outbox WHERE id = ?", (row.id,)).fetchone())
            assert row.state.value == "failed", row.state
            problems.append((step, f.log.head_seq, {f"{r.retraction_id}->{row.recipient}"}))
        if step == 170:  # the compromise is found: the writer's claims withdrawn
            for mid in compromised:
                f.quarantine(mid, reason="writer compromised", basis="contradicted", actor="sec")
            problems.append((80, f.log.head_seq, {"a7"}))
        head_at[step] = f.log.head_seq
    return f, problems, head_at


def simulate(policy: str, seed: int, budget: int = BUDGET) -> dict[str, Any]:
    f, problems, head_at = build(seed)
    auditor = Auditor(f)
    rng = random.Random(1000 + seed)
    detected: dict[int, int] = {}
    audits = flags = benign_flags = events_read = 0
    seen: set[tuple[str, str]] = set()
    truth_subjects = [s for _, _, s in problems]
    for end in range(WINDOW - 1, STEPS, WINDOW):
        # The auditor sees the log as of this step: later events do not exist yet.
        limit = head_at[end]
        triggers = [t for t in auditor.scan() if t.seq <= limit
                    and (t.kind, t.subject) not in seen]
        if policy == "event_triggered":
            chosen = triggers
        elif policy == "risk_budgeted":
            chosen = sorted(triggers, key=lambda t: (-t.risk, t.seq))[:budget]
        else:  # periodic: random subjects from the window, no triggers
            agents = sorted({m.provenance.created_by for m in f.state.memories.values()})
            actions = [str(e.seq) for e in f.log.read_types(["ActionGated"]) if e.seq <= limit]
            pool = agents + actions
            chosen = [Trigger(SAMPLE, s, limit, 0.1) for s in rng.sample(pool, min(budget, len(pool)))]
        for t in chosen:
            if policy != "periodic":
                seen.add((t.kind, t.subject))
            result = auditor.audit(t)
            audits += 1
            events_read += result.events_read
            if not result.finding:
                continue
            flags += 1
            hit = False
            named = {t.subject, *result.related}
            for i, subjects in enumerate(truth_subjects):
                if named & subjects and problems[i][1] <= limit:
                    detected.setdefault(i, end)
                    hit = True
            if not hit:
                benign_flags += 1
    f.close()
    delays = [detected[i] - problems[i][0] for i in detected]
    return {"detected": len(detected), "problems": len(problems), "audits": audits,
            "flags": flags, "benign_flags": benign_flags, "events_read": events_read,
            "delay_steps": delays}


def run(seeds: Sequence[int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, policy, budget in (("periodic", "periodic", BUDGET),
                                 ("event_triggered", "event_triggered", BUDGET),
                                 ("risk_budgeted", "risk_budgeted", BUDGET),
                                 ("periodic_budget_1", "periodic", 1),
                                 ("risk_budgeted_budget_1", "risk_budgeted", 1)):
        rows = [simulate(policy, s, budget) for s in seeds]
        delays = [d for r in rows for d in r["delay_steps"]]
        out[name] = {
            "detection_rate": sum(r["detected"] for r in rows) / sum(r["problems"] for r in rows),
            "audits_per_seed": statistics.mean(r["audits"] for r in rows),
            "benign_flags_per_seed": statistics.mean(r["benign_flags"] for r in rows),
            "events_read_per_seed": statistics.mean(r["events_read"] for r in rows),
            "median_delay_steps": statistics.median(delays) if delays else None,
        }
    return {"seeds": list(seeds), "steps": STEPS, "window": WINDOW, "budget": BUDGET,
            "policies": out}


def to_markdown(r: dict[str, Any], commit: str) -> str:
    rows = "\n".join(
        f"| `{p}` | {v['detection_rate']:.0%} | {v['median_delay_steps'] if v['median_delay_steps'] is not None else '—'} "
        f"| {v['audits_per_seed']:.1f} | {v['benign_flags_per_seed']:.1f} | {v['events_read_per_seed']:.0f} |"
        for p, v in r["policies"].items())
    return f"""# P10 — periodic, event-triggered and risk-budgeted auditing

Produced by `python -m experiments.p10_audit` at commit `{commit}`; raw numbers
in [p10-audit.json](p10-audit.json). {len(r['seeds'])} seeds, {r['steps']} steps,
audits every {r['window']} steps, a budget of {r['budget']} audits a window for the
budgeted policies, and a second run at a budget of 1, where the budget binds. Not pre-registered: a measurement of a diagnostic tool.

The auditor is **observation only**. It writes nothing, and no check consults
it. "Benign flags" are audits that returned a finding on a subject that was not
a planted problem. Each would be an operator's wasted look, never an automatic
quarantine, because nothing quarantines automatically.

| policy | problems detected | median delay (steps) | audits a seed | benign flags a seed | events read a seed |
|---|---|---|---|---|---|
{rows}

**Reading.** Blind periodic sampling spends the most reading and finds the
fewest problems. Event-triggered and risk-budgeted auditing find the same
problems here. At a budget of 3 the risk-budgeted policy did not use its whole
allowance, because there were fewer triggers than that. The budget-1 rows show
the trade once the budget binds. Delays are long for the compromised writer:
its burst is flagged at once, but the audit finds nothing wrong until its
claims are withdrawn. A burst alone is not evidence of compromise, and the
auditor does not treat it as such.

**Limits.** Four planted problems a seed, all of kinds the triggers were
written for. That measures how the policies spend a budget on known signals.
It says nothing about problems no trigger describes. A periodic audit can find
those in principle, and here it mostly does not, because it samples blindly.
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)
    result = run(SEEDS[:2] if args.quick else SEEDS)
    print(json.dumps(result, indent=2))
    if not args.quick:
        import subprocess
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True).stdout.strip() or "unknown"
        out = Path(__file__).resolve().parent.parent / "research" / "results"
        (out / "p10-audit.json").write_text(json.dumps({**result, "commit": commit}, indent=2) + "\n")
        (out / "p10-audit.md").write_text(to_markdown(result, commit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
