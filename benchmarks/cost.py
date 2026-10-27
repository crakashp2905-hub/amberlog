"""End-to-end cost ledger (MF-034, §7A.9).

Every component is counted separately so a cheap query cannot hide an
expensive build: `C_total(N)` is fixed costs plus N times per-query costs plus
the costs that grow with N. `cost_per_safe_success` is `None` when there was
no safe success — never a finite number made up by dividing by one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

FIXED = ("ingest", "embed", "ontology_build", "index")
PER_QUERY = ("query_inference", "retrieval", "agent_tools")
GROWING = ("refresh", "memory_write", "retention", "storage", "host", "human_review", "incident_recovery")


@dataclass
class Ledger:
    ingest: float = 0.0
    embed: float = 0.0
    ontology_build: float = 0.0
    index: float = 0.0
    query_inference: float = 0.0
    retrieval: float = 0.0
    agent_tools: float = 0.0
    refresh: float = 0.0
    memory_write: float = 0.0
    retention: float = 0.0
    storage: float = 0.0
    host: float = 0.0
    human_review: float = 0.0
    incident_recovery: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    model_calls: int = 0
    unit: str = "usd"

    def fixed(self) -> float:
        return sum(getattr(self, k) for k in FIXED)

    def per_query(self) -> float:
        return sum(getattr(self, k) for k in PER_QUERY)

    def total(self, n_queries: int) -> float:
        """Per-query fields are per query; growing fields are totals already incurred for these N."""
        return self.fixed() + n_queries * self.per_query() + sum(getattr(self, k) for k in GROWING)

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def cost_per_safe_success(total: float, safe_successes: int) -> float | None:
    return total / safe_successes if safe_successes > 0 else None


def break_even_queries(expensive: Ledger, cheap: Ledger) -> int | None:
    """Queries after which the arm with the bigger build is cheaper overall; None if never."""
    saving = cheap.per_query() - expensive.per_query()
    extra = expensive.fixed() - cheap.fixed()
    if extra <= 0:
        return 0
    if saving <= 0:
        return None
    n = int(extra // saving) + 1
    return n
