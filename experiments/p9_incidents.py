"""P9 — incident reconstruction against a live counterfactual (plan Task 9).

Each synthetic incident is a store in which an agent took a gated action on
evidence derived, through a random justification structure, from several
source observations, with unrelated decoy memories retrieved alongside.
`incident.reconstruct` then reports the path and, for each source, whether the
evidence would have survived its withdrawal.

**Ground truth is not the reconstruction's own logic.** For every source, the
same incident is rebuilt from its seed in a fresh store, that source is
actually quarantined just before the action, and the real gate is asked again.
"Necessary" is true when the gate then refuses. So the measurement is how well
a read-only replay predicts what truth maintenance and the gate really do.

    python -m experiments.p9_incidents          # 200 incidents, writes the result
    python -m experiments.p9_incidents --quick  # 30, prints only

Not pre-registered: this measures a diagnostic tool's fidelity. It does not
test a hypothesis about outcomes, and it is reported as a measurement.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
from memory_fabric.incident import reconstruct
from memory_fabric.justification import JustificationKind, justification_context

WRITERS = ("ana", "ben", "cho", "dev", "mallory")
NOUNS = ("pump", "valve", "crane", "hoist", "winch", "tug", "genset", "loader")


def build(seed: int, withdraw: str | None = None) -> tuple[MemoryFabric, dict[str, Any]]:
    """One incident. With `withdraw`, that memory (by label) is quarantined
    immediately before the action."""
    rng = random.Random(seed)
    fabric = MemoryFabric(auto_activate=True, seed=seed)
    label: dict[str, str] = {}
    order: list[str] = []

    def put(name: str, memory_id: str) -> None:
        label[name] = memory_id
        order.append(name)

    n_roots = rng.randint(2, 5)
    for i in range(n_roots):
        noun = rng.choice(NOUNS)
        put(f"root{i}", fabric.remember(
            rng.choice(WRITERS), f"{noun} {i} reading {rng.randint(1, 99)} logged at bay {seed}-{i}", scope="team"))
    if rng.random() < 0.4:  # a verbatim forward of a root: a recognised copy
        src = rng.choice([n for n in order if n.startswith("root")])
        text = fabric.get(label[src]).content
        put("forward", fabric.remember(rng.choice(WRITERS), text, scope="team"))

    for j in range(rng.randint(1, 4)):
        pool = list(order)
        k = min(len(pool), rng.randint(1, 3))
        parents = rng.sample(pool, k)
        if k == 1:
            kinds = [rng.choice([JustificationKind.REQUIRED, JustificationKind.COPIED])]
        else:
            kinds = [rng.choice([JustificationKind.REQUIRED, JustificationKind.ALTERNATIVE])
                     for _ in parents]
        ids = [label[p] for p in parents]
        put(f"derived{j}", fabric.derive(
            rng.choice(WRITERS), f"conclusion {seed}-{j} from {len(ids)} inputs",
            parents=ids, context=justification_context(list(zip(ids, kinds))), scope="team"))

    for d in range(3):  # decoys: unrelated, retrieved alongside
        put(f"decoy{d}", fabric.remember("eve", f"canteen notice {seed}-{d} reopening hours", scope="team"))
    fabric.retrieve("actor", f"canteen notice {seed} conclusion", k=5)

    derived = [n for n in order if n.startswith("derived")]
    evidence = derived[-1:] if rng.random() < 0.6 else derived[-2:]
    # Ground truth is the registered rule, support under the recorded justification
    # structure (`incident.CAVEAT`). Origin-bound authority (added after P9 was
    # recorded) also refuses evidence with *any* withdrawn ancestor, alternatives
    # included; it is a separate check, switched off here so it does not redefine
    # "necessary". Found by tools/reverify.py.
    gate = ActionGate(fabric, ActionPolicy(
        tools={"act": ToolRule("act", min_authority="untrusted")}, grants={"actor": frozenset({"act"})}))
    if withdraw is not None:
        fabric.quarantine(label[withdraw], reason="counterfactual withdrawal",
                          basis="contradicted")
    cert = fabric.certify(f"incident-{seed}", [label[e] for e in evidence], "actor")
    decision = gate.authorize("act", "actor", cert)
    return fabric, {"label": label, "evidence": evidence, "allowed": decision.allowed}


def ancestors(fabric: MemoryFabric, ids: Sequence[str]) -> set[str]:
    out: set[str] = set()
    frontier = list(ids)
    while frontier:
        m = frontier.pop()
        if m in out:
            continue
        out.add(m)
        frontier.extend(fabric.state.parents.get(m, ()))
        if m in fabric.state.copy_of:
            frontier.append(fabric.state.copy_of[m])
    return out


def run(n: int) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    decoys_in_report = 0
    path_exact = 0
    timings: list[float] = []
    used = skipped = 0
    seed = 0
    while used < n:
        fabric, info = build(seed)
        if not info["allowed"]:
            fabric.close()
            seed += 1
            skipped += 1
            continue
        start = time.perf_counter()
        report = reconstruct(fabric)
        timings.append((time.perf_counter() - start) * 1000)
        by_id = {v: k for k, v in info["label"].items()}
        truth_path = ancestors(fabric, [info["label"][e] for e in info["evidence"]])
        if {nd.memory_id for nd in report.nodes} == truth_path:
            path_exact += 1
        decoys_in_report += sum(1 for nd in report.nodes if by_id[nd.memory_id].startswith("decoy"))
        for finding in report.sources:
            name = by_id[finding.memory_id]
            replica, rinfo = build(seed, withdraw=name)
            truly_necessary = not rinfo["allowed"]
            replica.close()
            if finding.necessary and truly_necessary:
                tp += 1
            elif finding.necessary:
                fp += 1
            elif truly_necessary:
                fn += 1
            else:
                tn += 1
        fabric.close()
        used += 1
        seed += 1
    flagged = tp + fp
    return {
        "incidents": used, "skipped_not_allowed": skipped,
        "sources_judged": tp + fp + fn + tn,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "precision": tp / flagged if flagged else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "false_attribution_rate": fp / flagged if flagged else 0.0,
        "decoys_in_any_report": decoys_in_report,
        "path_exact_share": path_exact / used,
        "reconstruct_ms_p50": statistics.median(timings),
        "reconstruct_ms_p95": statistics.quantiles(timings, n=20)[18],
    }


def to_markdown(r: dict[str, Any], commit: str) -> str:
    c = r["confusion"]
    return f"""# P9 — incident reconstruction against a live counterfactual

