"""Collections: attach agents to a named set of memories, with audited permissions."""

from __future__ import annotations

import secrets
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.events import EventType
from memory_fabric.fabric import PolicyViolation
from memory_fabric.identity import ROLE_AGENT, IdentityError
from memory_fabric.model import LifecycleState
from memory_fabric.service import MemoryService


def ids(fabric: MemoryFabric, agent: str, query: str) -> list[str]:
    return [m.id for m in fabric.retrieve(agent, query, k=5).exposed]


class Attachment(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.fabric.close)
        self.mid = self.fabric.remember("ana", "valve 7 sticks below 4 C")

    def test_attaching_lets_an_agent_read_a_private_member(self) -> None:
        self.assertNotIn(self.mid, ids(self.fabric, "ben", "valve 7"))
        self.fabric.collection_add("winter", self.mid, actor="lead")
        self.fabric.collection_grant("winter", "ben", ["read"], actor="lead")
        self.assertIn(self.mid, ids(self.fabric, "ben", "valve 7"))
        self.assertTrue(self.fabric.use(self.mid, "ben").usable)
        self.assertNotIn(self.mid, ids(self.fabric, "cho", "valve 7"), "only attached agents")

    def test_detaching_takes_it_away_again(self) -> None:
        self.fabric.collection_add("winter", self.mid, actor="lead")
        self.fabric.collection_grant("winter", "ben", ["read"], actor="lead")
        self.fabric.collection_revoke("winter", "ben", actor="lead")
        self.assertNotIn(self.mid, ids(self.fabric, "ben", "valve 7"))

    def test_removing_a_member_takes_it_away(self) -> None:
        self.fabric.collection_add("winter", self.mid, actor="lead")
        self.fabric.collection_grant("winter", "ben", ["read"], actor="lead")
        self.fabric.collection_remove("winter", self.mid, actor="lead")
        self.assertNotIn(self.mid, ids(self.fabric, "ben", "valve 7"))

    def test_a_restricted_memory_cannot_join(self) -> None:
        secret_mid = self.fabric.remember("ana", "salary bands", security_class="restricted")
        with self.assertRaises(PolicyViolation):
            self.fabric.collection_add("winter", secret_mid, actor="lead")

    def test_every_change_is_an_audited_event_with_its_actor(self) -> None:
        self.fabric.collection_add("winter", self.mid, actor="lead")
        self.fabric.collection_grant("winter", "ben", ["read", "approve"], actor="lead")
        events = self.fabric.log.read_types([EventType.COLLECTION_CHANGED])
        self.assertEqual([(e.payload["action"], e.agent_id) for e in events],
                         [("add", "lead"), ("grant", "lead")])
        with self.assertRaises(PolicyViolation):
            self.fabric.collection_add("winter", self.mid, actor="operator")

    def test_it_survives_a_replay(self) -> None:
        self.fabric.collection_add("winter", self.mid, actor="lead")
        self.fabric.collection_grant("winter", "ben", ["read"], actor="lead")
        self.fabric._replay()
        self.assertEqual(self.fabric.collections()["tn_default/winter"],
                         {"members": [self.mid], "grants": {"ben": ["read"]}})

    def test_reach_names_the_collection_readers(self) -> None:
        from memory_fabric.reach import reach

        self.fabric.collection_add("winter", self.mid, actor="lead")
        self.fabric.collection_grant("winter", "ben", ["read"], actor="lead")
        self.assertIn("ben", reach(self.fabric, self.mid).may_read)


class PermissionsOnTheAuthenticatedPath(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MemoryService(path=":memory:")
        self.addCleanup(self.service.close)
        self.fabric = self.service._fabric
        for name in ("ana", "lead", "ben"):
            self.service.register_agent(name, key=secrets.token_bytes(32),
                                        tenant_id="tn_default", roles=(ROLE_AGENT,))
        self.ana = self.service.session(self.service.issue("ana"))
        self.lead = self.service.session(self.service.issue("lead"))
        self.ben = self.service.session(self.service.issue("ben"))
        self.mid = self.ana.remember("pump 3 needs a new seal")
        self.fabric.collection_add("pumps", self.mid, actor="admin")

    def test_without_a_grant_an_agent_cannot_approve(self) -> None:
        with self.assertRaises(IdentityError):
            self.lead.validate(self.mid)

    def test_approve_on_the_collection_lets_an_agent_validate_its_members(self) -> None:
        self.fabric.collection_grant("pumps", "lead", ["approve"], actor="admin")
        self.lead.validate(self.mid)
        self.assertIs(self.fabric.state.memories[self.mid].lifecycle_state, LifecycleState.ACTIVE)

    def test_retract_on_the_collection_lets_an_agent_withdraw_its_members(self) -> None:
        self.fabric.collection_grant("pumps", "lead", ["retract"], actor="admin")
        self.lead.quarantine(self.mid, reason="wrong seal size")
        self.assertIs(self.fabric.state.memories[self.mid].lifecycle_state,
                      LifecycleState.QUARANTINED)

    def test_a_grant_does_not_reach_memories_outside_the_collection(self) -> None:
        self.fabric.collection_grant("pumps", "lead", ["approve"], actor="admin")
        other = self.ana.remember("valve 7 sticks")
        with self.assertRaises(IdentityError):
            self.lead.validate(other)

    def test_write_lets_an_agent_add_its_own_memory(self) -> None:
        with self.assertRaises(IdentityError):
            self.ben.remember("pump 4 too", collection="pumps")
        self.fabric.collection_grant("pumps", "ben", ["write"], actor="admin")
        mid = self.ben.remember("pump 4 needs one too", collection="pumps")
        self.assertIn(mid, self.fabric.collections("tn_default")["pumps"]["members"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
