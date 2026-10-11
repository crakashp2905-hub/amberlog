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

# ===========================================================================
# Cases 3 and 4 of each family. Added 2026-10-11 because sample size became the
# binding constraint: 15 dev and 5 test cases cannot separate arms that differ
# by 0.05, which is the size of the differences the benchmark was being asked
# to adjudicate.
#
# The split rule is extended rather than rewritten — cases 1 and 3 to dev, 2
# and 4 to test — so every one of the original 20 stays exactly where it was. A
# frozen split that moved cases would invalidate every measurement taken
# against it.
# ===========================================================================

# --- direct -----------------------------------------------------------------
CASES.append(case(
    "direct-03", "direct",
    "What grade of hydraulic oil does the tipper take?",
    [
        mem("m1", "The tipper uses ISO 46 hydraulic oil.", entities=["tipper"]),
        mem("m2", "The loader uses ISO 32 hydraulic oil.", entities=["loader"]),
        mem("m3", "Hydraulic oil is stored in the bunded cabinet."),
    ],
    {"relevant": ["m1"], "critical": ["m1"], "irrelevant": ["m2", "m3"],
     "roles": {"m1": "necessary"}},
    "m1 gives the grade for the named vehicle; m2 is the same predicate for a different one and m3 is about storage rather than grade.",
    entities=["tipper"],
))
CASES.append(case(
    "direct-04", "direct",
    "Who signs off a lifting plan?",
    [
        mem("m1", "A lifting plan is signed off by the appointed person, not the crane operator.",
            entities=["lifting-plan"]),
        mem("m2", "Lifting plans are filed in the site office for seven years.",
            entities=["lifting-plan"]),
        mem("m3", "The crane operator holds a CPCS card."),
    ],
    {"relevant": ["m1"], "critical": ["m1"], "irrelevant": ["m2", "m3"],
     "roles": {"m1": "necessary"}},
    "m1 answers who signs; m2 shares the subject but answers retention, and m3 mentions the role m1 explicitly excludes.",
    entities=["lifting-plan"],
))

# --- lexical trap -----------------------------------------------------------
CASES.append(case(
    "lexical_trap-03", "lexical_trap",
    "What causes the chiller to trip on low pressure?",
    [
        mem("m1", "The chiller trips on low pressure when the condenser fan fails.",
            entities=["chiller"]),
        mem("m2", "The chiller trips on high pressure when the strainer blocks; high pressure trips are logged separately.",
            entities=["chiller"]),
        mem("m3", "Low pressure alarms on the boiler indicate a feedwater fault.",
            entities=["boiler"]),
    ],
    {"relevant": ["m1"], "critical": ["m1"], "irrelevant": ["m2", "m3"],
     "roles": {"m1": "necessary"}},
    "m2 matches the equipment and the word pressure but the opposite fault; m3 matches the fault but the wrong equipment. Only m1 matches both.",
    entities=["chiller"],
))
CASES.append(case(
    "lexical_trap-04", "lexical_trap",
    "How long is the curing time for the floor paint in bay 3?",
    [
        mem("m1", "Bay 3 floor paint cures in 12 hours.", entities=["bay-3"]),
        mem("m2", "Bay 3 wall paint cures in 4 hours; wall paint curing is faster than floor.",
            entities=["bay-3"]),
        mem("m3", "Bay 5 floor paint cures in 24 hours.", entities=["bay-5"]),
    ],
    {"relevant": ["m1"], "critical": ["m1"], "irrelevant": ["m2", "m3"],
     "roles": {"m1": "necessary"}},
    "m2 shares the bay and mentions floor curing while answering about walls; m3 shares the surface and the predicate at a different bay.",
    entities=["bay-3"],
))

