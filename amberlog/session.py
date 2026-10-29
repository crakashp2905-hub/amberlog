"""AgentSession: a handle scoped to one agent and one episode.

An adapter is given a session, not the fabric. It therefore cannot write as
another agent, attribute a memory to someone else, or record an outcome against
a different episode — the identifiers are bound at construction rather than
passed on every call.

This is scoping, not authentication. Anything holding the raw `Amberlog` can
still write as any agent, which is correct: that is the host. What it removes is
the much more likely failure — an adapter, a tool callback, or a retry path
quietly attributing work to the wrong agent (SECURITY.md, known gaps).
"""

from __future__ import annotations

__stability__ = "stable"

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from .model import MemoryType, ProvenanceMethod, SecurityClass
from .projections import Episode

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import Amberlog, RetrievalResult


class SessionClosed(RuntimeError):
    """Raised when a closed session is used again."""


@dataclass
class AgentSession:
    """One agent working one episode."""

    fabric: "Amberlog"
    agent_id: str
    episode: Episode
    _closed: bool = field(default=False, init=False, repr=False)
    _step: int = field(default=0, init=False, repr=False)

    # --- reading ---------------------------------------------------------

    def recall(
        self,
        query: str,
        k: int = 5,
        context: Mapping[str, Any] | None = None,
        include_contested: bool = False,
        pool: int | None = None,
    ) -> "RetrievalResult":
        """Retrieve memories for this episode, logging the exposure decisions.

        The step counter advances on every call, so a multi-step episode records
        *when* within the episode a memory was seen.
        """
        self._check_open()
        self._step += 1
        return self.fabric.retrieve(
            agent_id=self.agent_id,
            query=query,
            context=context if context is not None else self.episode.context,
            k=k,
            episode_id=self.episode.id,
            include_contested=include_contested,
            pool=pool,
            step=self._step,
        )

    # --- writing ---------------------------------------------------------

    def remember(
        self,
        content: str,
        type: str | MemoryType = MemoryType.SEMANTIC,
        context: Mapping[str, Any] | None = None,
        parents: Sequence[tuple[str, int]] = (),
        method: str | ProvenanceMethod = ProvenanceMethod.OBSERVED,
        security_class: str | SecurityClass = SecurityClass.INTERNAL,
        capabilities: Sequence[str] = (),
    ) -> str:
        """Write a memory attributed to this agent and this episode.

        `agent_id` and `source_episodes` are not parameters: an adapter holding
        this session cannot claim the memory came from somewhere else.

        The memory lands as a candidate unless the fabric is configured
        otherwise, so an agent writing something down does not by itself make it
        retrievable by anyone.
        """
        self._check_open()
        return self.fabric.remember(
            agent_id=self.agent_id,
            content=content,
            type=type,
            context=context if context is not None else self.episode.context,
            source_episodes=[self.episode.id],
            parents=parents,
            method=method,
            security_class=security_class,
            capabilities=capabilities,
            episode_id=self.episode.id,
        )

    def cite(self, memory_id: str) -> None:
        """Note that the agent says it used a memory.

        Self-reported and therefore never an input to value estimation; it is
        kept as a diagnostic, to compare against what the exposure log shows.
        """
        self._check_open()
        self.fabric.cite(self.agent_id, self.episode.id, memory_id, step=self._step)

    # --- finishing -------------------------------------------------------

    def record_outcome(self, outcome: float, verifier_id: str) -> None:
        """Record the verified outcome of this episode.

        The fabric refuses a `verifier_id` equal to the acting agent, so a
        session cannot score its own work (SECURITY.md T2).
        """
        self._check_open()
        self.fabric.record_outcome(self.episode.id, outcome, verifier_id=verifier_id)

    def close(self) -> None:
        self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            raise SessionClosed(f"session for episode {self.episode.id} is closed")

    def __enter__(self) -> "AgentSession":
        return self

    def __exit__(self, *exc: object) -> None:
        # Deliberately does not record an outcome. An episode that ended without
        # a verified result has no outcome, and inventing one — even a zero —
        # would feed a fabricated number into every estimate downstream.
        self.close()

    @property
    def episode_id(self) -> str:
        return self.episode.id
