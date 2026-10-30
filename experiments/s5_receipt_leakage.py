"""S5 -- what does a correction acknowledgement tell the origin about the recipient?

Deterministic, no model. Per seed, 30 recipient stores, each drawn with:
  activity   events it writes between two retractions, 0..300
  copies     imports of the retracted memory it holds, 1..3
  peers      stores it re-shared its copy to, 0..3
  dependents conclusions it derived from its copy, 0..3

Each recipient receives two retractions from the origin, separated by its
activity. The origin keeps what comes back: today's `Acknowledgement`, or an S5
`CorrectionReceipt`. An honest-but-curious origin then tries to infer each
attribute from them. Every attacker sees every field of what it was sent:

  parse   rules written for the acknowledgement's fields (state_revision
          difference; the counts in `detail`)
  length  the serialised length of what was sent
  byte    the first byte of every hex field

For each attribute the best attacker is scored, leave-one-out over the
population: accuracy advantage over always guessing the most common value
(categorical), or R^2 (activity).

Soundness: every recipient also has a lying twin of three kinds -- never
applied (sends a receipt anyway), forged commitment, applied then re-activated
-- and audit must catch the first two and report the third.

    python -m experiments.s5_receipt_leakage --seeds 5 --out s5.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

RECIPIENTS = 30
PEER = b"origin-recipient-peer-key"
ATTRIBUTES = ("activity", "copies", "peers", "dependents")


def store() -> Any:
    from memory_fabric import MemoryFabric
    from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                                   rule_must_be_active,
                                                   rule_restricted_stays_private)

    return MemoryFabric(":memory:", auto_activate=True, firewall=Firewall(rules=(
        rule_restricted_stays_private, rule_must_be_active, rule_capabilities_must_be_granted)))


def one_recipient(rng: random.Random, n: int) -> dict[str, Any]:
    from memory_fabric.federation import offer
    from memory_fabric.model import Scope
    from memory_fabric.receipts import CorrectionReceipt, ReceiptError, audit, issue

    truth = {"activity": rng.randint(0, 300), "copies": rng.randint(1, 3),
             "peers": rng.randint(0, 3), "dependents": rng.randint(0, 3)}
    binding = f"binding-{n}-{rng.random()}".encode()
    origin, rec = store(), store()
    downstream = [store() for _ in range(truth["peers"])]
    sent: dict[str, list[Any]] = {"ack": [], "receipt": []}
    soundness: dict[str, bool] = {}
    for round_ in range(2):
        mid = origin.remember("ana", f"Instrument {n}-{round_} runs at {rng.randint(2, 9)} bar.",
                              scope="team")
        origin.share(mid, Scope.FEDERATED, actor="op")
        copies = [offer(origin, mid, rec, recipient_agent=f"agent{c}", activate=True)
                  .imported_memory_id for c in range(truth["copies"])]
        for c, copy in enumerate(copies):
            assert copy is not None
            rec.share(copy, Scope.FEDERATED, actor="op") if c == 0 and downstream else None
        for d in downstream:
            offer(rec, copies[0], d, recipient_agent="down", activate=True)
        for k in range(truth["dependents"]):
            rec.derive("local", f"Conclusion {k} about instrument {n}-{round_}.",
                       parents=[copies[k % len(copies)]], scope="team")
        if round_ == 1:
            for i in range(truth["activity"]):
                rec.remember("busy", f"Unrelated observation {n}-{i}.", scope="team")
        retraction = origin.request_retraction(mid, reason="wrong",
                                               recipients=[rec.store_id], actor="op")
        sent["ack"].append(rec.receive_retraction(retraction).to_json())
        receipt = issue(rec, retraction.retraction_id, binding_key=binding, peer_key=PEER)
        sent["receipt"].append(receipt.to_json())
        if round_ == 1:
            soundness["honest_passes"] = audit(rec, receipt, binding).ok
            forged = CorrectionReceipt(**{**receipt.__dict__, "commitment": "%064x" % rng.getrandbits(256)})
            soundness["forged_caught"] = not audit(rec, forged, binding).ok
            liar = store()
            claimed = CorrectionReceipt(**{**receipt.__dict__, "recipient_store_id": liar.store_id})
            soundness["never_applied_caught"] = not audit(liar, claimed, binding).ok
            try:
                issue(liar, retraction.retraction_id, binding_key=binding, peer_key=PEER)
                soundness["never_applied_cannot_issue"] = False
            except ReceiptError:
                soundness["never_applied_cannot_issue"] = True
            liar.close()
            rec.release(copies[0], actor="op")
            if rec.get(copies[0]).lifecycle_state.value != "active":
                rec.validate(copies[0], actor="op")
            reactivated = audit(rec, receipt, binding)
            soundness["reactivation_reported"] = copies[0] in reactivated.reactivated_since
    for s in (origin, rec, *downstream):
        s.close()
    return {"truth": truth, "sent": sent, "soundness": soundness}


# --- the attackers ---------------------------------------------------------------

def parse_features(sent: list[dict[str, Any]]) -> dict[str, float]:
    a, b = sent
    out: dict[str, float] = {}
    if "state_revision" in b:
        out["revision_delta"] = float(b["state_revision"] - a["state_revision"])
    detail = b.get("detail", "")
    if (m := re.search(r"(\d+) memory/ies withdrawn", detail)):
        out["withdrawn"] = float(m.group(1))
    if (m := re.search(r"forwarded to (\d+) peer", detail)):
        out["forwarded"] = float(m.group(1))
    elif detail:
        out["forwarded"] = 0.0
    return out


def generic_features(sent: list[dict[str, Any]]) -> dict[str, float]:
    b = sent[1]
    out = {"length": float(len(json.dumps(b, sort_keys=True)))}
    for key, value in b.items():
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{16,}", value):
            out[f"byte:{key}"] = float(int(value[:2], 16))
    return out


def loo_categorical(xs: list[float], ys: list[int]) -> float:
    """Leave-one-out accuracy of predicting y by the majority y among equal x."""
    correct = 0
    for i, (x, y) in enumerate(zip(xs, ys)):
        rest = Counter(ys[j] for j in range(len(xs)) if j != i and xs[j] == x)
        if not rest:
            rest = Counter(ys[j] for j in range(len(xs)) if j != i)
        correct += rest.most_common(1)[0][0] == y
    return correct / len(xs)


def loo_majority(ys: list[int]) -> float:
    return sum(Counter(ys[j] for j in range(len(ys)) if j != i).most_common(1)[0][0] == y
               for i, y in enumerate(ys)) / len(ys)


def loo_r2(xs: list[float], ys: list[float]) -> float:
    """Leave-one-out R^2 of a least-squares line, against predicting the mean."""
    sse = sst = 0.0
    for i in range(len(xs)):
        x_rest = [xs[j] for j in range(len(xs)) if j != i]
        y_rest = [ys[j] for j in range(len(xs)) if j != i]
        mx, my = statistics.mean(x_rest), statistics.mean(y_rest)
        var = sum((x - mx) ** 2 for x in x_rest)
        slope = sum((x - mx) * (y - my) for x, y in zip(x_rest, y_rest)) / var if var else 0.0
        sse += (ys[i] - (my + slope * (xs[i] - mx))) ** 2
        sst += (ys[i] - my) ** 2
    return 1 - sse / sst if sst else 0.0


def leakage(population: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    feats = [{**parse_features(p["sent"][kind]), **generic_features(p["sent"][kind])}
             for p in population]
    names = sorted({k for f in feats for k in f})
    out: dict[str, Any] = {}
    for attr in ATTRIBUTES:
        ys = [p["truth"][attr] for p in population]
        scores: dict[str, float] = {}
        for name in names:
            xs = [f.get(name, -1.0) for f in feats]
            if attr == "activity":
                scores[name] = round(loo_r2(xs, [float(y) for y in ys]), 4)
            else:
                scores[name] = round(loo_categorical(xs, ys) - loo_majority(ys), 4)
        best = max(scores, key=lambda k: scores[k]) if scores else None
        out[attr] = {"best_feature": best, "advantage": scores.get(best, 0.0) if best else 0.0,
                     "metric": "loo R^2" if attr == "activity" else "loo accuracy - majority",
                     "by_feature": scores}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    population = []
    for seed in range(args.first_seed, args.first_seed + args.seeds):
        rng = random.Random(seed)
        population += [one_recipient(rng, seed * 1000 + n) for n in range(RECIPIENTS)]
    sound: dict[str, int] = defaultdict(int)
    for p in population:
        for k, v in p["soundness"].items():
            sound[k] += int(v)
    result = {
        "experiment": "s5-receipt-leakage",
        "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                 text=True).stdout.strip(),
        "seeds": args.seeds, "recipients": len(population),
        "leakage": {"ack": leakage(population, "ack"), "receipt": leakage(population, "receipt")},
        "soundness": {k: f"{v}/{len(population)}" for k, v in sorted(sound.items())},
    }
    if args.out:
        Path(args.out).write_text(json.dumps({**result, "population": population}, indent=1)
                                  + "\n", encoding="utf-8")
    def brief(side: dict[str, Any]) -> dict[str, Any]:
        return {a: (v["best_feature"], v["advantage"]) for a, v in side.items()}

    print(json.dumps({**{k: v for k, v in result.items() if k != "leakage"},
                      "ack": brief(result["leakage"]["ack"]),
                      "receipt": brief(result["leakage"]["receipt"])}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