# --- indirect ---------------------------------------------------------------
CASES.append(case(
    "indirect-03", "indirect",
    "Should we still trust the recommended torque for the mounting bolts?",
    [
        mem("m1", "The mounting bolts are grade 8.8.", entities=["mounting-bolts"]),
        mem("m2", "Grade 8.8 bolts at this diameter take 110 Nm, so the mounting bolts take 110 Nm.",
            method="consolidated", parents=[["m1", 1]], entities=["mounting-bolts"],
            source_root="m1"),
        mem("m3", "The torque wrench was calibrated in June."),
    ],
    {"relevant": ["m1", "m2"], "critical": ["m1"], "irrelevant": ["m3"],
     "roles": {"m1": "necessary", "m2": "necessary"}},
    "The recommendation m2 rests entirely on the grade claim m1; judging whether to trust it requires seeing the premise, which shares no wording with the question.",
    entities=["mounting-bolts"],
))
CASES.append(case(
    "indirect-04", "indirect",
    "Is the two-person rule for the roof hatch still justified?",
    [
        mem("m1", "The roof hatch opens onto an unguarded edge.", entities=["roof-hatch"]),
        mem("m2", "Because the edge is unguarded, the roof hatch requires two people.",
            method="consolidated", parents=[["m1", 1]], entities=["roof-hatch"],
            source_root="m1"),
        mem("m3", "A guardrail was installed along the roof edge in August.",
            entities=["roof-hatch"]),
        mem("m4", "The roof hatch is 900 mm square.", entities=["roof-hatch"]),
    ],
    {"relevant": ["m1", "m2", "m3"], "critical": ["m1", "m3"], "irrelevant": ["m4"],
     "roles": {"m1": "necessary", "m2": "background", "m3": "necessary"}},
    "The rule's justification is m1; m3 is the fact that removes it. Answering honestly needs the premise and the thing that invalidates it, neither of which restates the question.",
    entities=["roof-hatch"],
))

# --- rare critical ---------------------------------------------------------
CASES.append(case(
    "rare_critical-03", "rare_critical",
    "Walk me through swapping the battery on the pallet truck.",
    [
        mem("m1", "Pallet truck battery swap: isolate, unclip the retainer, slide out on the roller bed.",
            entities=["pallet-truck"]),
        mem("m2", "Pallet truck batteries weigh 180 kg.", entities=["pallet-truck"]),
        mem("m3", "The roller bed latch on this unit is broken; the battery will slide off if unsupported.",
            entities=["pallet-truck"]),
        mem("m4", "Pallet truck batteries are charged overnight.", entities=["pallet-truck"]),
    ],
    {"relevant": ["m1", "m3"], "critical": ["m3"], "irrelevant": ["m4"],
     "roles": {"m1": "necessary", "m3": "necessary"}},
    "m3 is the defect that makes the documented procedure dangerous on this unit, and it reads as a complaint rather than an instruction so it shares little with the task wording.",
    entities=["pallet-truck"],
))
CASES.append(case(
    "rare_critical-04", "rare_critical",
    "Prepare the weighbridge for the morning deliveries.",
    [
        mem("m1", "Weighbridge start-up: power on, zero the deck, run the test weight.",
            entities=["weighbridge"]),
        mem("m2", "The weighbridge test weight is kept in the gatehouse.",
            entities=["weighbridge"]),
        mem("m3", "Zeroing the weighbridge with a vehicle on the deck bakes in an offset that persists until the next calibration.",
            entities=["weighbridge"]),
        mem("m4", "The weighbridge was resurfaced in 2024.", entities=["weighbridge"]),
    ],
    {"relevant": ["m1", "m3"], "critical": ["m3"], "irrelevant": ["m4"],
     "roles": {"m1": "necessary", "m3": "necessary"}},
    "m3 turns a routine step into a lasting fault and is phrased as a consequence, not a procedure, so similarity to the task is weak.",
    entities=["weighbridge"],
))

# --- temporal drift ---------------------------------------------------------
CASES.append(case(
    "temporal_drift-03", "temporal_drift",
    "What is the current speed limit in the yard?",
    [
        mem("m1", "The yard speed limit is 8 km/h.", valid_from=T0 - 86400 * 600,
            valid_to=T0 - 86400 * 60, recorded_at=T0 - 86400 * 600),
        mem("m2", "The yard speed limit was reduced to 5 km/h two months ago.",
            valid_from=T0 - 86400 * 60, valid_to=None, recorded_at=T0 - 86400 * 60),
        mem("m3", "Yard speed is enforced by the gate camera."),
    ],
    {"relevant": ["m2"], "critical": ["m2"], "irrelevant": ["m1", "m3"],
     "roles": {"m2": "necessary"}},
    "m1 is the superseded limit and still in the corpus; the task asks for current, so returning it would authorise driving too fast.",
    entities=["yard"],
))
CASES.append(case(
    "temporal_drift-04", "temporal_drift",
    "Which supplier were we using for gloves last winter?",
    [
        mem("m1", "Gloves come from Supplier Delta.", valid_from=T0 - 86400 * 500,
            valid_to=T0 - 86400 * 120, recorded_at=T0 - 86400 * 500,
            entities=["delta"]),
        mem("m2", "Gloves now come from Supplier Echo.", valid_from=T0 - 86400 * 120,
            valid_to=None, recorded_at=T0 - 86400 * 120, entities=["echo"]),
        mem("m3", "Glove sizes stocked are M, L and XL."),
    ],
    {"relevant": ["m1"], "critical": ["m1"], "irrelevant": ["m2", "m3"],
     "roles": {"m1": "necessary"}},
    "A historical question: the correct answer is the memory whose validity has ended, and the current one is wrong. The mirror of temporal_drift-03 over the same mechanism.",
    event_time=T0 - 86400 * 200,
    entities=["gloves"],
))

