"""DepotWorld: a world where a true memory is false next door.

RuleWorld cannot host Phase A. Its lessons are true everywhere, so a store can
only ever be right or incomplete, never *misleadingly right*. The hazard this
project claims to govern is the other one: a memory that earned its place
honestly at one site and is wrong at the next, with nothing on its surface to
say so.

So the correct action here is a function of **both** the fault code and the
site. Each fault has a base action that holds at two of the three site types and
a different action that holds at the third. A lesson written at a base site is
true, useful, and wrong when retrieved at the exception site — and it is the
*most similar* text in the store to the query that arrives there, because it
names the same fault code. Similarity search cannot separate the two cases even
in principle. That is the point of the design, not a weakness of it.

On top of that, a fraction of learning episodes hand the agent a misleading
diagnosis, so the lesson it writes is wrong even for its own site. Those are the
memories a lifecycle is supposed to catch.

No model is called from this module. The world is pure, seeded, and testable on
its own, so that a bug here cannot hide inside a live run.

See research/prereg/phase-a-real-agent-benchmark.md §2.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Sequence

ACTIONS = (
    "reseat_contactor",
    "replace_rcd",
    "reflash_firmware",
    "clean_earth_bond",
    "swap_pilot_cable",
    "recalibrate_meter",
)

SITES = ("cold_store", "coastal", "urban")

FAULTS = ("E01", "E02", "E03", "E04", "E05", "E06")

# What the inspection found, phrased as an engineer would. Keyed by the action
# it implies, so a diagnosis and its action always agree unless the world
# deliberately poisons the pair.
DIAGNOSES = {
    "reseat_contactor": "the main contactor had worked loose in its housing",
    "replace_rcd": "the residual current device had failed closed",
    "reflash_firmware": "the controller firmware had a corrupted checksum",
    "clean_earth_bond": "the earth bond was damp and corroded",
    "swap_pilot_cable": "the pilot cable had a broken conductor",
    "recalibrate_meter": "the energy meter was reading 12% high",
}

SITE_BLURB = {
    "cold_store": "a refrigerated distribution depot, ambient -18C",
    "coastal": "a harbour-side depot with salt spray exposure",
    "urban": "a city-centre depot in a basement car park",
}


@dataclass(frozen=True)
class Truth:
    """The world's answer key: action per (fault, site), plus which site is the
    exception for each fault. Built once per seed and never consulted by an
    arm — only by the verifier and by the oracle."""

    base: dict[str, str]
    exception_site: dict[str, str]
    exception_action: dict[str, str]

    def action(self, fault: str, site: str) -> str:
        if self.exception_site[fault] == site:
            return self.exception_action[fault]
        return self.base[fault]

    def is_exception(self, fault: str, site: str) -> bool:
        return self.exception_site[fault] == site


def build_truth(rng: random.Random) -> Truth:
    """Each fault gets a base action, one exception site, and a different action
    there. The exception action is drawn from the remaining actions, so no fault
    has the same answer everywhere and none has the same answer as its base."""
    base: dict[str, str] = {}
    exception_site: dict[str, str] = {}
    exception_action: dict[str, str] = {}
    for index, fault in enumerate(FAULTS):
        # One distinct base action per fault, so a correct lesson identifies the
        # fault unambiguously and a failure cannot be explained by two faults
        # sharing an answer.
        base[fault] = ACTIONS[index % len(ACTIONS)]
        exception_site[fault] = rng.choice(SITES)
        exception_action[fault] = rng.choice([a for a in ACTIONS if a != base[fault]])
    return Truth(base=base, exception_site=exception_site, exception_action=exception_action)


@dataclass(frozen=True)
class LearningEpisode:
    fault: str
    site: str
    action: str
    """The action the agent is told the incident called for — which is the true
    one unless this episode is poisoned."""
    diagnosis: str
    poisoned: bool

    @property
    def truth_at_own_site(self) -> bool:
        return not self.poisoned


def learning_episodes(truth: Truth, rng: random.Random, poison_rate: float = 0.25) -> list[LearningEpisode]:
    """One episode per (fault, site) pair: 18 in all.

    An earlier version visited two sites of three, on the reasoning that full
    coverage would leave nothing to get wrong by transfer. That was wrong twice
    over. The transfer hazard does not come from gaps — the contaminating
    lesson from another site is still in the store and still the closest match
    — and the gaps put the *oracle* below the pre-registered sanity floor,
    because an exception site never visited has no correct lesson for perfect
    selection to find. A ceiling depressed by missing data measures the sampling
    scheme, not the method.
    """
    episodes: list[LearningEpisode] = []
    for fault in FAULTS:
        for site in SITES:
            poisoned = rng.random() < poison_rate
            correct = truth.action(fault, site)
            if poisoned:
                action = rng.choice([a for a in ACTIONS if a != correct])
            else:
                action = correct
            episodes.append(
                LearningEpisode(
                    fault=fault,
                    site=site,
                    action=action,
                    diagnosis=DIAGNOSES[action],
                    poisoned=poisoned,
                )
            )
    rng.shuffle(episodes)
    return episodes


@dataclass(frozen=True)
class EvalEpisode:
    fault: str
    site: str
    correct: str
    is_exception: bool


def eval_episodes(truth: Truth, rng: random.Random, count: int = 24) -> list[EvalEpisode]:
    """Half the episodes land on an exception site, by construction.

    Sampling (fault, site) uniformly would put a third of episodes on exceptions
    and leave the measurement at the mercy of the draw at 24 episodes. Fixing
    the share makes the hazard rate a stated parameter rather than noise — and
    it is stated in the pre-registration as such.
    """
    pairs: list[EvalEpisode] = []
    exceptions = [
        EvalEpisode(f, truth.exception_site[f], truth.action(f, truth.exception_site[f]), True)
        for f in FAULTS
    ]
    bases = [
        EvalEpisode(f, s, truth.action(f, s), False)
        for f in FAULTS
        for s in SITES
        if not truth.is_exception(f, s)
    ]
    half = count // 2
    for _ in range(half):
        pairs.append(rng.choice(exceptions))
    for _ in range(count - half):
        pairs.append(rng.choice(bases))
    rng.shuffle(pairs)
    return pairs


# --- prompts ----------------------------------------------------------------


def write_prompt(episode: LearningEpisode) -> str:
    """Ask for a lesson that names the fault, the site and the action.

    The live multi-agent run established why: let a model describe the fix in
    its own words and it writes "requires replacement of faulty conductor",
    which names none of the options the reader is later asked to choose between.
    Both arms then score zero and the experiment measures nothing. Naming the
    action connects the written memory to the answer space.
    """
    return (
        f"You attended a charger fault at {SITE_BLURB[episode.site]} "
        f"(site type: {episode.site}).\n"
        f"The charger reported fault code {episode.fault}.\n"
        f"Your inspection found: {episode.diagnosis}.\n"
        f"The response that resolved it was: {episode.action}\n\n"
        "Write the durable lesson for future incidents, in one sentence. "
        f"It must contain the fault code {episode.fault}, the site type "
        f"{episode.site}, and the response name copied exactly as "
        f"`{episode.action}` — underscores included, not reworded."
    )


def recall_query(episode: EvalEpisode) -> str:
    """What the agent looks the episode up by.

    Deliberately short. The first run retrieved against the whole question —
    six option names, a site blurb and two sentences of instruction — and the
    fault code was a few tokens in a hundred, so similarity ranked lessons
    about *other* faults above the one that mattered and every contamination
    figure came out as zero. The hazard under test only appears once retrieval
    gets as far as the right fault code, which a real system would ensure the
    same way.
    """
    return f"fault code {episode.fault} at a {episode.site} site"


def ask_prompt(episode: EvalEpisode) -> str:
    options = "\n".join(f"  - {a}" for a in ACTIONS)
    return (
        f"A charger at {SITE_BLURB[episode.site]} (site type: {episode.site}) "
        f"is reporting fault code {episode.fault}.\n\n"
        f"Possible responses:\n{options}\n\n"
        "Name the single correct response. Note that the correct response for a "
        "fault code can differ between site types, so a note about this fault at "
        "another site type may not apply here. Answer with one response name."
    )


# --- scoring ----------------------------------------------------------------

HEDGE = re.compile(
    r"\b(conflict|disagree|contradic|uncertain|unclear|ambiguous|verify|confirm|"
    r"inconsisten|cannot determine|not sure|insufficient)\w*",
    re.IGNORECASE,
)


# Each action, as the stems a sentence must contain in order. Stems match on
# word prefix, so "reseating" counts for "reseat" and "recalibrated" for
# "recalibrate". The alternations cover the noun a model actually writes: asked
# for `replace_rcd` it writes "replace the residual current device", and a
# parser that only accepts the token form discards a third of the corpus — then
# the measurement is of the parser, not of the memory layer.
ACTION_STEMS: dict[str, tuple[str, ...]] = {
    "reseat_contactor": ("reseat", "contactor"),
    "replace_rcd": ("replac|renew", "rcd|residual"),
    "reflash_firmware": ("reflash|flash|reimag", "firmware"),
    "clean_earth_bond": ("clean|cleans", "earth|ground"),
    "swap_pilot_cable": ("swap|replac|renew", "pilot"),
    "recalibrate_meter": ("recalibrat|calibrat", "meter"),
}
GAP = r"(?:\s+\w+){0,3}\s+"
ACTION_PATTERNS = {
    action: re.compile(
        r"\b" + GAP.join(r"(?:" + stem + r")\w*" for stem in stems),
        re.IGNORECASE,
    )
    for action, stems in ACTION_STEMS.items()
}


def parse_action(text: str) -> str | None:
    """The single action a reply commits to, tolerating prose.

    A model asked about `swap_pilot_cable` answers "swap the pilot cable".
    Scoring only the token form records a confidently wrong answer as no answer
    at all, which would bias every arm's error rate downward — and would bias it
    most for the arms whose memories are wrong, which is precisely the effect
    under measurement.

    Still requires exactly one distinct action: naming several is listing
    options, not committing to one.
    """
    body = (text or "").replace("_", " ")
    hits = [action for action, pattern in ACTION_PATTERNS.items() if pattern.search(body)]
    return hits[0] if len(hits) == 1 else None


def asserted_action(text: str, fault: str) -> str | None:
    """What a lesson claims the response is, used to label the corpus.

    Requires the lesson to name its own fault code: a sentence that names an
    action but no fault is not a usable lesson about this fault, and counting it
    as one would mislabel the corpus the whole measurement rests on.
    """
    if fault.lower() not in (text or "").lower():
        return None
    return parse_action(text)


def mentioned_site(text: str) -> str | None:
    lowered = (text or "").lower()
    found = [s for s in SITES if s.replace("_", " ") in lowered or s in lowered]
    return found[0] if len(found) == 1 else None


def render_plain(contents: Sequence[str]) -> str:
    """How an ungoverned vector store presents what it found: the text, and
    nothing else. No provenance, no lifecycle, no caveats — because it has
    none to give. The asymmetry against the fabric's rendering is real and is
    recorded as a confound in the result, not hidden here."""
    if not contents:
        return ""
    lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(contents))
    return f"Relevant notes from past incidents:\n{lines}"
