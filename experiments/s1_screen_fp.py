"""S1 — the injection screen on ordinary conversation (research/prereg/s1-screen-false-positives.md).

    python experiments/s1_screen_fp.py rates OUT.json LME.json DEEPSET_DIR
    python experiments/s1_screen_fp.py show LME.json [N]          # tune-split flags only
    python experiments/s1_screen_fp.py report BASE.json HEAD.json
    python experiments/s1_screen_fp.py withholding OUT.json LME.json [LIMIT]

`rates` imports whichever `amberlog` is first on the path, so CI runs it
once against a checkout of the base commit and once against the change, in the
same job: the baseline is measured, not quoted (AGENTS.md 8d). It only reads
text and calls the screens; nothing from the datasets is executed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "research" / "results" / "s1-screen-false-positives.md"
OUT_JSON = ROOT / "research" / "results" / "s1-screen-false-positives.json"


def split_of(question_id: str) -> str:
    return "tune" if int(hashlib.sha256(question_id.encode()).hexdigest(), 16) % 2 == 0 else "test"


def lme_turns(path: str) -> dict[str, list[str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    seen: dict[str, set[str]] = {"tune": set(), "test": set()}
    for inst in data:
        bucket = seen[split_of(inst["question_id"])]
        for session in inst["haystack_sessions"]:
            for turn in session:
                content = (turn.get("content") or "").strip()
                if content:
                    bucket.add(f"{turn.get('role', 'user')}: {content}")
    # A turn in both splits stays only in tune, so test is never seen while tuning.
    seen["test"] -= seen["tune"]
    return {k: sorted(v) for k, v in seen.items()}


def screen() -> Any:
    from amberlog.governance.firewall import Firewall

    return Firewall()


def verdict(fw: Any, text: str) -> tuple[bool, bool, list[str]]:
    """(quarantined as injection, quarantined for sensitive data, reasons)."""
    ruling = fw.screen_ingest(text)
    quarantined = ruling.decision.value == "quarantine"
    reasons = list(ruling.reasons)
    injection = quarantined and any("prompt injection detected" in r for r in reasons)
    sensitive = quarantined and any(r.startswith("sensitive data detected") for r in reasons)
    return injection, sensitive, reasons


def injection_flag(text: str) -> bool:
    from amberlog.governance import directive
    from amberlog.governance.injection import InjectionDetector

    high = [f for f in InjectionDetector().scan(text) if f.severity == "high"]
    return bool(high) or directive.assess(text).flagged


def deepset(directory: str) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for f in sorted(Path(directory).glob("test-*.json")):
        rows += [(r["row"]["text"], int(r["row"]["label"]))
                 for r in json.loads(f.read_text(encoding="utf-8")).get("rows", [])]
    return rows


def recall(rows: list[tuple[str, int]]) -> dict[str, int]:
    pos = [injection_flag(t) for t, y in rows if y == 1]
    neg = [injection_flag(t) for t, y in rows if y == 0]
    return {"caught": sum(pos), "injections": len(pos), "benign_flagged": sum(neg),
            "benign": len(neg)}


def rates(out: str, lme: str, deepset_dir: str) -> int:
    fw = screen()
    turns = lme_turns(lme)
    result: dict[str, Any] = {"lme": {}}
    for split, texts in turns.items():
        inj = sens = 0
        flagged: list[dict[str, Any]] = []
        for text in texts:
            i, s, reasons = verdict(fw, text)
            inj += i
            sens += s
            if i and split == "test":
                flagged.append({"text": text[:300], "reasons": reasons[:3]})
        result["lme"][split] = {"turns": len(texts), "injection": inj, "sensitive": sens,
                                "injection_rate": inj / len(texts) if texts else 0.0,
                                "sensitive_rate": sens / len(texts) if texts else 0.0}
        if split == "test":
            result["test_flagged"] = flagged
    result["deepset_test"] = recall(deepset(deepset_dir))
    own = json.loads((ROOT / "research/bench/injection_heldout/heldout.json").read_text(encoding="utf-8"))
    result["own_heldout"] = recall([(t, 1) for t in own["injections"]]
                                   + [(t, 0) for t in own["benign_hard_negatives"]])
    Path(out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "test_flagged"}, indent=2))
    return 0


def show(lme: str, n: int = 80) -> int:
    """Tune-split turns the screen quarantines as injection, grouped by signal."""
    fw = screen()
    by_signal: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for text in lme_turns(lme)["tune"]:
        i, _, reasons = verdict(fw, text)
        if not i:
            continue
        for r in reasons:
            if "prompt injection" in r:
                key = r.split(":", 1)[-1].strip()[:90]
                by_signal[key] += 1
                examples.setdefault(key, []).append(text[:240].replace("\n", " "))
    for key, count in by_signal.most_common(n):
        print(f"{count:5d}  {key}")
        for ex in examples[key][:2]:
            print(f"         | {ex}")
    return 0


def report(base_path: str, head_path: str) -> int:
    base = json.loads(Path(base_path).read_text(encoding="utf-8"))
    head = json.loads(Path(head_path).read_text(encoding="utf-8"))
    b = base["lme"]["test"]["injection_rate"]
    h = head["lme"]["test"]["injection_rate"]
    d, o = head["deepset_test"], head["own_heldout"]
    verdict_ = {
        "S1a": h <= 0.2 * b,
        "S1b": d["caught"] >= 20 and d["benign_flagged"] <= 0,
        "S1c": o["caught"] >= 10 and o["benign_flagged"] == 0,
    }
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    OUT_JSON.write_text(json.dumps({"commit": commit, "base": base, "head": head,
                                    "verdict": verdict_}, indent=2) + "\n", encoding="utf-8")

    def row(name: str, r: dict[str, Any]) -> str:
        t, u = r["lme"]["test"], r["lme"]["tune"]
        return (f"| {name} | {t['injection']} / {t['turns']} ({100 * t['injection_rate']:.2f}%) | "
                f"{u['injection']} / {u['turns']} ({100 * u['injection_rate']:.2f}%) | "
                f"{r['deepset_test']['caught']} / {r['deepset_test']['injections']} | "
                f"{r['deepset_test']['benign_flagged']} / {r['deepset_test']['benign']} | "
                f"{r['own_heldout']['caught']} / {r['own_heldout']['injections']} | "
                f"{r['own_heldout']['benign_flagged']} / {r['own_heldout']['benign']} |")
    flagged = "\n".join(f"- `{x['text'][:160]!r}` — {x['reasons'][0][:120]}"
                        for x in head.get("test_flagged", [])[:20]) or "- none"
    OUT_MD.write_text(f"""# S1 — the injection screen on ordinary conversation