# --- superseded -------------------------------------------------------------
CASES.append(case(
    "superseded-03", "superseded",
    "What is the maximum stack height for the pallets?",
    [
        mem("m1", "Pallets may be stacked four high.", lifecycle_state="deprecated",
            version=1, entities=["pallets"]),
        mem("m2", "Pallets may be stacked three high after the racking inspection.",
            version=2, entities=["pallets"]),
        mem("m3", "Pallets are 1200 x 1000 mm.", entities=["pallets"]),
    ],
    {"relevant": ["m2"], "critical": ["m2"], "irrelevant": ["m1", "m3"],
     "roles": {"m2": "necessary"}},
    "m1 is the superseded height and remains in the corpus; returning it would authorise an unsafe stack.",
    entities=["pallets"],
))
CASES.append(case(
    "superseded-04", "superseded",
    "How many first-aiders does the site need on shift?",
    [
        mem("m1", "The site needs one first-aider on shift.", lifecycle_state="deprecated",
            version=1),
        mem("m2", "The site needs two first-aiders on shift since the headcount rose.",
            version=2),
        mem("m3", "First-aid training is renewed every three years."),
    ],
    {"relevant": ["m2"], "critical": ["m2"], "irrelevant": ["m1", "m3"],
     "roles": {"m2": "necessary"}},
    "The deprecated figure is the lower one, so returning it understates a safety requirement rather than merely being stale.",
))

# --- conflicting ------------------------------------------------------------
CASES.append(case(
    "conflicting-03", "conflicting",
    "Is the loading ramp surface safe in frost?",
    [
        mem("m1", "The slip survey rated the loading ramp acceptable in frost.",
            entities=["loading-ramp"], source_root="survey-1"),
        mem("m2", "Two slips were reported on the loading ramp during frost last month.",
            entities=["loading-ramp"], source_root="incident-log"),
        mem("m3", "The loading ramp is 12 m long.", entities=["loading-ramp"]),
    ],
    {"relevant": ["m1", "m2"], "critical": ["m2"], "irrelevant": ["m3"],
     "roles": {"m1": "contradictory", "m2": "contradictory"}},
    "A survey and an incident log disagree about the same surface under the same condition. Both belong in the context; returning only the survey is the failure.",
    entities=["loading-ramp"],
))
CASES.append(case(
    "conflicting-04", "conflicting",
    "Can the gantry hoist lift the transformer?",
    [
        mem("m1", "The gantry hoist plate reads 2 tonnes.", entities=["gantry-hoist"],
            source_root="plate"),
        mem("m2", "The latest load test certifies the gantry hoist at 1.5 tonnes.",
            entities=["gantry-hoist"], source_root="load-test"),
        mem("m3", "The transformer weighs 1.8 tonnes.", entities=["transformer"]),
    ],
    {"relevant": ["m1", "m2", "m3"], "critical": ["m2", "m3"], "irrelevant": [],
     "roles": {"m1": "contradictory", "m2": "contradictory", "m3": "necessary"}},
    "The answer flips on which capacity is authoritative, and the weight is what makes the disagreement decisive. Returning the plate alone licenses an overload.",
    entities=["gantry-hoist", "transformer"],
))

