"""Memory Fabric — governed agent memory with provenance and value estimation.

Product-first P1 (see ROADMAP.md). The governance path is complete; causal
credit ships two estimators, with the doubly-robust, paired-replay and amortized
ones due at P4.

    from memory-fabric import MemoryFabric

    fabric = MemoryFabric("memory.db")
    ep  = fabric.start_episode("agent-a", task_id="onboard-42", context={"team": "sales"})
    mid = fabric.remember("agent-a", "Email follow-up beats calling after a failed onboarding.")
    fabric.validate(mid, actor="reviewer")
    hits = fabric.retrieve("agent-a", "how to follow up?", episode_id=ep.id)
    fabric.record_outcome(ep.id, outcome=1.0, verifier_id="env")
    print(fabric.explain(mid).narrative())
"""

__stability__ = "stable"

from .estimators import IPSEstimator, NaiveUsageEstimator, ValueEstimator
from .eventlog import EventLog
from .events import Event, EventType
from .explain import Explanation
from .exposure import (
    AlwaysExposePolicy,
    Candidate,
    EpsilonGreedyPolicy,
    ExposureDecision,
    ExposurePolicy,
    TopKPolicy,
)
from .fabric import (
    FabricError,
    HealthReport,
    MemoryFabric,
    NotFound,
    PolicyViolation,
    RetrievalResult,
    TenantView,
)
from .federation import (
    FederationSummary,
    OfferResult,
    PropagationResult,
    describe,
    offer,
    offer_many,
    propagate_retraction,
)
from .identity import (
    DEFAULT_TENANT,
    InMemoryRevocations,
    RevocationStore,
    SqliteRevocations,
    ROLE_AGENT,
    ROLE_AUDITOR,
    ROLE_OPERATOR,
    Credential,
    IdentityError,
    Principal,
    PrincipalRegistry,
    new_tenant_id,
)
from .governance import Firewall, FirewallRuling, RetentionPolicy, SensitiveDataDetector
from .lineage import LineageGraph, LineageView
from .model import (
    SCHEMA_VERSION,
    WEAK_BASES,
    FirewallDecision,
    LifecycleState,
    Memory,
    MemoryStats,
    MemoryType,
    Provenance,
    ProvenanceMethod,
    Scope,
    SecurityClass,
    ValueEstimate,
    WithdrawalBasis,
)
from .projections import Episode, Projection
from .relevance import (
    CONTRACT_VERSION,
    MISSING,
    ContextPackage,
    ContextSnapshot,
    ReasonCode,
    RelevanceAssessment,
    RelevanceEvidence,
    RelevanceLabel,
    SelectionDecision,
)
from .service import MemoryService, Session
from .session import AgentSession, SessionClosed
from .vectors import Embedder, HashingEmbedder, VectorIndex

__version__ = "0.14.0"

__all__ = [
    "RevocationStore",
    "InMemoryRevocations",
    "SqliteRevocations",
    "CONTRACT_VERSION",
    "MISSING",
    "SelectionDecision",
    "ReasonCode",
    "RelevanceLabel",
    "RelevanceEvidence",
    "RelevanceAssessment",
    "ContextPackage",
    "ContextSnapshot",
    "Session",
    "MemoryService",
    "new_tenant_id",
    "ROLE_AUDITOR",
    "ROLE_OPERATOR",
    "ROLE_AGENT",
    "DEFAULT_TENANT",
    "PrincipalRegistry",
    "Principal",
    "IdentityError",
    "Credential",
    "TenantView",
    "SCHEMA_VERSION",
    "WithdrawalBasis",
    "WEAK_BASES",
    "__version__",
    # facade
    "MemoryFabric",
    "RetrievalResult",
    "HealthReport",
    "FabricError",
    "NotFound",
    "PolicyViolation",
    # model
    "Memory",
    "MemoryStats",
    "MemoryType",
    "Provenance",
    "ProvenanceMethod",
    "Scope",
    "LifecycleState",
    "SecurityClass",
    "FirewallDecision",
    "ValueEstimate",
    # log and projections
    "EventLog",
    "Event",
    "EventType",
    "Projection",
    "Episode",
    # agent integration
    "AgentSession",
    "SessionClosed",
    # retrieval and exposure
    "Embedder",
    "HashingEmbedder",
    "VectorIndex",
    "Candidate",
    "ExposureDecision",
    "ExposurePolicy",
    "TopKPolicy",
    "EpsilonGreedyPolicy",
    "AlwaysExposePolicy",
    # value
    "ValueEstimator",
    "NaiveUsageEstimator",
    "IPSEstimator",
    # governance
    "Firewall",
    "FirewallRuling",
    "SensitiveDataDetector",
    "RetentionPolicy",
    # federation
    "offer",
    "offer_many",
    "describe",
    "OfferResult",
    "FederationSummary",
    "PropagationResult",
    "propagate_retraction",
    # provenance
    "LineageGraph",
    "LineageView",
    "Explanation",
]
