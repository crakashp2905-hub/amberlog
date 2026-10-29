"""M1: a memory objective decides relevance before retrieval ranks anything."""

from __future__ import annotations

import json
import unittest

from amberlog import Amberlog
from amberlog.events import EventType
from amberlog.objective import MemoryObjective, Rule, compile_objective, sanity, validate

OBJ = MemoryObjective(
    "Night shift at Brook: approved Brook procedures and plant-wide safety rules only.",
    include=((Rule("plant", "eq", "brook"), Rule("status", "eq", "approved")),
             (Rule("plant", "eq", "all"),)),
    exclude=(Rule("source", "eq", "vendor"),),
)


class Rules(unittest.TestCase):
    def test_include_is_an_or_of_and_groups_and_exclude_wins(self) -> None:
        self.assertTrue(OBJ.admits({"plant": "brook", "status": "approved"}))
        self.assertTrue(OBJ.admits({"plant": "all", "status": "approved"}))
        self.assertFalse(OBJ.admits({"plant": "brook", "status": "draft"}))
        self.assertFalse(OBJ.admits({"plant": "ashby", "status": "approved"}))
        self.assertFalse(OBJ.admits({"plant": "brook", "status": "approved", "source": "vendor"}))
        self.assertFalse(OBJ.admits({}), "a missing field satisfies nothing")

    def test_it_round_trips_and_renders_as_agent_rules(self) -> None:
        self.assertEqual(MemoryObjective.from_json(OBJ.to_json()), OBJ)
        text = OBJ.prompt()
        self.assertIn("Relevant: notes where plant is 'brook' and status is 'approved'.", text)
        self.assertIn("Irrelevant: notes where source is 'vendor'", text)

    def test_validation_drops_what_the_store_cannot_have(self) -> None:
        fields = {"plant": ["ashby", "brook", "all"], "status": ["approved", "draft"]}
        raw = {"include": [[{"field": "plant", "op": "eq", "value": "brook"},
                            {"field": "colour", "op": "eq", "value": "red"}]],
               "exclude": [{"field": "status", "op": "eq", "value": "archived"},
                           {"field": "status", "op": "bogus", "value": "x"}]}
        objective = validate(raw, fields, "s")
        self.assertEqual(objective.include, ((Rule("plant", "eq", "brook"),),))
        self.assertEqual(objective.exclude, ())
        self.assertEqual(len(objective.dropped), 3)


class Robustness(unittest.TestCase):
    def test_a_proposed_value_takes_the_fields_type(self) -> None:
        objective = validate({"include": [[{"field": "revision", "op": "eq", "value": "2026"}]],
                              "exclude": []}, {"revision": [2025, 2026]}, "s")
        self.assertEqual(objective.include, ((Rule("revision", "eq", 2026),),))
        self.assertTrue(objective.admits({"revision": 2026}))

    def test_an_objective_that_admits_nothing_is_refused(self) -> None:
        contexts = [{"source": "staff"}, {"source": "vendor"}]
        blank = MemoryObjective("s", exclude=(Rule("source", "in", ["staff", "vendor"]),))
        self.assertIn("admits none", sanity(blank, contexts) or "")
        self.assertIsNone(sanity(OBJ, [{"plant": "all", "status": "approved"}]))


class Retrieval(unittest.TestCase):
    def test_an_excluded_memory_is_never_ranked_or_logged(self) -> None:
        f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        good = f.remember("ana", "Pump P4 restart: hold 4 bar for two minutes.", scope="team",
                          context={"plant": "brook", "status": "approved"})
        draft = f.remember("ana", "Pump P4 restart: hold 6 bar for two minutes.", scope="team",
                           context={"plant": "brook", "status": "draft"})
        other = f.remember("ana", "Pump P4 restart: hold 5 bar for two minutes.", scope="team",
                           context={"plant": "ashby", "status": "approved"})
        plain = {m.id for m in f.retrieve("ben", "pump P4 restart bar", k=5).exposed}
        self.assertEqual(plain, {good, draft, other})
        before = f.log.head_seq
        result = f.retrieve("ben", "pump P4 restart bar", k=5, objective=OBJ)
        self.assertEqual([m.id for m in result.exposed], [good])
        logged = {e.payload["memory_id"] for e in f.log.read()
                  if (e.seq or 0) > before and e.type == EventType.EXPOSURE_DECIDED}
        self.assertEqual(logged, {good})


class FakeClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def chat(self, model, messages, **kwargs):
        self.seen = messages
        return {"message": {"content": self.reply}}


class Compile(unittest.TestCase):
    def test_a_compiled_objective_is_validated(self) -> None:
        reply = json.dumps({"include": [[{"field": "plant", "op": "eq", "value": "brook"}]],
                            "exclude": [{"field": "source", "op": "eq", "value": "vendor"}]})
        client = FakeClient(reply)
        objective = compile_objective("Brook only, no vendor notes.",
                                      {"plant": ["brook", "ashby"], "source": ["vendor", "staff"]},
                                      client, "m")
        self.assertTrue(objective.admits({"plant": "brook", "source": "staff"}))
        self.assertFalse(objective.admits({"plant": "brook", "source": "vendor"}))
        self.assertIn("plant: one of", client.seen[0]["content"])

    def test_an_unparseable_reply_admits_everything_and_says_so(self) -> None:
        objective = compile_objective("x", {"plant": ["brook"]}, FakeClient("not json"), "m")
        self.assertTrue(objective.admits({"plant": "ashby"}))
        self.assertIn("unparseable", objective.dropped[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