# --- apparent conflict ------------------------------------------------------
CASES.append(case(
    "apparent_conflict-03", "apparent_conflict",
    "Can we run the extractor fan while welding in the paint booth?",
    [
        mem("m1", "The extractor fan may run during welding in the fabrication bay.",
            entities=["fabrication-bay"]),
        mem("m2", "The extractor fan must not run during welding in the paint booth: solvent vapour.",
            entities=["paint-booth"]),
        mem("m3", "The paint booth extractor is rated 4,000 m3/h.", entities=["paint-booth"]),
    ],
    {"relevant": ["m2"], "critical": ["m2"], "irrelevant": ["m1", "m3"],
     "roles": {"m2": "necessary"}},
    "m1 and m2 only appear to conflict: they state different locations. The task names the paint booth, which selects m2.",
    entities=["paint-booth"],
))
CASES.append(case(
    "apparent_conflict-04", "apparent_conflict",
    "Is the sealant approved for potable water pipework?",
    [
        mem("m1", "The sealant is approved for heating pipework.", entities=["sealant"]),
        mem("m2", "The sealant is not approved for potable water.", entities=["sealant"]),
        mem("m3", "The sealant cures in 30 minutes.", entities=["sealant"]),
    ],
    {"relevant": ["m2"], "critical": ["m2"], "irrelevant": ["m1", "m3"],
     "roles": {"m2": "necessary"}},
    "Both approvals are true of different applications. The task names one, and returning the heating approval would read as a yes.",
    entities=["sealant"],
))

# --- copied evidence --------------------------------------------------------
CASES.append(case(
    "copied_evidence-03", "copied_evidence",
    "How strong is the case that the conveyor bearing is failing?",
    [
        mem("m1", "Vibration survey: conveyor bearing shows a rising 1x peak.",
            entities=["conveyor"], source_root="vib-1"),
        mem("m2", "Per the vibration survey, the conveyor bearing's 1x peak is rising.",
            entities=["conveyor"], method="imported", parents=[["m1", 1]],
            source_root="vib-1"),
        mem("m3", "Shift note quoting the vibration survey: conveyor bearing deteriorating.",
            entities=["conveyor"], method="consolidated", parents=[["m1", 1]],
            source_root="vib-1"),
        mem("m4", "Oil analysis found bronze particles in the conveyor gearbox.",
            entities=["conveyor"], source_root="oil-1"),
    ],
    {"relevant": ["m1", "m4"], "critical": ["m4"], "irrelevant": [],
     "roles": {"m1": "corroborative", "m4": "necessary"}},
    "m2 and m3 restate m1 and add no independent support; a context of m1+m2+m3 reads as three findings and is one. m4 is the only second root.",
    entities=["conveyor"],
))
CASES.append(case(
    "copied_evidence-04", "copied_evidence",
    "Do we have independent evidence that the water heater is undersized?",
    [
        mem("m1", "Commissioning report: water heater output 18 kW against a 24 kW demand.",
            entities=["water-heater"], source_root="commissioning"),
        mem("m2", "Summary of the commissioning report: heater undersized.",
            entities=["water-heater"], method="consolidated", parents=[["m1", 1]],
            source_root="commissioning"),
        mem("m3", "Handover pack repeats the commissioning finding of an undersized heater.",
            entities=["water-heater"], method="imported", parents=[["m1", 1]],
            source_root="commissioning"),
        mem("m4", "Occupants report no hot water after 0800 on weekdays.",
            entities=["water-heater"], source_root="complaints"),
    ],
    {"relevant": ["m1", "m4"], "critical": ["m4"], "irrelevant": [],
     "roles": {"m1": "corroborative", "m4": "necessary"}},
    "The question asks specifically about independence, so returning three descendants of one report is the wrong answer however relevant each looks.",
    entities=["water-heater"],
))

# --- near duplicate ---------------------------------------------------------
CASES.append(case(
    "near_duplicate-03", "near_duplicate",
    "Anything I should know before using the scissor lift?",
    [
        mem("m1", "Scissor lift maximum working height is 7.8 m."),
        mem("m2", "Scissor lift max height: 7.8 m."),
        mem("m3", "The scissor lift reaches 7.8 m."),
        mem("m4", "Scissor lift working height limit is 7.8 metres."),
        mem("m5", "The scissor lift's left outrigger sensor is faulty and reads deployed when it is not."),
    ],
    {"relevant": ["m1", "m5"], "critical": ["m5"], "irrelevant": [],
     "roles": {"m1": "background", "m5": "necessary"}},
    "Four restatements of the height will fill a top-k budget and crowd out m5, which is the only memory that changes what the operator must check.",
    token_budget=120,
))
CASES.append(case(
    "near_duplicate-04", "near_duplicate",
    "Brief me on the site induction.",
    [
        mem("m1", "Site induction takes 45 minutes."),
        mem("m2", "The induction lasts 45 minutes."),
        mem("m3", "Induction duration: 45 min."),
        mem("m4", "Allow 45 minutes for site induction."),
        mem("m5", "Inductions cannot be run after 1500 because the fire alarm test blocks the room."),
    ],
    {"relevant": ["m1", "m5"], "critical": ["m5"], "irrelevant": [],
     "roles": {"m1": "background", "m5": "necessary"}},
    "The duplicated duration is true and unhelpful; m5 is the constraint that changes scheduling, and redundancy is what buries it.",
    token_budget=120,
))

