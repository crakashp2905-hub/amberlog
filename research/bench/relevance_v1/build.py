"""Generate relevance_v1. Deterministic, committed as JSON, no randomness."""

import json
import pathlib

OUT = pathlib.Path("D:/Memory/research/bench/relevance_v1")
T0 = 1_700_000_000


def mem(mid, content, **kw):
    base = {
        "id": mid,
        "content": content,
        "type": "semantic",
        "lifecycle_state": "active",
        "scope": "private",
        "tenant_id": "tn_default",
        "capabilities": [],
        "method": "observed",
        "parents": [],
        "recorded_at": T0,
        "valid_from": None,
        "valid_to": None,
        "version": 1,
        "entities": [],
        "source_root": mid,
    }
    base.update(kw)
    return base


def case(case_id, family, task_text, corpus, labels, rationale, **task_kw):
    task = {
        "task_text": task_text,
        "goal": task_kw.pop("goal", ""),
        "constraints": task_kw.pop("constraints", []),
        "entities": task_kw.pop("entities", []),
        "event_time": task_kw.pop("event_time", T0),
        "token_budget": task_kw.pop("token_budget", 400),
        "agent_id": task_kw.pop("agent_id", "ag-bench"),
        "agent_role": task_kw.pop("agent_role", "engineer"),
        "tenant_id": task_kw.pop("tenant_id", "tn_default"),
        "granted_capabilities": task_kw.pop("granted_capabilities", []),
    }
    assert not task_kw, task_kw
    full = {
        "relevant": [],
        "critical": [],
        "irrelevant": [],
        "must_not_expose": [],
        "expect_abstain": False,
        "roles": {},
    }
    full.update(labels)
    ids = {m["id"] for m in corpus}
    for key in ("relevant", "critical", "irrelevant", "must_not_expose"):
        unknown = set(full[key]) - ids
        assert not unknown, (case_id, key, unknown)
    # A memory cannot be both relevant and irrelevant.
    overlap = set(full["relevant"]) & set(full["irrelevant"])
    assert not overlap, (case_id, overlap)
    # Critical implies relevant.
    assert set(full["critical"]) <= set(full["relevant"]), (case_id, "critical ⊄ relevant")
    return {
        "case_id": case_id,
        "family": family,
        "task": task,
        "corpus": corpus,
        "labels": full,
        "rationale": rationale,
    }


CASES = []

# --- direct -----------------------------------------------------------------
CASES.append(case(
    "direct-01", "direct",
    "What is the winter tyre pressure for the yard tug?",
    [
        mem("m1", "Yard tug tyre pressure is 3.5 bar in winter.", entities=["yard-tug"]),
        mem("m2", "The east gate closes at 1800."),
        mem("m3", "Forklift battery cells are replaced every 400 cycles."),
    ],
    {"relevant": ["m1"], "critical": ["m1"], "irrelevant": ["m2", "m3"],
     "roles": {"m1": "necessary"}},
    "m1 states the asked quantity for the asked vehicle and season; the others concern unrelated equipment.",
    entities=["yard-tug"],
))
CASES.append(case(
    "direct-02", "direct",
    "How often should the coastal site cable be swapped?",
    [
        mem("m1", "At the coastal site, swap the signal cable every 90 days due to salt corrosion.",
            entities=["coastal"]),
        mem("m2", "Inland sites swap the signal cable every 2 years.", entities=["inland"]),
        mem("m3", "The coastal site has 14 parking bays.", entities=["coastal"]),
    ],
    {"relevant": ["m1"], "critical": ["m1"], "irrelevant": ["m2", "m3"],
     "roles": {"m1": "necessary"}},
    "m1 answers the interval for the named site. m2 is the same predicate at a different site; m3 shares the site but not the subject.",
    entities=["coastal"],
))