Registered in [s1-screen-false-positives.md](../prereg/s1-screen-false-positives.md). Produced by
`experiments/s1_screen_fp.py` at commit `{commit}` in CI; the baseline is the base commit's screen,
measured in the same job. Raw numbers in [s1-screen-false-positives.json](s1-screen-false-positives.json).

| screen | LongMemEval test turns quarantined as injection | tune turns | deepset test caught | deepset benign flagged | held-out caught | held-out benign flagged |
|---|---|---|---|---|---|---|
{row("before", base)}
{row("after", head)}

| S1a test rate ≤ 0.2 × before | S1b deepset ≥ 20/60, 0 benign | S1c held-out ≥ 10/12, 0/16 |
|---|---|---|
| {"pass" if verdict_["S1a"] else "fail"} | {"pass" if verdict_["S1b"] else "fail"} | {"pass" if verdict_["S1c"] else "fail"} |

S1d (every existing test passes) is the CI run on the same commit. Sensitive-data quarantines,
not this question, are {base['lme']['test']['sensitive']} before and {head['lme']['test']['sensitive']} after on the test split.

Test-split turns still quarantined after the change, for a reader to judge:

{flagged}
""", encoding="utf-8")
    print(json.dumps(verdict_))
    return 0 if all(verdict_.values()) else 1


def withholding(out: str, lme_path: str, limit: str = "60") -> int:
    """§5: LongMemEval lexical turn recall with hostile-source withholding on and off."""
    sys.path.insert(0, str(ROOT))
    from experiments import longmemeval_bench as lme
    from amberlog import Amberlog

    lme.DATA = Path(lme_path).parent
    lme.SPLITS["s"] = Path(lme_path).name
    instances = lme.load("s", limit=int(limit))
    result: dict[str, float] = {}
    for on in (True, False):
        recalls = []
        for inst in instances:
            gold = {(sid, pos) for sid, sess in zip(inst["haystack_session_ids"],
                                                    inst["haystack_sessions"])
                    for pos, t in enumerate(sess) if t.get("has_answer")}
            f = Amberlog(":memory:", auto_activate=True, encrypt_content=False,
                             recognise_copies=False, retrieval="lexical",
                             withhold_hostile_sources=on)
            try:
                mapping = lme._write_history(f, inst)
                got = [m.id for m in f.retrieve(
                    agent_id="lme", query=inst["question"], k=10, min_relevance=0.0,
                    as_of=lme.parse_date(inst.get("question_date") or "")).exposed]
            finally:
                f.close()
            hits = len({mapping[m] for m in got if m in mapping} & gold)
            recalls.append(hits / len(gold) if gold else 0.0)
        result["on" if on else "off"] = round(sum(recalls) / len(recalls), 4)
    result["pass"] = abs(result["on"] - result["off"]) <= 0.01
    Path(out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


def dump(out: str, lme: str, deepset_dir: str) -> int:
    """S1b's data: deepset test rows and 500 seeded test-split turns, printed for a model run elsewhere."""
    import random

    test = lme_turns(lme)["test"]
    sample = random.Random(1).sample(test, 500)
    data = {"deepset_test": deepset(deepset_dir), "lme_sample": sample}
    Path(out).write_text(json.dumps(data) + "\n", encoding="utf-8")
    print("=== S1b DATA ===")
    print(json.dumps(data))
    print("=== S1b END ===")
    return 0


def main(argv: list[str]) -> int:
    cmd, *rest = argv
    if cmd == "rates":
        return rates(*rest)
    if cmd == "show":
        return show(rest[0], int(rest[1]) if len(rest) > 1 else 80)
    if cmd == "report":
        return report(*rest)
    if cmd == "dump":
        return dump(*rest)
    if cmd == "withholding":
        return withholding(*rest)
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
