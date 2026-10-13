"""Can a model supply the declarations, and what does it cost?

`research/prereg/x1-extraction-at-ingest.md` registers sufficiency as the
primary metric. The end-to-end run over the registered families needs **1,374
unique statements on dev**, and the models run on CPU here (`/api/ps` reports
0 MB VRAM), at a measured **4.8 to 54.5 seconds each** -- up to **20.8 hours
for one arm of one split**, which no batching or concurrency reduces because it
is compute-bound rather than round-trip-bound. So this measures the thing the
end-to-end run depends on, directly and affordably: **does the model produce
the structure, and what does each statement cost?**

An extraction-quality measurement, not a retrieval arm. The statements are
chosen *using the labels* -- the chain hops, the default rule, and a sample of
fillers -- because the question is whether the model sees what is there, and a
random sample of 500 memories would spend an hour to look at two interesting
ones. Nothing here is scored as retrieval, and the registered primary stays
unmeasured for the reason §4 of the result gives.

Three things are checked per statement:

* **the modifier** -- is *"at the depot-12 site, add 0.35 bar to the axle-set figure"* recognised as adjusting something rather than asserting it, with a usable target?
* **the default** -- is *"all yard vehicles run 3.9 bar in winter, except at the harbour and quarry sites"* recognised as excluding named entities?
* **the fillers** -- are ordinary statements left alone? A model that calls everything a modifier has told us nothing, and this is the half an end-to-end run would hide.

## What `classify` measures, and what it over-credits

`classify` reads the **class** and not the **target**, and the first run showed
why that distinction has to be reported rather than assumed away.
`qwen2.5:7b` classified the modifier correctly and returned
`modifies="add"`; `finsenti-llama3.2-1b` returned
`modifies="salt-corrosion margin"`. Both score 1/1 in the `modifier` column and
**neither is usable**: `infer_relations` matches the target against another
record's predicate, and no predicate is "add". Only `gemma2` returned
`"axle-set figure"`, the thing actually being adjusted.

The column is left as it is and the **targets are reported verbatim** in the
result, because a usability score invented after seeing three targets would be
fitted to them -- the substring test that rejects `"add"` accepts
`"salt-corrosion margin"`, which is wrong for a reason a substring cannot see.
Three verbatim strings are more honest than a metric with one tunable.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import relevance_bench as rb  # noqa: E402
from memory_fabric import extraction as extracting  # noqa: E402

FILLERS_PER_FAMILY = 8


@dataclass
class Judged:
    content: str
    expect: str              # "modifier" | "default" | "plain"
    got: str
    detail: str
    seconds: float

    truncated: bool = False
    """Whether the reply used the whole output budget.

    A reasoning model spends it reasoning: `qwen3:1.7b` hit 220 of 220 output
    tokens on 12 of 12 calls. Reported so that "this model cannot extract" and
    "this model never reached the JSON" are different rows.
    """

    target: str | None = None
    """The extracted `modify_target`, verbatim.

    Reported rather than scored. `classify` reads the class and not the
    target, and the first run showed why that has to be visible: two models
    scored 1/1 on the modifier with targets of `'add'` and
    `'salt-corrosion margin'`, neither of which any predicate can match. A
    usability metric invented after seeing three targets would be fitted to
    them -- a substring test rejects `'add'` and accepts
    `'salt-corrosion margin'`, which is wrong for a reason a substring cannot
    see.
    """

    @property
    def correct(self) -> bool:
        return self.got == self.expect


@dataclass
class ModelResult:
    model: str
    judged: list[Judged] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        by_expect: dict[str, list[Judged]] = {}
        for row in self.judged:
            by_expect.setdefault(row.expect, []).append(row)
        out: dict[str, Any] = {
            "statements": len(self.judged),
            "unparsed": sum(1 for r in self.judged if r.got == "unparsed"),
            "truncated": sum(1 for r in self.judged if r.truncated),
            "seconds_total": round(sum(r.seconds for r in self.judged), 1),
            "seconds_each": round(
                sum(r.seconds for r in self.judged) / len(self.judged), 1)
            if self.judged else 0.0,
        }
        for expect, rows in sorted(by_expect.items()):
            out[f"{expect}_correct"] = f"{sum(r.correct for r in rows)}/{len(rows)}"
        return out


def classify(record: extracting.Extracted) -> tuple[str, str]:
    """The class, and enough detail to tell a success from a silence.

    `unparsed` is reported **before** anything else and is never `plain`. It
    used to be: an unparseable reply became `Extracted(asserts=False)` with no
    target and no exclusions, which read as an ordinary statement -- so a model
    that failed on every call scored 17/17 on the column that exists to catch
    models behaving badly. The figures in sections 2 and 8 of the result were
    measured before this distinction existed and are re-measured with it.
    """
    if not record.parsed:
        return "unparsed", "no JSON object in the reply"
    if record.is_modifier:
        return "modifier", f"target={record.modify_target!r}"
    if record.is_default:
        return "default", f"excepts={list(record.excepts)}"
    return "plain", f"predicate={record.predicate!r}"


def sample(split: str, seed: int = 1) -> list[tuple[str, str]]:
    """(content, expected class). Chosen with the labels; see the docstring."""
    rng = random.Random(seed)
    out: list[tuple[str, str]] = []

    for case in rb.load(split, "relevance_v2"):
        if case["family"] != "multi_hop_4":
            continue
        by_id = {m["id"]: m["content"] for m in case["corpus"]}
        if "h4" in by_id:
            out.append((by_id["h4"], "modifier"))
        if "h3" in by_id:
            out.append((by_id["h3"], "plain"))
        fillers = [m["content"] for m in case["corpus"]
                   if m["id"] not in case["labels"]["relevant"]]
        out += [(c, "plain") for c in rng.sample(fillers, FILLERS_PER_FAMILY)]
        break

    for case in rb.load(split, "facet_v1"):
        if case["family"] != "implied_by_default":
            continue
        by_id = {m["id"]: m["content"] for m in case["corpus"]}
        if "a1" in by_id:
            out.append((by_id["a1"], "default"))
        fillers = [m["content"] for m in case["corpus"]
                   if m["id"] not in case["labels"]["relevant"]]
        out += [(c, "plain") for c in rng.sample(fillers, FILLERS_PER_FAMILY)]
        break

    return out


def run(models: Sequence[str], split: str = "dev",
        constrained: bool = True, warm: bool = True,
        trace: str | None = None,
        think: bool | None = False) -> dict[str, Any]:
    from memory_fabric.adapters.ollama import OllamaClient

    statements = sample(split)
    results: list[ModelResult] = []
    for model in models:
        client = OllamaClient()
        if trace:
            # Metadata only. `JsonlSink` sends no content unless asked, and
            # this comparison has no reason to ask: what it needs from a trace
            # is latency and token counts per model.
            from memory_fabric.adapters.tracing import JsonlSink

            client.add_sink(JsonlSink(trace))
        extractor = extracting.ModelExtractor(
            client=client, model=model, constrained=constrained, think=think)
        if warm:
            # A cold load costs 20-35s against a per-call figure of seconds,
            # so without this the first statement of each model carries the
            # load and the per-statement mean is a load time divided by 19.
            try:
                extractor.extract("warmup", "Bay 1 is assigned to unit-1.")
                extractor._cache.clear()
            except Exception as exc:  # pragma: no cover - environment
                print(f"  {model}: warmup failed: {exc}", file=sys.stderr)
        result = ModelResult(model=model)
        for content, expect in statements:
            started = time.perf_counter()
            try:
                record = extractor.extract("m", content)
            except Exception as exc:  # pragma: no cover - environment
                result.judged.append(Judged(
                    content=content, expect=expect, got="error",
                    detail=f"{type(exc).__name__}: {exc}"[:80],
                    seconds=time.perf_counter() - started))
                continue
            got, detail = classify(record)
            calls = getattr(client, "calls", [])
            result.judged.append(Judged(
                content=content, expect=expect, got=got, detail=detail,
                seconds=time.perf_counter() - started,
                truncated=bool(calls and calls[-1].truncated),
                target=record.modify_target))
        results.append(result)
        print(f"  {model}: {result.summary()}", file=sys.stderr)

    return {
        "experiment": "x1-extraction-quality",
        "split": split,
        "constrained": constrained,
        "warmed": warm,
        "think": think,
        "statements": len(statements),
        "models": {r.model: r.summary() for r in results},
        "detail": {
            r.model: [
                {"expect": j.expect, "got": j.got, "detail": j.detail,
                 "target": j.target, "seconds": round(j.seconds, 1),
                 "content": j.content[:90]}
                for j in r.judged
            ]
            for r in results
        },
    }


def to_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        f"# X1 — can a model supply the declarations? · {result['split']} split",
        "",
        f"- Decoding: **{'schema-constrained' if result.get('constrained') else 'free-form'}**"
        f"{', models warmed first' if result.get('warmed') else ', cold'}"
        f"{', reasoning trace ON' if result.get('think') else ', no reasoning trace'}",
        f"- {result['statements']} statements, chosen with the labels so the "
        f"interesting ones are included; see the module docstring",
        "- An extraction-quality measurement, **not** a retrieval arm",
        "",
        "| model | modifier | default | plain (false positives) | unparsed | "
        "truncated | seconds each | total |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for model, row in result["models"].items():
        lines.append(
            f"| `{model}` | {row.get('modifier_correct', '—')} | "
            f"{row.get('default_correct', '—')} | "
            f"{row.get('plain_correct', '—')} | {row.get('unparsed', 0)} | "
            f"{row.get('truncated', 0)} | {row['seconds_each']:.1f} s | "
            f"{row['seconds_total']:.0f} s |")
    lines += [
        "",
        "`unparsed` and `truncated` are the columns that make the rest "
        "readable. An unparseable reply used to classify as `plain`, so a "
        "model that failed every call scored full marks on the column meant "
        "to catch it; and a reasoning model spends its whole output budget "
        "reasoning, which is a truncated reply rather than a wrong one.",
        "",
        "`plain` counts statements that must be left alone. A model marking "
        "ordinary memories as modifiers or defaults would inject edges and "
        "applicability rules that are not there, which an end-to-end number "
        "would hide.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="*",
                        default=["qwen2.5:7b", "gemma2:latest",
                                 "finsenti-llama3.2-1b:latest"])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--unconstrained", action="store_true",
                        help="free-form decoding, as the first run measured")
    parser.add_argument("--cold", action="store_true",
                        help="do not warm the model first")
    parser.add_argument("--trace",
                        help="append one JSON object per model call to this "
                             "file (metadata only, no content)")
    parser.add_argument("--think", action="store_true",
                        help="leave the reasoning trace on. A reasoning model "
                             "spends the whole output budget on it and never "
                             "reaches the JSON, so this is for measuring that "
                             "rather than for using it")
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.models, args.split,
                 constrained=not args.unconstrained, warm=not args.cold,
                 trace=args.trace, think=True if args.think else False)
    print(json.dumps(result, indent=2) if args.as_json
          else to_markdown(result))
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