# --- lexical trap -----------------------------------------------------------
CASES.append(case(
    "lexical_trap-01", "lexical_trap",
    "Why does pump 4 overheat?",
    [
        mem("m1", "Pump 4 overheats when valve 7 is partly closed, restricting flow.",
            entities=["pump-4", "valve-7"]),
        mem("m2", "Pump 2 overheats when its impeller is worn; pump 2 overheat reports are common.",
            entities=["pump-2"]),
        mem("m3", "Overheat alarms on the pump deck are logged to the overheat register.",
            entities=["pump-deck"]),
    ],
    {"relevant": ["m1"], "critical": ["m1"], "irrelevant": ["m2", "m3"],
     "roles": {"m1": "necessary"}},
    "m2 and m3 repeat 'pump' and 'overheat' more often than m1 but concern a different unit and a filing procedure; only m1 explains pump 4.",
    entities=["pump-4"],
))
CASES.append(case(
    "lexical_trap-02", "lexical_trap",
    "What is the torque setting for the M12 bolts on the gantry?",
    [
        mem("m1", "Gantry M12 bolts are torqued to 80 Nm.", entities=["gantry"]),
        mem("m2", "Gantry M10 bolts are torqued to 45 Nm; M10 torque is checked with the M10 wrench.",
            entities=["gantry"]),
        mem("m3", "Crane M12 bolts are torqued to 95 Nm.", entities=["crane"]),
    ],
    {"relevant": ["m1"], "critical": ["m1"], "irrelevant": ["m2", "m3"],
     "roles": {"m1": "necessary"}},
    "m2 shares the structure and the word torque but the wrong bolt size; m3 shares the bolt size but the wrong structure.",
    entities=["gantry"],
))

# --- indirect ---------------------------------------------------------------
CASES.append(case(
    "indirect-01", "indirect",
    "Is the conclusion about the pump pressure limit still supported?",
    [
        mem("m1", "Valve 7 is rated to 3.5 bar maximum.", entities=["valve-7"]),
        mem("m2", "The pump inherits valve 7's pressure limit, so the pump is limited to 3.5 bar.",
            entities=["pump", "valve-7"], method="consolidated", parents=[["m1", 1]],
            source_root="m1"),
        mem("m3", "The yard has three pumps."),
    ],
    {"relevant": ["m1", "m2"], "critical": ["m1"], "irrelevant": ["m3"],
     "roles": {"m2": "necessary", "m1": "necessary"}},
    "The conclusion m2 cannot be judged without its premise m1, which a retriever matching only the question's wording will miss.",
    entities=["pump"],
))
CASES.append(case(
    "indirect-02", "indirect",
    "Can we rely on the 90-day cable interval at the new depot?",
    [
        mem("m1", "Salt corrosion drives cable degradation at coastal sites.", entities=["coastal"]),
        mem("m2", "Therefore coastal cables are swapped every 90 days.",
            method="consolidated", parents=[["m1", 1]], entities=["coastal"], source_root="m1"),
        mem("m3", "The new depot is 40 km inland.", entities=["new-depot"]),
        mem("m4", "The canteen reopens in March."),
    ],
    {"relevant": ["m1", "m2", "m3"], "critical": ["m1", "m3"], "irrelevant": ["m4"],
     "roles": {"m1": "necessary", "m2": "background", "m3": "necessary"}},
    "The interval's justification is the coastal premise m1; m3 is the fact that makes it inapplicable. Both are needed to answer honestly.",
    entities=["new-depot"],
))

# --- rare critical ----------------------------------------------------------
CASES.append(case(
    "rare_critical-01", "rare_critical",
    "Procedure for restarting the compressor after a power cut.",
    [
        mem("m1", "Compressor restart: open the bypass, wait for pressure to equalise, then start.",
            entities=["compressor"]),
        mem("m2", "Compressor restart notes are kept in the blue folder.", entities=["compressor"]),
        mem("m3", "Never restart the compressor with the bypass shut: the seal fails at 6 bar.",
            entities=["compressor"]),
        mem("m4", "The compressor was installed in 2019.", entities=["compressor"]),
    ],
    {"relevant": ["m1", "m3"], "critical": ["m3"], "irrelevant": ["m2", "m4"],
     "roles": {"m1": "necessary", "m3": "necessary"}},
    "m3 is the one fact whose omission causes damage, and it is phrased as a prohibition so it shares fewer words with the task than the procedure does.",
    entities=["compressor"],
))
CASES.append(case(
    "rare_critical-02", "rare_critical",
    "Set up the north site generator for the weekend.",
    [
        mem("m1", "North site generator runs on diesel, 200 litre tank.", entities=["north"]),
        mem("m2", "North site generator service interval is 500 hours.", entities=["north"]),
        mem("m3", "The north site fuel gauge reads 30% high; treat 40% as empty.", entities=["north"]),
        mem("m4", "North site has a spare alternator belt.", entities=["north"]),
    ],
    {"relevant": ["m1", "m3"], "critical": ["m3"], "irrelevant": ["m2"],
     "roles": {"m1": "background", "m3": "necessary"}},
    "m3 is a calibration fault that changes the action; it mentions neither 'generator' nor 'set up'.",
    entities=["north"],
))