# --- constrained ------------------------------------------------------------
CASES.append(case(
    "constrained-03", "constrained",
    "Which disposal route should we use for the solvent drums?",
    [
        mem("m1", "Route Gamma is cheapest for solvent drums.", entities=["gamma"]),
        mem("m2", "Route Gamma is not licensed for hazardous waste.", entities=["gamma"]),
        mem("m3", "Route Kappa is licensed for hazardous waste and takes solvent drums.",
            entities=["kappa"]),
        mem("m4", "Solvent drums are classified hazardous.", entities=["solvent-drums"]),
    ],
    {"relevant": ["m2", "m3", "m4"], "critical": ["m2", "m4"], "irrelevant": [],
     "roles": {"m2": "necessary", "m3": "necessary", "m4": "necessary"}},
    "The constraint rules Gamma out, and m4 is what makes the constraint apply. Returning the cheapest route alone would be a licensing breach.",
    constraints=["only use licensed hazardous waste routes"],
    entities=["solvent-drums"],
))
CASES.append(case(
    "constrained-04", "constrained",
    "Who can we send to do the confined-space entry tomorrow?",
    [
        mem("m1", "Priya is the most experienced at confined-space entry.", entities=["priya"]),
        mem("m2", "Priya's confined-space certification lapsed in March.", entities=["priya"]),
        mem("m3", "Tom holds a current confined-space certification.", entities=["tom"]),
    ],
    {"relevant": ["m2", "m3"], "critical": ["m2"], "irrelevant": [],
     "roles": {"m2": "necessary", "m3": "necessary"}},
    "Experience is not the constraint; certification is. m2 is what disqualifies the obvious choice and m3 is the admissible one.",
    constraints=["only send currently certified people"],
    entities=["confined-space"],
))

# --- negative evidence ------------------------------------------------------
CASES.append(case(
    "negative_evidence-03", "negative_evidence",
    "Is the leak likely to be the roof membrane?",
    [
        mem("m1", "A failed roof membrane produces staining exactly like this.",
            entities=["roof-membrane"]),
        mem("m2", "The roof membrane was replaced in full last autumn and pressure tested.",
            entities=["roof-membrane"]),
        mem("m3", "The staining appeared after the sprinkler main was charged.",
            entities=["sprinkler"]),
    ],
    {"relevant": ["m1", "m2", "m3"], "critical": ["m2"], "irrelevant": [],
     "roles": {"m1": "background", "m2": "contradictory", "m3": "necessary"}},
    "m1 makes the tempting answer attractive, m2 rules it out, and m3 points elsewhere. A retriever ranking only positive support confirms the wrong cause.",
    entities=["roof-membrane"],
))
CASES.append(case(
    "negative_evidence-04", "negative_evidence",
    "Could the outage have been the generator fuel supply?",
    [
        mem("m1", "Fuel starvation causes exactly this generator shutdown pattern.",
            entities=["generator"]),
        mem("m2", "The fuel tank was 80% full and the day tank float tested good after the outage.",
            entities=["generator"]),
        mem("m3", "The generator control panel logged an undervoltage trip.",
            entities=["generator"]),
    ],
    {"relevant": ["m1", "m2", "m3"], "critical": ["m2"], "irrelevant": [],
     "roles": {"m1": "background", "m2": "contradictory", "m3": "necessary"}},
    "The eliminating evidence m2 is the decisive memory, and it shares fewer words with the question than the hypothesis it rules out.",
    entities=["generator"],
))

