"""A client for System One decision models: typed questions, calibrated answers.

A System One model does not generate prose. It is asked **typed questions**
about a piece of text and returns a **probability distribution** over a closed
option set. The API here is TypeSafe's, which [Kev](https://github.com/jaredpalmer/kev)
serves locally under Apache-2.0, so the same client reaches either.

## Why this shape fits this project specifically

Three measured gaps are all closed option sets, and none of them is a
generation task:

* **Abstention.** *"Can this question be answered from this context?"* is one yes/no question. Four signal families are eliminated and the fifth is rejected on its operating point (`research/results/abstention-signals.md`), and the one that works is plain retrieval score at AUC 0.682.
* **Choosing between sibling rules.** `multi_hop_4`'s test split fails because the chain picks the wrong axle rule out of several differing only by axle type (`research/results/x1-extraction.md` section 11). *"Which of these three rules applies to a vehicle with the standard axle set?"* is a `choice` question over three options.
* **Propensities.** AGENTS.md principle 4 requires every exposure decision to record the probability it was made with, and principle 5 requires value to be a distribution rather than a number. A model that returns a distribution is the natural source for both.

## What this client does not assume

**Confidence is not accuracy, and the vendors say so.** Kev's README states
plainly that neither its `confidence` nor its probabilities are a measured
accuracy rate, and that probabilities are calibrated by a **per-checkpoint
temperature** fitted on their data, not ours. Kev-0.8B's Brier score on sources
it never trained on is **0.481**, against Kev-4B's 0.269 -- so the smallest
checkpoint, which is the one that fits on a laptop, is also the one whose
numbers mean least.

The failure mode to design against is the one its sibling Laya is reported to
have on Khmer: **0 accuracy at 0.952 confidence**. Confident and wrong is worse
here than unavailable, because this project's measured value is correctness
under correction, and a confidently wrong withholding decision undoes that.

So: `AnswerRecord` keeps the whole distribution rather than the top answer, the
latency and the token counts, and **every call is logged** the way AGENTS.md
requires of model calls. Nothing in this module decides anything; it reports.
Whether a number from it is worth acting on is a question for an experiment
with a registered threshold, and this project has five results saying that
acting on an inferred signal loses even when the inference is good
(`research/results/phase-a-prime-attribution.md`).

## Zero dependencies

`urllib` and `json`, like the Ollama adapter, because the core of this project
installs with nothing and that claim is only true if it is checked. The Kev
server itself needs torch; that lives in its own environment and is reached
over HTTP.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_HOST = "http://127.0.0.1:8009"
DEFAULT_MODEL = "kev-latest"


class SystemOneError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnswerRecord:
    """One typed question's answer, with the distribution kept.

    `probabilities` is the whole distribution rather than the argmax, because
    the argmax discards exactly the information this model was chosen for. For
    a `noul` question the keys are `"false"` and `"true"`.
    """

    question_id: str
    kind: str
    answer: Any
    probabilities: dict[str, float]
    confidence: float | None = None
    legend: tuple[str, ...] = ()

    @property
    def p_true(self) -> float | None:
        """P(yes) for a yes/no question, or None for any other kind."""
        if self.kind != "noul":
            return None
        return float(self.answer)

    @property
    def top(self) -> tuple[str, float] | None:
        if not self.probabilities:
            return None
        key = max(self.probabilities, key=lambda k: self.probabilities[k])
        return key, self.probabilities[key]

    @property
    def margin(self) -> float | None:
        """Gap between the two most likely options.

        Reported beside `confidence` because `confidence` is a rescaling of the
        maximum alone -- `(p_max - 1/K) / (1 - 1/K)` -- and so cannot
        distinguish one close rival from many distant ones.
        """
        if len(self.probabilities) < 2:
            return None
        ordered = sorted(self.probabilities.values(), reverse=True)
        return ordered[0] - ordered[1]


@dataclass(frozen=True)
class CallRecord:
    """One request, as AGENTS.md requires every model call to be recorded.

    The state is **hashed rather than stored**, for the reason the Ollama
    adapter gives: it contains memory content, which may contain exactly what
    the governance layer exists to keep out of secondary surfaces.
    """

    model: str
    state_sha256: str
    questions: int
    input_tokens: int
    output_tokens: int
    seconds: float
    server_latency_ms: float | None = None

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def noul(instructions: str, yes: str | None = None,
         no: str | None = None) -> dict[str, Any]:
    """A yes/no question. The answer is P(yes).

    `yes`/`no` describe what each verdict means. They are optional and worth
    writing: the model sees the descriptions, not the question id.
    """
    question: dict[str, Any] = {"type": "noul", "instructions": instructions}
    criteria = {k: v for k, v in (("true", yes), ("false", no)) if v}
    if criteria:
        question["criteria"] = criteria
    return question


def choice(instructions: str,
           options: Mapping[str, str | None] | Sequence[str]
           ) -> dict[str, Any]:
    """A multiple-choice question over 1-255 named options.

    Options may be a mapping of name to description, or a bare sequence of
    names. A description is worth giving where the name alone is a bare
    identifier, which in this project it usually is.
    """
    if not isinstance(options, Mapping):
        options = {str(name): None for name in options}
    return {"type": "choice", "instructions": instructions,
            "criteria": dict(options)}


def score(instructions: str, levels: Sequence[str]) -> dict[str, Any]:
    """A rating question over ordered levels, lowest first."""
    return {"type": "score", "instructions": instructions,
            "criteria": list(levels)}


class SystemOneClient:
    """Minimal client over the System One API.

    Points at a local Kev server by default. `calls` accumulates a ledger on
    the client rather than returning it per call, so a caller who never looks
    still records the cost -- the same reasoning as `OllamaClient`.
    """

    def __init__(self, host: str = DEFAULT_HOST, timeout: float = 600.0,
                 model: str = DEFAULT_MODEL, api_key: str | None = None,
                 retries: int = 2) -> None:
        self.host = host.rstrip("/")
        # Generous, because a cold CPU load of these weights is minutes and a
        # timeout loses the run rather than one call.
        self.timeout = timeout
        self.model = model
        self.api_key = api_key
        self.retries = retries
        self.calls: list[CallRecord] = []
        self._sinks: list[Any] = []

    # --- plumbing ---------------------------------------------------------

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(
                self.host + path, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(
                        request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                # A 4xx is a bad request and will not improve on a retry.
                if 400 <= exc.code < 500:
                    raise SystemOneError(
                        f"{exc.code} from {self.host}{path}: {detail}") from exc
                last = exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
            if attempt < self.retries:
                time.sleep(0.5 * (attempt + 1))
        raise SystemOneError(
            f"cannot reach a System One server at {self.host}: {last}. "
            f"Start one with: uv run --extra serve python -m kev.serve "
            f"--run jaredpalmer/kev-0.8b --device cpu --port 8009"
        ) from last

    def available(self) -> list[str]:
        try:
            with urllib.request.urlopen(
                    self.host + "/v1/models", timeout=10) as response:
                data = json.load(response)
        except Exception as exc:  # noqa: BLE001 - availability must not raise
            raise SystemOneError(
                f"cannot list models at {self.host}: {exc}") from exc
        # Kev answers `{"models": [{"name": ...}]}`; TypeSafe's documented
        # shape is OpenAI-ish `{"data": [{"id": ...}]}`. Both are accepted
        # because the point of this client is that one caller reaches either,
        # and the first version read only the second and reported no models
        # against a server that was serving two.
        rows = data
        if isinstance(data, Mapping):
            rows = data.get("models") or data.get("data") or []
        out: list[str] = []
        for row in rows or []:
            if isinstance(row, Mapping):
                name = row.get("name") or row.get("id")
                if name:
                    out.append(str(name))
        return out

    def add_sink(self, sink: Any) -> None:
        """Register a tracing callback, wrapped so it cannot fail a call."""
        self._sinks.append(sink)

    # --- the one call -----------------------------------------------------

    def ask(self, state: Any,
            questions: Mapping[str, Mapping[str, Any]],
            model: str | None = None) -> dict[str, AnswerRecord]:
        """Ask several typed questions about one state, in one request.

        The questions share the text and **cannot read each other**, which is
        what makes a batch cheap rather than a conversation.
        """
        if not questions:
            raise ValueError("at least one question is required")
        payload = {
            "state": state,
            "model": model or self.model,
            "questions": dict(questions),
        }
        started = time.perf_counter()
        result = self._post("/v1/systemone", payload)
        usage = result.get("usage") or {}
        record = CallRecord(
            model=str(result.get("model") or payload["model"]),
            state_sha256=hashlib.sha256(
                json.dumps(state, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
            questions=len(questions),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            seconds=time.perf_counter() - started,
            server_latency_ms=(float(result["latency_ms"])
                               if result.get("latency_ms") is not None
                               else None),
        )
        self.calls.append(record)
        for sink in self._sinks:
            try:
                sink(record, record.model, payload, result)
            except Exception:  # pragma: no cover - exporter is best-effort
                pass
        return parse_answers(result)

    def usage(self, since: int = 0) -> dict[str, float]:
        window = self.calls[since:]
        return {
            "calls": float(len(window)),
            "questions": float(sum(c.questions for c in window)),
            "input_tokens": float(sum(c.input_tokens for c in window)),
            "output_tokens": float(sum(c.output_tokens for c in window)),
            "seconds": sum(c.seconds for c in window),
        }


def parse_answers(result: Mapping[str, Any]) -> dict[str, AnswerRecord]:
    """Turn a response body into `AnswerRecord`s.

    Tolerant of a missing field rather than raising, because a server version
    that adds or renames one should degrade a reported number rather than fail
    a 500-instance run.
    """
    out: dict[str, AnswerRecord] = {}
    for question_id, answer in (result.get("answers") or {}).items():
        if not isinstance(answer, Mapping):
            continue
        kind = str(answer.get("type") or "")
        probabilities = {
            str(k): float(v)
            for k, v in (answer.get("probabilities") or {}).items()
        }
        value = answer.get(kind) if kind in answer else None
        if kind == "noul":
            # The server reports P(yes) alone; keep it as a distribution too so
            # every kind is handled the same way downstream.
            p_true = float(answer.get("noul") or 0.0)
            probabilities = probabilities or {"false": 1.0 - p_true,
                                              "true": p_true}
            value = p_true
        legend = answer.get("legend") or ()
        out[str(question_id)] = AnswerRecord(
            question_id=str(question_id),
            kind=kind,
            answer=value,
            probabilities=probabilities,
            confidence=(float(answer["confidence"])
                        if answer.get("confidence") is not None else None),
            legend=tuple(str(x) for x in legend),
        )
    return out


def expected_calibration_error(pairs: Iterable[tuple[float, bool]],
                               bins: int = 10) -> float | None:
    """Mean |confidence - accuracy| over equal-width probability bins.

    Here rather than in an experiment because **this is the number that decides
    whether a calibrated model is worth anything to this project**, and it is
    the one the vendors report moving by a factor of five with a fitted
    temperature. A model that is accurate on average and confident when wrong
    is useless for an exposure decision, and AUC cannot see that.

    `pairs` is (predicted probability of the positive class, actual outcome).
    Returns None for an empty input rather than 0.0, which would read as
    perfect calibration.
    """
    rows = [(float(p), bool(y)) for p, y in pairs]
    if not rows:
        return None
    total = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        bucket = [r for r in rows
                  if (low <= r[0] < high) or (index == bins - 1 and r[0] == 1.0)]
        if not bucket:
            continue
        mean_p = sum(p for p, _ in bucket) / len(bucket)
        accuracy = sum(1 for _, y in bucket if y) / len(bucket)
        total += (len(bucket) / len(rows)) * abs(mean_p - accuracy)
    return total


def brier_score(pairs: Iterable[tuple[float, bool]]) -> float | None:
    """Mean squared error of the probability against the outcome.

    Reported beside ECE because Kev's model cards use Brier, so this is the
    number that can be compared against their published figures: 0.481 for
    Kev-0.8B on sources it never trained on, 0.269 for Kev-4B.
    """
    rows = [(float(p), bool(y)) for p, y in pairs]
    if not rows:
        return None
    return sum((p - (1.0 if y else 0.0)) ** 2 for p, y in rows) / len(rows)
