"""X6 -- is a memory written by one model usable by another?

Registered in `research/prereg/x6-cross-model-portability.md`.

Three families at matched size -- `qwen2.5:3b`, `llama3.2:3b`, `gemma3:4b` --
each **writes** the same DepotWorld learning episodes up as lessons, and each
**reads** every resulting corpus. A 3 x 3 matrix of task success, paired by
(seed, episode), plus an oracle row per reader.

## The estimand is the diagonal interaction, not the off-diagonal mean

The obvious measure -- does B do well with A's memories? -- mostly measures
whether A writes good lessons. So each cell is decomposed

    success(r, w) = mu + reader_r + writer_w + interaction_rw

and the quantity reported is the mean diagonal interaction: the part of
reading your *own* memory that being a good reader and being a good writer do
not explain. Writer quality goes into `writer_w`, where it belongs.

## Resumable, because it is long

About four hours on CPU. Every corpus and every cell result is written to
`--cache` as it completes, keyed by (seed, writer) and (seed, reader, corpus),
so an interrupted run resumes rather than restarting. Two runs were lost whole
to missing persistence earlier the same day.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as stats
import sys
import time
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments import checks  # noqa: E402
from experiments import depotworld as W  # noqa: E402
from experiments import phase_a_prime as PA  # noqa: E402
from amberlog.vectors import LexicalIndex  # noqa: E402

MODELS = ("qwen2.5:3b", "llama3.2:3b", "gemma3:4b")
ORACLE = "oracle"
K = 3


# --- persistence ------------------------------------------------------------

class Cache:
    """Corpora and cell results, written as each one completes."""

    def __init__(self, path: str | None) -> None:
        self.path = Path(path) if path else None
        self.data: dict[str, Any] = {"corpora": {}, "cells": {}}
        if self.path and self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        self.data.setdefault("corpora", {})
        self.data.setdefault("cells", {})

    def save(self) -> None:
        if not self.path:
            return
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        # Replace rather than write in place, so a crash mid-write cannot
        # leave a truncated cache that loads and looks complete.
        tmp.replace(self.path)


def lesson_to_dict(lesson: PA.Lesson) -> dict[str, Any]:
    return {"content": lesson.content, "fault": lesson.fault,
            "site": lesson.site, "asserted": lesson.asserted,
            "poisoned": lesson.poisoned}


def lesson_from_dict(row: dict[str, Any]) -> PA.Lesson:
    return PA.Lesson(**row)


# --- corpora ----------------------------------------------------------------

def oracle_corpus(truth: Any, learning: Sequence[W.LearningEpisode]
                  ) -> list[PA.Lesson]:
    """The correct lesson for every learned (fault, site), in one neutral
    template.

    Built from the **truth**, not from the episode's action, so a poisoned
    learning episode still contributes its correct lesson. It bounds what any
    writer could give a reader: the right facts, in plain wording, with nothing
    garbled.
    """
    out = []
    for episode in learning:
        action = truth.action(episode.fault, episode.site)
        out.append(PA.Lesson(
            content=(f"Fault {episode.fault} at the {episode.site} site: "
                     f"{action.replace('_', ' ')}."),
            fault=episode.fault, site=episode.site,
            asserted=action, poisoned=False))
    return out


def corpus_for(writer: str, seed: int, truth: Any,
               learning: Sequence[W.LearningEpisode], client: Any,
               cache: Cache) -> list[PA.Lesson]:
    key = f"{seed}|{writer}"
    if key in cache.data["corpora"]:
        return [lesson_from_dict(r) for r in cache.data["corpora"][key]]
    if writer == ORACLE:
        lessons = oracle_corpus(truth, learning)
    else:
        lessons = PA.write_corpus(learning, client, writer, verbose=False)
    cache.data["corpora"][key] = [lesson_to_dict(l) for l in lessons]
    cache.save()
    return lessons


# --- one cell ---------------------------------------------------------------

def read_cell(reader: str, lessons: Sequence[PA.Lesson],
              evaluation: Sequence[W.EvalEpisode], client: Any,
              seed: int, corpus: str) -> dict[str, Any]:
    """One reader, one corpus, every evaluation episode.

    Retrieval is lexical over the corpus, restricted to the lessons released
    so far by the same schedule PA' uses, so every cell sees the same
    information at the same time. Rendering is plain text -- X5 measured it
    as the most accurate, and this experiment is about who wrote a memory,
    not how it is framed.
    """
    schedule = PA.release_schedule(max(len(lessons), 1), len(evaluation))
    index = LexicalIndex()
    added: set[int] = set()
    successes: list[int] = []
    retrieved_right: list[int] = []
    started = time.perf_counter()
    for position, episode in enumerate(evaluation):
        for i in range(min(schedule[position], len(lessons))):
            if i not in added:
                index.add(str(i), lessons[i].content)
                added.add(i)
        hits = (index.search(W.recall_query(episode), k=K,
                             restrict_to={str(i) for i in added})
                if added else [])
        shown = [lessons[int(key)] for key, _score in hits]
        text = W.render_plain([l.content for l in shown]) if shown else ""
        reply, tokens, model_ms = PA._ask(client, reader, text, episode)
        decision = PA._score(f"{reader}<-{corpus}", seed, position, episode,
                             shown, reply, tokens, 0.0, model_ms,
                             store_size=len(added))
        successes.append(int(bool(decision.success)))
        retrieved_right.append(int(any(l.right_for(episode) for l in shown)))
    return {"success": successes, "right_in_context": retrieved_right,
            "seconds": round(time.perf_counter() - started, 1)}


# --- the run ----------------------------------------------------------------

def run(seeds: int, episodes: int, models: Sequence[str], cache_path: str | None,
        verbose: bool) -> dict[str, Any]:
    from amberlog.adapters.ollama import OllamaClient

    client = OllamaClient()
    cache = Cache(cache_path)
    corpora_names = list(models) + [ORACLE]
    started = time.perf_counter()

    for seed in range(seeds):
        rng = random.Random(seed)
        truth = W.build_truth(rng)
        learning = W.learning_episodes(truth, rng)
        evaluation = W.eval_episodes(truth, rng, count=episodes)

        corpora = {}
        for writer in corpora_names:
            corpora[writer] = corpus_for(writer, seed, truth, learning,
                                         client, cache)
        print(f"  seed {seed}: corpora "
              + ", ".join(f"{w}={len(c)}" for w, c in corpora.items()),
              flush=True)

        for reader in models:
            for corpus in corpora_names:
                key = f"{seed}|{reader}|{corpus}"
                if key in cache.data["cells"]:
                    continue
                cell = read_cell(reader, corpora[corpus], evaluation,
                                 client, seed, corpus)
                cache.data["cells"][key] = cell
                cache.save()
                print(f"  seed {seed} {reader:<13} <- {corpus:<13} "
                      f"success {stats.mean(cell['success']):.3f}  "
                      f"({cell['seconds']}s)", flush=True)

    return analyse(cache.data, seeds, episodes, models,
                   wall=time.perf_counter() - started,
                   calls=len(client.calls))


# --- analysis ---------------------------------------------------------------

def matrix(cells: dict[str, Any], units: Sequence[tuple[int, int]],
           models: Sequence[str]) -> dict[tuple[str, str], float]:
    """Mean success per (reader, writer) over the given episode units."""
    out = {}
    for reader in models:
        for writer in list(models) + [ORACLE]:
            values = [cells[f"{s}|{reader}|{writer}"]["success"][e]
                      for s, e in units
                      if f"{s}|{reader}|{writer}" in cells]
            out[(reader, writer)] = (sum(values) / len(values)) if values else 0.0
    return out


def diagonal_interaction(m: dict[tuple[str, str], float],
                         models: Sequence[str]) -> float:
    """Mean over r of cell(r,r) - row_mean(r) - col_mean(r) + grand_mean.

    Over the model-written corpora only: the oracle is a bound, not a writer,
    and including it would let a reader's skill with perfect lessons leak into
    the estimate of how it reads another model's.
    """
    rows = {r: stats.mean(m[(r, w)] for w in models) for r in models}
    cols = {w: stats.mean(m[(r, w)] for r in models) for w in models}
    grand = stats.mean(m[(r, w)] for r in models for w in models)
    return stats.mean(m[(r, r)] - rows[r] - cols[r] + grand for r in models)


def own_memory_bonus(d: float, n: int) -> float:
    """The diagonal bonus a given D implies.

    D is not the bonus itself. A bonus `b` added to every diagonal cell also
    raises that row's mean, that column's mean and the grand mean, so the
    decomposition recovers only part of it:

        D = b * (n - 1) / n

    For three models D is two thirds of the bonus. Found by a known-answer test
    before any model call -- a bonus of 0.1 returned D = 0.067 -- and recorded
    in the registration's amendment, because a threshold written on D means a
    larger effect than it appears to.
    """
    return d * n / (n - 1) if n > 1 else d


def analyse(data: dict[str, Any], seeds: int, episodes: int,
            models: Sequence[str], wall: float = 0.0,
            calls: int = 0, draws: int = 2000) -> dict[str, Any]:
    cells = data["cells"]
    units = [(s, e) for s in range(seeds) for e in range(episodes)
             if all(f"{s}|{r}|{w}" in cells
                    for r in models for w in list(models) + [ORACLE])]
    if not units:
        return {"experiment": "x6-cross-model", "error": "no complete units"}

    point = matrix(cells, units, models)
    d_point = diagonal_interaction(point, models)

    rng = random.Random(7)
    boot = []
    for _ in range(draws):
        sample = [units[rng.randrange(len(units))] for _ in units]
        boot.append(diagonal_interaction(matrix(cells, sample, models), models))
    boot.sort()
    lo, hi = boot[int(0.025 * draws)], boot[int(0.975 * draws)]
    half_width = (hi - lo) / 2

    if lo > 0.0 and d_point >= 0.05:
        verdict = "NOT PORTABLE"
    elif lo >= -0.05 and hi <= 0.05:
        verdict = "PORTABLE"
    else:
        verdict = "INCONCLUSIVE"

    rows = {r: round(stats.mean(point[(r, w)] for w in models), 4)
            for r in models}
    cols = {w: round(stats.mean(point[(r, w)] for r in models), 4)
            for w in models}
    grand = stats.mean(point[(r, w)] for r in models for w in models)

    correctness = {}
    for writer in models:
        rows_w = [l for key, corpus in data["corpora"].items()
                  if key.split("|", 1)[1] == writer for l in corpus]
        correctness[writer] = (round(
            sum(1 for l in rows_w if not l["poisoned"]) / len(rows_w), 4)
            if rows_w else None)
        correctness[writer + "_lessons"] = len(rows_w)

    oracle_by_reader = {r: round(point[(r, ORACLE)], 4) for r in models}
    above = {f"{r}<-{w}": round(point[(r, w)], 4)
             for r in models for w in models
             if point[(r, w)] > point[(r, ORACLE)] + 1e-9}

    return {
        "experiment": "x6-cross-model",
        "models": list(models), "seeds": seeds, "episodes": episodes,
        "units": len(units),
        "matrix": {f"{r}<-{w}": round(v, 4) for (r, w), v in point.items()},
        "reader_effect": {r: round(v - grand, 4) for r, v in rows.items()},
        "writer_effect": {w: round(v - grand, 4) for w, v in cols.items()},
        "oracle_by_reader": oracle_by_reader,
        "diagonal_interaction": {
            "point": round(d_point, 4), "ci95": [round(lo, 4), round(hi, 4)],
            "half_width": round(half_width, 4),
            "portable_reachable": half_width <= 0.05,
            # The interpretable quantity: how much better a model reads its
            # own memories, in the same units as the cells.
            "own_memory_bonus": round(own_memory_bonus(d_point, len(models)), 4),
            "own_memory_bonus_ci95": [
                round(own_memory_bonus(lo, len(models)), 4),
                round(own_memory_bonus(hi, len(models)), 4)],
        },
        "verdict": verdict,
        "writer_lesson_correctness": correctness,
        "checks": checks.verify(
            ceiling={"ok": not above, "arms_above_their_readers_oracle": above,
                     "note": ("a cell above its reader's oracle means the "
                              "oracle corpus is not a bound")
                     if above else ""},
            power={"ok": half_width <= 0.05,
                   "half_width": round(half_width, 4),
                   "note": ("the CI is too wide for the PORTABLE verdict to be "
                            "reachable; INCONCLUSIVE here is not a soft yes")
                   if half_width > 0.05 else ""},
        ),
        "cost": {"calls": calls, "wall_s": round(wall, 1)},
    }


def to_markdown(r: dict[str, Any]) -> str:
    if r.get("error"):
        return f"# X6\n\n{r['error']}"
    models = r["models"]
    lines = [
        "# X6 - cross-model memory portability",
        "",
        f"- {', '.join(f'`{m}`' for m in models)}; {r['seeds']} seeds x "
        f"{r['episodes']} episodes = {r['units']} paired units",
        "",
        "Task success by **reader** (row) and **writer** (column):",
        "",
        "| reader \\ writer | " + " | ".join(f"`{w}`" for w in models)
        + " | oracle |",
        "|---|" + "---|" * (len(models) + 1),
    ]
    for reader in models:
        cells = [r["matrix"][f"{reader}<-{w}"] for w in models]
        cells_txt = [f"**{c}**" if w == reader else f"{c}"
                     for c, w in zip(cells, models)]
        lines.append(f"| `{reader}` | " + " | ".join(cells_txt)
                     + f" | {r['oracle_by_reader'][reader]} |")
    d = r["diagonal_interaction"]
    lines += [
        "",
        f"**Diagonal interaction D = {d['point']:+}**, 95% CI "
        f"[{d['ci95'][0]:+}, {d['ci95'][1]:+}], half-width {d['half_width']}. "
        f"That is an **own-memory bonus of {d['own_memory_bonus']:+}** "
        f"[{d['own_memory_bonus_ci95'][0]:+}, "
        f"{d['own_memory_bonus_ci95'][1]:+}], since D = b(n-1)/n.",
        "",
        f"**{r['verdict']}.**"
        + ("" if d["portable_reachable"] else
           " The CI is wider than the +/-0.05 equivalence margin, so PORTABLE "
           "was not reachable at this sample size."),
        "",
        "| model | reader effect | writer effect | own-site-correct lessons |",
        "|---|---|---|---|",
    ]
    for m in models:
        lines.append(f"| `{m}` | {r['reader_effect'][m]:+} | "
                     f"{r['writer_effect'][m]:+} | "
                     f"{r['writer_lesson_correctness'].get(m)} |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pilot", action="store_true",
                        help="one seed, 8 episodes")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--episodes", type=int, default=24)
    parser.add_argument("--models", nargs="*", default=list(MODELS))
    parser.add_argument("--cache")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    seeds = 1 if args.pilot else args.seeds
    episodes = 8 if args.pilot else args.episodes
    result = run(seeds, episodes, args.models, args.cache, args.verbose)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, default=str)
                                  + "\n", encoding="utf-8")
    text = to_markdown(result)
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