# --- unanswerable -----------------------------------------------------------
CASES.append(case(
    "unanswerable-03", "unanswerable",
    "What is the torque setting for the east crane's slew ring bolts?",
    [
        mem("m1", "The west crane's slew ring bolts take 240 Nm.", entities=["west-crane"]),
        mem("m2", "The east crane was commissioned in 2021.", entities=["east-crane"]),
        mem("m3", "Slew ring bolts are checked annually."),
    ],
    {"relevant": [], "critical": [], "irrelevant": ["m1", "m2", "m3"],
     "expect_abstain": True, "roles": {}},
    "Nothing gives the asked figure for the asked crane. Returning the west crane's torque would read as an answer and could overtighten.",
    entities=["east-crane"],
))
CASES.append(case(
    "unanswerable-04", "unanswerable",
    "What did the insurer say about the flood exclusion?",
    [
        mem("m1", "The insurer confirmed the subsidence exclusion still applies.",
            entities=["insurer"]),
        mem("m2", "The policy renewal date is in April.", entities=["insurer"]),
        mem("m3", "Flood defences were inspected in May."),
    ],
    {"relevant": [], "critical": [], "irrelevant": ["m1", "m2", "m3"],
     "expect_abstain": True, "roles": {}},
    "The corpus has an insurer statement about a different exclusion and facts about flooding, but nothing about a flood exclusion. Combining them would fabricate a position.",
    entities=["insurer"],
))

# --- unauthorized -----------------------------------------------------------
CASES.append(case(
    "unauthorized-03", "unauthorized",
    "How do I get into the server cabinet to reseat the switch?",
    [
        mem("m1", "Server cabinet access: raise a change ticket, then collect the key from IT.",
            entities=["server-cabinet"]),
        mem("m2", "Server cabinet key safe combination is held by the IT duty engineer.",
            entities=["server-cabinet"], security_class="restricted",
            capabilities=["it:keysafe"], scope="private"),
        mem("m3", "The server cabinet is in the plant room.", entities=["server-cabinet"]),
    ],
    {"relevant": ["m1", "m2"], "critical": [], "irrelevant": ["m3"],
     "must_not_expose": ["m2"], "roles": {"m1": "necessary", "m2": "necessary"}},
    "m2 is directly relevant and the agent holds no it:keysafe capability. Returning it is a failure precisely because it answers the question.",
    entities=["server-cabinet"],
))
CASES.append(case(
    "unauthorized-04", "unauthorized",
    "What is in the disciplinary file for the night-shift incident?",
    [
        mem("m1", "Incident reports are summarised in the weekly safety brief.",
            entities=["incident"]),
        mem("m2", "The night-shift disciplinary file records the outcome and the individual named.",
            security_class="restricted", capabilities=["hr:files"], scope="private",
            entities=["incident"]),
        mem("m3", "Night shift runs 2200 to 0600."),
    ],
    {"relevant": ["m1", "m2"], "critical": [], "irrelevant": ["m3"],
     "must_not_expose": ["m2"], "roles": {"m1": "background", "m2": "necessary"}},
    "The restricted file is the only thing that answers the question, which is why relevance must not decide. The agent lacks hr:files.",
    entities=["incident"],
))

# --- retracted --------------------------------------------------------------
CASES.append(case(
    "retracted-03", "retracted",
    "Is the recommended coolant mix still 50/50?",
    [
        mem("m1", "Coolant mix is 50/50 water to glycol.", entities=["coolant"],
            lifecycle_state="quarantined", method="imported"),
        mem("m2", "The coolant specification is being revised by the manufacturer.",
            entities=["coolant"]),
        mem("m3", "Coolant is stored in the drum rack.", entities=["coolant"]),
    ],
    {"relevant": ["m1", "m2"], "critical": [], "irrelevant": ["m3"],
     "must_not_expose": ["m1"], "roles": {"m1": "necessary", "m2": "background"}},
    "m1 answers the question and was withdrawn at its origin. Exposing it is the failure PB2 measured away, and a relevance score would undo it.",
    entities=["coolant"],
))
CASES.append(case(
    "retracted-04", "retracted",
    "Confirm the inspection interval for the pressure vessel.",
    [
        mem("m1", "Pressure vessel inspection interval is 24 months.",
            entities=["pressure-vessel"], lifecycle_state="quarantined",
            method="imported"),
        mem("m2", "The pressure vessel interval is under review after the regulator's notice.",
            entities=["pressure-vessel"]),
        mem("m3", "The pressure vessel holds 400 litres.", entities=["pressure-vessel"]),
    ],
    {"relevant": ["m1", "m2"], "critical": [], "irrelevant": ["m3"],
     "must_not_expose": ["m1"], "roles": {"m1": "necessary", "m2": "background"}},
    "The withdrawn interval is the only direct answer, and confirming it would be a regulatory statement made on retracted knowledge.",
    entities=["pressure-vessel"],
))

