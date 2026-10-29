"""Ingesting existing conversation logs as episodic memories.

Most deployments have transcripts before they have a fabric. This turns them
into episodes with provenance, so the store starts from real history rather than
from nothing.

Deliberately does no extraction. Turning a transcript into semantic claims is a
judgement call that needs a model, and a claim invented by a summariser with no
evidence behind it is the thing provenance exists to prevent. The transcript
becomes an episodic record; consolidating it into beliefs is a separate,
attributable step.
"""

from __future__ import annotations

__stability__ = "stable"

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from ..model import MemoryType, ProvenanceMethod

if TYPE_CHECKING:  # pragma: no cover
    from ..fabric import Amberlog

MAX_TURN_CHARS = 2000


@dataclass(frozen=True)
class Turn:
    role: str
    content: str

    @staticmethod
    def coerce(value: "Turn | Mapping[str, Any]") -> "Turn":
        if isinstance(value, Turn):
            return value
        content = value.get("content", "")
        if isinstance(content, list):
            # Claude-style content blocks: keep the text, drop images and
            # tool plumbing, which do not belong in an episodic record.
            content = "\n".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return Turn(role=str(value.get("role", "unknown")), content=str(content))


def render_transcript(turns: Sequence[Turn], max_turn_chars: int = MAX_TURN_CHARS) -> str:
    lines: list[str] = []
    for turn in turns:
        text = " ".join(turn.content.split())
        if len(text) > max_turn_chars:
            text = text[: max_turn_chars - 1].rstrip() + "…"
        if text:
            lines.append(f"{turn.role}: {text}")
    return "\n".join(lines)


def ingest_transcript(
    fabric: "Amberlog",
    agent_id: str,
    task_id: str,
    turns: Iterable["Turn | Mapping[str, Any]"],
    context: Mapping[str, Any] | None = None,
    outcome: float | None = None,
    verifier_id: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """Record one past conversation as an episode plus an episodic memory.

    An `outcome` may be supplied when the transcript's result is known and was
    established by something other than the agent — a test suite, a ticket
    resolution, a human review. It still needs a `verifier_id`, and the fabric
    still refuses one equal to the agent.

    Returns the episode id, the memory id, and whether the content tripped the
    ingest screen.
    """
    coerced = [Turn.coerce(turn) for turn in turns]
    body = render_transcript(coerced)
    if not body:
        raise ValueError("transcript has no text content")

    episode = fabric.start_episode(agent_id, task_id, context or {})
    content = f"{summary.strip()}\n\n{body}" if summary else body

    memory_id = fabric.remember(
        agent_id=agent_id,
        content=content,
        type=MemoryType.EPISODIC,
        context=context or {},
        source_episodes=[episode.id],
        method=ProvenanceMethod.IMPORTED,
        episode_id=episode.id,
    )

    if outcome is not None:
        if not verifier_id:
            raise ValueError("an imported outcome needs a verifier_id")
        fabric.record_outcome(episode.id, outcome, verifier_id=verifier_id)

    memory = fabric.get(memory_id)
    return {
        "episode_id": episode.id,
        "memory_id": memory_id,
        "turns": len(coerced),
        "lifecycle_state": memory.lifecycle_state.value,
        "quarantined": memory.lifecycle_state.value == "quarantined",
    }


def ingest_many(
    fabric: "Amberlog",
    agent_id: str,
    transcripts: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Ingest a batch. Each entry needs `task_id` and `turns`."""
    return [
        ingest_transcript(
            fabric,
            agent_id=entry.get("agent_id", agent_id),
            task_id=entry["task_id"],
            turns=entry["turns"],
            context=entry.get("context"),
            outcome=entry.get("outcome"),
            verifier_id=entry.get("verifier_id"),
            summary=entry.get("summary"),
        )
        for entry in transcripts
    ]