Produced by `python -m experiments.p9_incidents` at commit `{commit}`; raw
numbers in [p9-incidents.json](p9-incidents.json). A measurement of a
diagnostic tool, not a pre-registered hypothesis test.

**Method.** {r['incidents']} seeded synthetic incidents
({r['skipped_not_allowed']} seeds skipped because their action was refused, so
there was nothing to reconstruct). Each one has random REQUIRED, ALTERNATIVE and
COPIED structure, recognised copies, and decoys retrieved alongside the
evidence. `incident.reconstruct` replays the log up to the action, read-only,
and predicts for each source whether the evidence survives its withdrawal.
**Ground truth is a live re-run:** the incident is rebuilt from its seed, the
source is really quarantined before the action, and the real gate decides.

| measure | value |
|---|---|
| sources judged | {r['sources_judged']} |
| "necessary" precision | {r['precision']:.3f} |
| "necessary" recall | {r['recall']:.3f} |
| false attribution rate (flagged but not necessary) | {r['false_attribution_rate']:.3f} |
| confusion (tp / fp / fn / tn) | {c['tp']} / {c['fp']} / {c['fn']} / {c['tn']} |
| decoys appearing in any report | {r['decoys_in_any_report']} |
| reconstructed path equals the true ancestor set | {r['path_exact_share']:.1%} |
| reconstruction time p50 / p95 | {r['reconstruct_ms_p50']:.2f} / {r['reconstruct_ms_p95']:.2f} ms |

**The first evaluator was wrong, and this measurement is what showed it.**
It treated a COPIED premise as required and ignored the independence of
alternatives. On the first 30 incidents it scored precision 0.804, recall 0.974
and false attribution 0.196 (9 sources flagged that the live system did not
need). It now mirrors `JustificationGraph.recompute` rule for rule. The
agreement above is therefore a measure of how faithfully the read-only replay
mirrors the live system. It is not independent evidence that the rules
themselves are right.

**Why seeds are skipped.** A derivation whose only premise is COPIED is
contested at write by design, because a copy carries no support of its own.
Seeds whose action rests on one are refused before there is anything to
reconstruct.

**Limits.** Synthetic structures generated by this repository, with one
withdrawal at a time. Interactions between several withdrawals are not
measured. "Necessary" is a dependency property under the recorded
justification structure. It is not a causal finding about the outcome, and
the report says so in every output (`incident.CAVEAT`).
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)
    result = run(30 if args.quick else 200)
    print(json.dumps(result, indent=2))
    if not args.quick:
        import subprocess
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True).stdout.strip() or "unknown"
        out = Path(__file__).resolve().parent.parent / "research" / "results"
        (out / "p9-incidents.json").write_text(json.dumps({**result, "commit": commit}, indent=2) + "\n")
        (out / "p9-incidents.md").write_text(to_markdown(result, commit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