# --- temporal drift ---------------------------------------------------------
CASES.append(case(
    "temporal_drift-01", "temporal_drift",
    "What is the current east gate closing time?",
    [
        mem("m1", "The east gate closes at 1800.", valid_from=T0 - 86400 * 365,
            valid_to=T0 - 86400 * 30, recorded_at=T0 - 86400 * 365),
        mem("m2", "From last month the east gate closes at 2000.", valid_from=T0 - 86400 * 30,
            valid_to=None, recorded_at=T0 - 86400 * 30),
        mem("m3", "The east gate is 4 m wide."),
    ],
    {"relevant": ["m2"], "critical": ["m2"], "irrelevant": ["m1", "m3"],
     "roles": {"m2": "necessary"}},
    "m1 was true and its validity ended; the task asks for current, so returning m1 is wrong even though it matches the wording closely.",
    entities=["east-gate"],
))
CASES.append(case(
    "temporal_drift-02", "temporal_drift",
    "What did we believe the east gate closing time was last year?",
    [
        mem("m1", "The east gate closes at 1800.", valid_from=T0 - 86400 * 365,
            valid_to=T0 - 86400 * 30, recorded_at=T0 - 86400 * 365),
        mem("m2", "From last month the east gate closes at 2000.", valid_from=T0 - 86400 * 30,
            valid_to=None, recorded_at=T0 - 86400 * 30),
    ],
    {"relevant": ["m1"], "critical": ["m1"], "irrelevant": ["m2"],
     "roles": {"m1": "necessary"}},
    "The same corpus, the opposite answer, because the task's event_time is a year ago. This is the case that proves relevance is task-scoped rather than a property of the memory.",
    event_time=T0 - 86400 * 300,
    entities=["east-gate"],
))

# --- superseded -------------------------------------------------------------
CASES.append(case(
    "superseded-01", "superseded",
    "What is the approved lifting limit for the crane?",
    [
        mem("m1", "Crane lifting limit is 12 tonnes.", lifecycle_state="deprecated",
            version=1, entities=["crane"]),
        mem("m2", "Crane lifting limit is 10 tonnes after the 2026 inspection.",
            version=2, entities=["crane"]),
        mem("m3", "The crane cab has a new seat."),
    ],
    {"relevant": ["m2"], "critical": ["m2"], "irrelevant": ["m1", "m3"],
     "roles": {"m2": "necessary"}},
    "m1 is the superseded figure and is still in the corpus; returning it would authorise an overload.",
    entities=["crane"],
))

# --- conflicting ------------------------------------------------------------
CASES.append(case(
    "conflicting-01", "conflicting",
    "Is the spare battery pack safe to install?",
    [
        mem("m1", "Inspection A found the spare battery pack within tolerance.",
            entities=["battery-pack"], source_root="insp-a"),
        mem("m2", "Inspection B found the spare battery pack cell 3 swollen.",
            entities=["battery-pack"], source_root="insp-b"),
        mem("m3", "The battery pack weighs 24 kg.", entities=["battery-pack"]),
    ],
    {"relevant": ["m1", "m2"], "critical": ["m2"], "irrelevant": ["m3"],
     "roles": {"m1": "contradictory", "m2": "contradictory"}},
    "Two independent inspections disagree under the same conditions. Both belong in the context; returning only the reassuring one is the failure.",
    entities=["battery-pack"],
))

# --- apparent conflict ------------------------------------------------------
CASES.append(case(
    "apparent_conflict-01", "apparent_conflict",
    "Is the adhesive safe to use in the cold store at 2 C?",
    [
        mem("m1", "The adhesive is rated safe at 20 C.", entities=["adhesive"]),
        mem("m2", "The adhesive is not rated below 5 C.", entities=["adhesive"]),
        mem("m3", "The cold store runs at 2 C.", entities=["cold-store"]),
    ],
    {"relevant": ["m2", "m3"], "critical": ["m2", "m3"], "irrelevant": ["m1"],
     "roles": {"m2": "necessary", "m3": "necessary"}},
    "m1 and m2 only appear to conflict: they state different temperature scopes. The task's condition selects m2, and m3 is what establishes the condition.",
    entities=["cold-store", "adhesive"],
))

# --- copied evidence --------------------------------------------------------
CASES.append(case(
    "copied_evidence-01", "copied_evidence",
    "How well supported is the claim that the hoist brake is failing?",
    [
        mem("m1", "Technician report: hoist brake shows delayed engagement.",
            entities=["hoist"], source_root="rep-1"),
        mem("m2", "Per the technician report, the hoist brake engages late.",
            entities=["hoist"], method="imported", parents=[["m1", 1]], source_root="rep-1"),
        mem("m3", "Summary: hoist brake engagement is delayed (from the technician report).",
            entities=["hoist"], method="consolidated", parents=[["m1", 1]], source_root="rep-1"),
        mem("m4", "Independent measurement: hoist brake engagement 0.8 s against a 0.3 s spec.",
            entities=["hoist"], source_root="meas-1"),
    ],
    {"relevant": ["m1", "m4"], "critical": ["m4"], "irrelevant": [],
     "roles": {"m1": "corroborative", "m4": "necessary"}},
    "m2 and m3 are copies of m1 and add no independent support, so a context of m1+m2+m3 looks triply confirmed and is not. m4 is the only second root.",
    entities=["hoist"],
))

