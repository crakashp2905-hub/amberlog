"""Seed a store that exercises every panel of both surfaces.

Not a test fixture and not an example of good agent design: a deliberately messy
store, so the dashboard and CLI can be looked at with something in every state —
a poisoning and its retraction, an unresolved disagreement, a leaked secret,
episodes with and without verified outcomes, and enough randomised exposure to
give one memory a real comparison group.
"""

from __future__ import annotations

import random
from typing import Any

from .exposure import EpsilonGreedyPolicy, TopKPolicy
from .fabric import MemoryFabric
from .model import MemoryType, WithdrawalBasis

DAY_MS = 86_400_000


def seed(fabric: MemoryFabric) -> dict[str, Any]:
    rng = random.Random(7)
    # Episodes are backdated so retention has something to act on.
    start = fabric.now() - 120 * DAY_MS
    clock = {"now": start}
    original_clock = fabric._clock
    fabric._clock = lambda: clock["now"]
    original_policy = fabric.policy
    fabric.auto_activate = True

    def advance(ms: int) -> None:
        clock["now"] += ms

    try:
        # --- a healthy procedure with real evidence --------------------------
        # Randomised exposure, so this memory gets both arms and a contrastive
        # estimate becomes possible.
        fabric.policy = EpsilonGreedyPolicy(epsilon=0.4, rank_by="relevance")

        retry = fabric.remember(
            "ops-agent",
            "Retry a failed deploy once after 30s; a second retry has never helped.",
            type=MemoryType.PROCEDURAL,
            context={"domain": "deploy", "tags": ["runbook"]},
            capabilities=["shell"], scope="team",
        )
        # Written for its effect on the store: a nearby memory the demo's
        # queries must not surface. Nothing reads the id.
        fabric.remember(
            "ops-agent",
            "The staging cluster runs in eu-west-2.",
            context={"domain": "deploy"}, scope="team",
        )

        for index in range(40):
            advance(DAY_MS // 8)
            episode = fabric.start_episode(
                "ops-agent", f"deploy-{4100 + index}", {"domain": "deploy"}
            )
            result = fabric.retrieve(
                "ops-agent", "a deploy failed, should I retry it?", k=1, episode_id=episode.id
            )
            exposed = {m.id for m in result.exposed}
            # The retry procedure genuinely helps; the distractor does nothing.
            outcome = 0.45 + (0.35 if retry in exposed else 0.0) + rng.uniform(-0.05, 0.05)
            fabric.record_outcome(episode.id, round(min(outcome, 1.0), 3), verifier_id="ci")

        # --- a poisoning, its derivatives, and the retraction ---------------
        fabric.policy = TopKPolicy("relevance")
        advance(DAY_MS)

        rig_episode = fabric.start_episode(
            "diagnostic-agent", "battery-anomaly-4471", {"domain": "ev"}
        )
        observation = fabric.remember(
            "diagnostic-agent",
            "The battery temperature threshold is 45 degrees C.",
            context={"domain": "ev", "vehicle": "model-x"},
            source_episodes=[rig_episode.id], scope="team",
        )
        fabric.record_outcome(rig_episode.id, 1.0, verifier_id="test-rig")

        belief = fabric.derive(
            "diagnostic-agent",
            "Warn the operator whenever the pack exceeds 45 degrees C.",
            parents=[observation], scope="team",
        )
        procedure = fabric.derive(
            "ops-agent",
            "Procedure: poll pack temperature every 5s, warn above 45, shut down above 60.",
            parents=[belief],
            type=MemoryType.PROCEDURAL, scope="team",
        )
        # Someone tried to share it and was refused: the attempt is on record.
        fabric.share(procedure, "team", granted_capabilities=["telemetry"])

        advance(2 * DAY_MS)
        fabric.quarantine(
            observation,
            reason="source test rig was misconfigured; readings invalid",
            actor="safety-team",
            # Evidence about the memory itself, which is the only kind that
            # supports a withdrawal. The demo states it because the attention
            # list flags a withdrawal that does not, and the showcase should
            # model the practice rather than trip the warning.
            basis=WithdrawalBasis.CONTRADICTED,
        )

        # --- an unresolved disagreement -------------------------------------
        advance(DAY_MS)
        cache_a = fabric.remember(
            "search-agent",
            "Cache embeddings for 24h; recomputing them is the main latency cost.",
            context={"domain": "search"}, scope="team",
        )
        cache_b = fabric.remember(
            "eval-agent",
            "Never cache embeddings beyond an hour; stale vectors cause silent recall drops.",
            context={"domain": "search"}, scope="team",
        )
        fabric.challenge(
            [cache_a, cache_b],
            evidence="both observed in production, under conditions nobody has pinned down",
            detector_id="manual",
            confidence=0.9,
        )

        # --- a secret an agent tried to memorise ----------------------------
        advance(DAY_MS)
        fabric.remember(
            "onboarding-agent",
            "To deploy, export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE and run make ship.",
            context={"domain": "deploy"}, scope="team",
        )

        # --- a rare, high-impact memory retention must not delete -----------
        fabric.remember(
            "ops-agent",
            "If the primary database corrupts, restore from the 03:00 snapshot before "
            "failing over; failing over first overwrites the good replica.",
            type=MemoryType.PROCEDURAL,
            context={"domain": "db", "tags": ["critical", "rare"], "impact": 0.95}, scope="team",
        )

        # --- an aging unused candidate for retention to catch ---------------
        stale = fabric.remember(
            "research-agent",
            "The vendor's 2024 pricing page listed tier 3 at $400/month.",
            context={"domain": "vendor"}, scope="team",
        )
        fabric.forget(stale, reason="pricing superseded", actor="research-agent")

        # --- an episode with no verified outcome ----------------------------
        advance(DAY_MS)
        orphan = fabric.start_episode("search-agent", "tune-recall-88", {"domain": "search"})
        fabric.retrieve("search-agent", "should I cache embeddings?", k=2, episode_id=orphan.id)

        # Return the clock to the present so ages read sensibly.
        clock["now"] = original_clock()
        return {
            "memories": len(fabric.state.memories),
            "episodes": len(fabric.state.episodes),
            "events": len(fabric.log),
        }
    finally:
        fabric._clock = original_clock
        fabric.policy = original_policy