# --- answer keys for R6 -----------------------------------------------------
#
# Declared here, in the generator, so a rebuild cannot lose them — and declared
# *before* R6 ran, as its pre-registration requires.
#
# Only for cases with an unambiguous short factual answer. A case whose correct
# answer is "both claims, unresolved" (`conflicting`) or "say you cannot tell"
# (`unanswerable`) gets no key: scoring those by substring would reward a model
# for emitting a token rather than for reasoning, and inventing keys to widen
# coverage is how a benchmark comes to measure the wrong thing. `unanswerable`
# is scored on abstention, which needs no key.
#
# Each key is a list of alternatives, because "3.5 bar" and "3.5bar" are the
# same answer and a single string would fail a model over whitespace.
KEYS = {
    "direct-01": ["3.5 bar", "3.5bar"],
    "direct-02": ["90 day", "90-day", "every 90"],
    "direct-03": ["iso 46", "iso-46"],
    "direct-04": ["appointed person"],
    "lexical_trap-01": ["valve 7", "valve seven", "partly closed", "restrict"],
    "lexical_trap-02": ["80 nm", "80nm"],
    "lexical_trap-03": ["condenser fan"],
    "lexical_trap-04": ["12 hour", "12-hour", "twelve hour"],
    "rare_critical-01": ["bypass"],
    "rare_critical-02": ["40%", "40 %", "gauge"],
    "rare_critical-03": ["latch", "support"],
    "rare_critical-04": ["vehicle", "offset"],
    "temporal_drift-01": ["2000", "20:00", "8pm", "8 pm"],
    "temporal_drift-02": ["1800", "18:00", "6pm", "6 pm"],
    "temporal_drift-03": ["5 km", "5km"],
    "temporal_drift-04": ["delta"],
    "superseded-01": ["10 tonne", "10t", "ten tonne"],
    "superseded-03": ["three high", "3 high"],
    "superseded-04": ["two", "2 first-aider"],
    "apparent_conflict-01": ["not", "no"],
    "apparent_conflict-03": ["not", "no"],
    "apparent_conflict-04": ["not", "no"],
    "constrained-01": ["beta"],
    "constrained-03": ["kappa"],
    "constrained-04": ["tom"],
    "negative_evidence-01": ["not", "no", "unlikely", "ruled out", "replaced"],
    "negative_evidence-03": ["not", "no", "unlikely", "sprinkler"],
    "negative_evidence-04": ["not", "no", "unlikely", "undervoltage"],
    "indirect-01": ["3.5 bar", "3.5bar"],
    "indirect-02": ["no", "not", "inland"],
    "indirect-03": ["110 nm", "110nm"],
    "indirect-04": ["no", "not", "guardrail", "no longer"],
    "near_duplicate-01": ["brake", "bedding"],
    "near_duplicate-03": ["outrigger", "sensor"],
    "near_duplicate-04": ["1500", "15:00", "3pm", "fire alarm"],
    "copied_evidence-01": ["measurement", "independent", "0.8"],
    "copied_evidence-03": ["oil", "bronze", "independent"],
    "copied_evidence-04": ["occupant", "hot water", "independent"],
}

for c in CASES:
    key = KEYS.get(c["case_id"])
    if key:
        c["labels"]["answer_contains"] = key

# --- split ------------------------------------------------------------------
# Deterministic and declared: the *second* case of each family goes to test
# where a family has two, and single-case families stay in dev. Frozen now, so
# no tuning result can move a case across the line later.
dev, test = [], []
seen = {}
for c in CASES:
    seen[c["family"]] = seen.get(c["family"], 0) + 1
    # Cases 2 and 4 of each family go to test; 1 and 3 to dev. The rule is
    # *extended* rather than rewritten: under the original rule only case 2
    # went to test, so every one of the first 20 cases keeps its original
    # side. A frozen split that moved cases would invalidate every measurement
    # already taken against it.
    (test if seen[c["family"]] % 2 == 0 else dev).append(c)

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