# --- near duplicate ---------------------------------------------------------
CASES.append(case(
    "near_duplicate-01", "near_duplicate",
    "Brief me on the forklift before I drive it.",
    [
        mem("m1", "Forklift maximum speed is 12 km/h."),
        mem("m2", "Forklift max speed: 12 km/h."),
        mem("m3", "The forklift tops out at 12 km/h."),
        mem("m4", "Forklift speed limit is 12 km/h indoors."),
        mem("m5", "The forklift's left brake has been replaced and needs bedding in for 20 km."),
    ],
    {"relevant": ["m1", "m5"], "critical": ["m5"], "irrelevant": [],
     "roles": {"m1": "background", "m5": "necessary"}},
    "Four near-duplicates of the speed fact will fill a top-k budget and crowd out m5, which is the only thing that changes how the driver behaves.",
    token_budget=120,
))

# --- constrained ------------------------------------------------------------
CASES.append(case(
    "constrained-01", "constrained",
    "Which cable supplier should we use for the coastal site?",
    [
        mem("m1", "Supplier Alpha offers the cheapest marine-grade cable.", entities=["alpha"]),
        mem("m2", "Supplier Alpha was removed from the approved list in 2026.", entities=["alpha"]),
        mem("m3", "Supplier Beta is on the approved list and stocks marine-grade cable.",
            entities=["beta"]),
    ],
    {"relevant": ["m2", "m3"], "critical": ["m2"], "irrelevant": [],
     "roles": {"m2": "necessary", "m3": "necessary"}},
    "The constraint rules Alpha out, so m2 is what makes the cheapest option inadmissible and m3 is the admissible answer.",
    constraints=["only use suppliers on the approved list"],
    entities=["coastal"],
))

# --- negative evidence ------------------------------------------------------
CASES.append(case(
    "negative_evidence-01", "negative_evidence",
    "Could the charging fault be a failed contactor?",
    [
        mem("m1", "A failed contactor produces exactly this charging fault signature.",
            entities=["contactor"]),
        mem("m2", "The contactor was replaced last week and tested good.", entities=["contactor"]),
        mem("m3", "The charger cabinet was repainted in May."),
    ],
    {"relevant": ["m1", "m2"], "critical": ["m2"], "irrelevant": ["m3"],
     "roles": {"m1": "background", "m2": "contradictory"}},
    "m1 makes the tempting answer attractive; m2 is the fact that rules it out. A retriever ranking only positive support returns m1 alone and confirms the wrong diagnosis.",
    entities=["contactor"],
))

# --- unanswerable -----------------------------------------------------------
CASES.append(case(
    "unanswerable-01", "unanswerable",
    "What is the calibration offset for the south site flow meter?",
    [
        mem("m1", "North site flow meter offset is +0.2.", entities=["north"]),
        mem("m2", "The south site has two flow meters.", entities=["south"]),
        mem("m3", "Flow meters are calibrated annually."),
    ],
    {"relevant": [], "critical": [], "irrelevant": ["m1", "m2", "m3"],
     "expect_abstain": True, "roles": {}},
    "Nothing here gives the asked offset. Returning the north figure or the generic policy is worse than returning nothing, because both read as an answer.",
    entities=["south"],
))

# --- unauthorized -----------------------------------------------------------
CASES.append(case(
    "unauthorized-01", "unauthorized",
    "What is the door code for the chemical store?",
    [
        mem("m1", "Chemical store door procedure: badge at the reader, then the keypad.",
            entities=["chemical-store"]),
        mem("m2", "Chemical store keypad code rotation is handled by site security.",
            entities=["chemical-store"], security_class="restricted",
            capabilities=["security:codes"], scope="private"),
        mem("m3", "The chemical store holds 40 drums."),
    ],
    {"relevant": ["m1", "m2"], "critical": [], "irrelevant": ["m3"],
     "must_not_expose": ["m2"], "roles": {"m1": "necessary", "m2": "necessary"}},
    "m2 is genuinely relevant and the agent holds no security:codes capability. Returning it is a failure *because* it is relevant: this is the case where a better ranker scores worse unless gates sit outside the score.",
    entities=["chemical-store"],
))

