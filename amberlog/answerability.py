"""Answerability: does the retrieved evidence answer *this* question?

Retrieval answers a different question: which stored memories are most like
the query. Its scores are a ranking, and every measurement here says they are
a poor abstention signal. Pooled AUC is 0.682 and the best threshold F1 is
0.206 (`research/results/abstention-signals.md`). An unanswerable question
still has near neighbours, so it still gets confident-looking results.

So answerability is a separate verdict, made **after** retrieval and from
the evidence itself, never from its scores:

| verdict | meaning |
|---|---|
| `answerable` | at least one usable memory states a value for the asked subject and parameter |
| `conflicting` | covering memories by different authors give different values; the answer is disputed |
| `insufficient` | the question names a subject (an identifier) and no usable memory covers that subject and parameter |
| `undetermined` | the question names no identifier, so the structural check cannot tell; a judge, or the caller, decides |

`retrieval_confidence` is reported beside the verdict and kept separate from
it: the top retrieval score, for callers who log both.

**The structural check** reuses the claim reading of the conflict and
validation checks (`conflicts.claim`). A memory *covers* a question when its
identifiers include every identifier in the question, and it shares at least
two content words with the question (all of them, if the question has fewer),
and it states a value. This is the same "same claim" rule the claim checks use,
so a near-miss on another unit (`K-13` for `K-31`) or another parameter of the
right unit does not count as cover.

**A judge** is optional: any callable `(question, [memory text]) -> (bool,
reason)`, typically a model. It is consulted only when the structural verdict
is `undetermined`, or on every call with `judge_always=True`. The product
makes no model call itself (AGENTS.md: model calls go through the caller's
client wrapper).

**When to gate on it, measured (A1, A1-h).** With a capable model told to
answer or say UNKNOWN, the model alone abstained correctly on every
near-miss family (`sonnet` 1.000, `haiku` 0.993), and gating on this verdict
only added false abstentions on paraphrases. Gating helped where the model
was *not* told to abstain: 0.587 → 0.907 correct, with zero wrong answers.
A separate model judge was worse than the model abstaining inside its own
answer: `haiku` as a judge refused 72% of answerable questions. So: report
the verdict always, gate on it only for models or hosts that do not follow
an abstention instruction, and use the strongest model available as a judge.

**What it cannot see, stated.** It reads identifiers and words, not meaning.
If a parameter is paraphrased with no shared word ("overcurrent setting"
against "trip current") the memory does not count as cover, and the verdict
is `insufficient` when it should be `answerable`. That is the false-abstention
risk, and the A1 evaluation measures it.
"""

from __future__ import annotations

__stability__ = "beta"

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Sequence

from .conflicts import author, claim

if TYPE_CHECKING:  # pragma: no cover
    from .model import Memory

ANSWERABLE = "answerable"
CONFLICTING = "conflicting"
INSUFFICIENT = "insufficient"
UNDETERMINED = "undetermined"

Judge = Callable[[str, Sequence[str]], "tuple[bool, str]"]


@dataclass(frozen=True)
class Answerability:
    verdict: str
    covering: tuple[str, ...] = ()
    """Memory ids that cover the asked subject and parameter."""
    reasons: tuple[str, ...] = ()
    retrieval_confidence: float | None = None
    """The top retrieval score, reported separately and never used for the verdict."""
    judged: bool = False
    values: dict[str, list[str]] = field(default_factory=dict)
    """value -> memory ids stating it, among the covering memories."""

    @property
    def should_abstain(self) -> bool:
        return self.verdict == INSUFFICIENT

    def to_json(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "covering": list(self.covering),
                "reasons": list(self.reasons), "values": self.values,
                "retrieval_confidence": self.retrieval_confidence, "judged": self.judged}


def covers(question: str, content: str) -> bool:
    """Whether one memory's text states a value for the question's subject and parameter."""
    q_ids, q_words, _ = claim(question)
    ids, words, values = claim(content)
    if not q_ids or not values or not q_ids <= ids:
        return False
    need = min(2, len(q_words))
    return len(q_words & words) >= max(1, need)


def assess(question: str, memories: Sequence["Memory"], *,
           scores: dict[str, float] | None = None, judge: Judge | None = None,
           judge_always: bool = False) -> Answerability:
    """The answerability verdict for `question` given the memories retrieval returned.

    `memories` should be what the caller is about to place in context (usable
    ones). `scores`, if given, only fills `retrieval_confidence`.
    """
    confidence = max(scores.values()) if scores else None
    q_ids, _, _ = claim(question)
    covering = [m for m in memories if covers(question, m.content)]
    values: dict[str, list[str]] = {}
    for m in covering:
        key = ",".join(sorted(claim(m.content)[2]))
        values.setdefault(key, []).append(m.id)

    if not q_ids:
        verdict, reasons = UNDETERMINED, ["the question names no identifier to check cover for"]
    elif not covering:
        verdict = INSUFFICIENT
        reasons = [f"no usable memory states a value for {', '.join(sorted(q_ids))} "
                   f"and the asked parameter"]
    elif len(values) > 1 and len({author(m) for m in covering}) > 1:
        verdict = CONFLICTING
        reasons = [f"{len(values)} different values from {len({author(m) for m in covering})} authors"]
    else:
        verdict, reasons = ANSWERABLE, [f"{len(covering)} memory(ies) state a value"]

    judged = False
    if judge is not None and (judge_always or verdict == UNDETERMINED):
        ok, why = judge(question, [m.content for m in memories])
        judged = True
        if verdict == UNDETERMINED or judge_always:
            if ok and verdict in (UNDETERMINED, INSUFFICIENT):
                verdict = ANSWERABLE
            elif not ok and verdict in (UNDETERMINED, ANSWERABLE):
                verdict = INSUFFICIENT
        reasons.append(f"judge: {why}")

    return Answerability(verdict, tuple(m.id for m in covering), tuple(reasons),
                         confidence, judged, values)