# --- retracted --------------------------------------------------------------
CASES.append(case(
    "retracted-01", "retracted",
    "Is the yard tug tyre pressure still 3.5 bar?",
    [
        mem("m1", "Yard tug tyre pressure is 3.5 bar in winter.", entities=["yard-tug"],
            lifecycle_state="quarantined", method="imported"),
        mem("m2", "Yard tug tyre pressure specification is under review.", entities=["yard-tug"]),
        mem("m3", "The yard tug was serviced in March.", entities=["yard-tug"]),
    ],
    {"relevant": ["m1", "m2"], "critical": [], "irrelevant": ["m3"],
     "must_not_expose": ["m1"], "roles": {"m1": "necessary", "m2": "background"}},
    "m1 answers the question and was withdrawn at its origin. PB2 measured acting on origin-retracted knowledge going 17% to 0%; this case is where a relevance score would undo that.",
    entities=["yard-tug"],
))

# --- split ------------------------------------------------------------------
# Deterministic and declared: the *second* case of each family goes to test
# where a family has two, and single-case families stay in dev. Frozen now, so
# no tuning result can move a case across the line later.
dev, test = [], []
seen = {}
for c in CASES:
    seen[c["family"]] = seen.get(c["family"], 0) + 1
    (test if seen[c["family"]] == 2 else dev).append(c)

# --- distractors -----------------------------------------------------------
#
# Every case started with 3–5 memories against k=3, which meant every arm
# returned nearly the whole corpus: recall was 1.0 by construction and there
# was nothing to select. A deliberately broken arm with no relevance signal at
# all scored 0.843 nDCG against the hybrid baseline's 0.832, because with
# k >= corpus size, ranking cannot be wrong.
#
# So every case gets a shared pool of plausible-but-irrelevant depot facts,
# bringing each corpus to ~18 memories. They are on-topic enough to be real
# distractors — same site, same equipment vocabulary — and none of them answers
# any task. Labelled irrelevant, so returning one costs precision.
DISTRACTORS = [
    ("d01", "The depot canteen reopens at 0600 on weekdays."),
    ("d02", "Visitor parking is in bay 12 behind the weighbridge."),
    ("d03", "The weighbridge is calibrated every six months."),
    ("d04", "Hi-vis vests are required beyond the yellow line."),
    ("d05", "The spill kit is mounted beside the fuel bund."),
    ("d06", "Night shift hands over at 0545 in the mess room."),
    ("d07", "The yard speed limit is 8 km/h for all vehicles."),
    ("d08", "Waste oil is collected on the first Tuesday of the month."),
    ("d09", "The site first-aider is based in the gatehouse."),
    ("d10", "Tool crib keys are signed out at the supervisor's desk."),
    ("d11", "The compressor shed door sticks in wet weather."),
    ("d12", "Pallet racking was inspected in February and passed."),
    ("d13", "The diesel bowser holds 1,200 litres when full."),
    ("d14", "Radio channel 3 is reserved for crane movements."),
    ("d15", "The staff noticeboard is updated every Friday."),
]

for c in CASES:
    existing = {m["id"] for m in c["corpus"]}
    for did, text in DISTRACTORS:
        assert did not in existing, did
        c["corpus"].append(mem(did, text))
        c["labels"]["irrelevant"].append(did)

# --- remove the positional signal ------------------------------------------
#
# The cases above were written with the relevant memory first, which turned
# corpus order into a near-perfect ranking signal: a deliberately broken arm
# that returned the corpus in storage order scored 0.869 nDCG against the
# hybrid baseline's 0.832. The benchmark was leaking its own answers.
#
# Shuffled here, in the generator, so the committed JSON carries no positional
# information and the fix is visible in the data rather than hidden in the
# runner. Seeded from the case id so the order is fixed for all time: two
# builds of this script produce byte-identical files.
import random

for c in CASES:
    rng = random.Random(f"relevance_v1/{c['case_id']}")
    rng.shuffle(c["corpus"])

OUT.mkdir(parents=True, exist_ok=True)
for name, cases in (("dev", dev), ("test", test)):
    payload = {
        "benchmark": "relevance_v1",
        "split": name,
        "built_at": "2026-10-11",
        "note": "Frozen. A change means a new benchmark directory, not an edit.",
        "cases": cases,
    }
    (OUT / f"{name}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
print(f"dev {len(dev)} cases, test {len(test)} cases, {len(CASES)} total")
print("families:", sorted({c['family'] for c in CASES}))
