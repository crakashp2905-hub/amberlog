# Pre-registration — Phase A: does governed memory beat ungoverned memory for a real agent?

- **Written:** 2026-10-08, **before** the world, the arms or the harness were built.
- **Origin:** an external review of this project, which judged the implementation mature and the evidence thin on the one question a buyer actually asks. Its words: a benchmark against *real* agents, not RuleWorld.
- **Why this one matters:** every result so far is either simulation (H1–H4) or a single-mechanism live check (contested labelling, retrieval accuracy). Nothing has yet put the whole product on a task and compared it to the thing a competent engineer would build instead — a vector store.

Thresholds in §6 are fixed now and are not revised after seeing results.

---

## 1. Hypothesis

**PA.** For an LLM agent working a sequence of tasks where some remembered lessons are wrong for the situation at hand, memory governed by this project's machinery — provenance, lifecycle, contested marking, retraction, and value-based selection — produces higher task success and materially less memory-induced harm than an ungoverned vector store over the same lessons, at a cost the accuracy is worth.

The null that has to be taken seriously: **a vector store is enough.** H2 already killed a comparable claim about retention once, after the oracle showed a smoothed success rate captured 93% of the available gain. The same outcome here is a real possibility and would be reported as such.

The second null, weaker but worth measuring: **memory is net harmful.** A store full of lessons that are right somewhere and wrong here can leave an agent worse off than one with no memory at all. The `no_memory` arm exists to detect that, not as a courtesy.

## 2. The world

RuleWorld cannot be used. It has no notion of a lesson being correct in one context and wrong in another, and the live validation already measured its central parameter as wrong (compliance 1.00, not 0.80).

**DepotWorld.** An agent maintains EV chargers across a fleet of depots.

- **6 fault codes** × **3 site types** (`cold_store`, `coastal`, `urban`).
- **6 possible actions**, the same list throughout.
- The correct action is a function of **both** the fault and the site: each fault has a base action that is right at two of the three sites, and a different action that is right at the third. So a lesson learned at one site is *right there and wrong elsewhere*, with no surface feature distinguishing the two cases. This is the whole point of the world: relevance and value come apart, and similarity search cannot tell them apart because the contaminating lesson is the most similar text in the store.
- **Poisoned lessons.** In 25% of learning episodes the diagnosis handed to the agent is misleading, so the lesson it writes asserts the wrong action *for its own site too*. These are the memories governance is supposed to catch, and the ones a vector store will happily retrieve forever.

**Learning phase** (once per seed, shared by every arm). The agent is run on 18 episodes — each fault at each of the three sites and writes one lesson per episode in its own words. Sharing the corpus across arms is deliberate: the arms must differ only in *what is kept, shown and trusted*, which is what the product claims to do. What the model writes is held constant so it cannot become the explanation.

**Evaluation phase.** 24 episodes per seed. Each episode gives a fault code and a site, the arm selects memories, the agent answers, and the environment verifies. The corpus is released progressively over the evaluation phase so the store fills as the run proceeds — that is what makes long-horizon degradation measurable rather than asserted.

## 3. Arms

| id | Memory | Governance | Selection |
|---|---|---|---|
| `no_memory` | none | — | — |
| `local_rag` | only lessons this agent wrote at **this** site | none | top-3 cosine |
| `shared_memory` | every site's lessons, pooled | none | top-3 cosine |
| `shared_memory_framed` | every site's lessons, pooled | none — but rendered in the fabric's framing (added by amendment; see below) | top-3 cosine |
| `shared_memory_decay` | every site's lessons, pooled | delete a lesson that was in context when an episode failed | top-3 cosine |
| `fabric` | every site's lessons | validation gate, contested marking on disagreement, quarantine on contradiction | top-3 relevance |
| `fabric_causal` | every site's lessons | full | value estimate (amortized) over relevance |
| `oracle` | the released corpus with everything wrong-for-here removed | — | perfect filtering, top-3 (corrected by amendment; see below) |

**`shared_memory_decay` is the arm that matters most**, and it is here because of H2. The obvious comparison is governance against a *naive* vector store, and governance would probably win it. The honest comparison is against the cheapest thing that also reacts to failure — delete what was present when you failed. If governance cannot beat one line of code, the machinery is not earning its place, and H2 is precedent that this is not a hypothetical worry.

**`oracle` is not a competitor.** It fixes the ceiling, and every threshold below is a share of the headroom it reveals (AGENTS.md principle 8a).

## 4. Metrics

**Primary**
- `success` — chosen action equals the verified correct action.
- `memory_induced_improvement` — `success(arm) − success(no_memory)`, paired by (seed, episode).

**Harm**
- `harmful_memory_rate` — episodes where the answer was wrong **and** a memory in context asserted that exact wrong action. Attributable harm, not merely co-occurring failure.
- `contamination` — share of retrieved memories asserting an action that is wrong for this episode's (fault, site). Measures what selection let through, independently of what the model did with it.

**Cost**
- `tokens` — prompt + completion per episode, from Ollama's own counts.
- `latency` — ms per episode, split into memory operations and generation.

**Long horizon**
- `degradation` — success over the final third of the evaluation phase minus the first third, per arm. A store that fills with contaminating material should get worse; the claim is that a governed one does not.

## 5. Sanity condition, checked before the registered run

The world must be able to measure anything at all. Before the registered run, a pilot at one seed must show:

1. `oracle` success **≥ 0.80** — a correct, correctly-selected memory does let the model answer. (The live validation found 6.7% → 100% with the right memory, so this should hold; if it does not, the task is beyond the model and the world is wrong.)
2. `no_memory` success **≤ oracle − 0.20** — there is room for memory to help.
3. `shared_memory` contamination **> 0** — ungoverned pooling actually retrieves wrong-for-here lessons. If it does not, the world contains no hazard and the benchmark is vacuous.

Failing any of these means the **world** is changed and the change recorded as a dated amendment here, before any registered run. Thresholds in §6 are not changed either way.

> ### Amendment, 2026-10-08 — during harness construction, before any registered run
>
> Four changes to the **world and the arms**. No threshold in §6 was touched, and
> none of these was made after seeing an arm comparison.
>
> 1. **18 learning episodes, as registered — after a failed attempt to reduce
>    them to 12.** The harness first visited two of the three sites per fault,
>    on the reasoning that full coverage would leave nothing to get wrong by
>    transfer. Both halves of that were wrong. The transfer hazard does not come
>    from gaps: the contaminating lesson written at another site is still in the
>    store and is still the closest match to the query. And the gaps pushed the
>    **oracle to 50%** in a smoke run, below the §5 sanity floor of 0.80 — an
>    exception site never visited has no correct lesson for perfect selection to
>    find, so the ceiling was measuring the sampling scheme rather than what
>    selection could achieve. Reverted to one episode per (fault, site) pair.
> 1b. **The action parser accepts paraphrase.** Asked to write
>    `replace_rcd`, the model writes "replace the residual current device";
>    the first parser accepted only the token form and dropped a third of the
>    corpus. That is a measurement of the parser. It now matches word stems with
>    up to three filler words between them, is tested against sentences taken
>    from real runs (`tests/test_depotworld.py`), and still refuses a reply that
>    names more than one action, because listing options is not committing to
>    one.
> 2. **Half the evaluation episodes land on an exception site, by construction.**
>    Sampling (fault, site) uniformly puts a third there and leaves the
>    measurement at the mercy of the draw at 24 episodes. The hazard rate is
>    now a stated parameter, which §8.3 already said it was.
> 3. **Retrieval uses a short query** — "fault code E04 at a coastal site" —
>    rather than the full question. The first smoke run retrieved against the
>    whole question, in which the fault code is a few tokens among a hundred of
>    option names and instructions, and similarity ranked lessons about *other
>    faults* above the one that mattered. Contamination came out as 0% for every
>    arm: the hazard under test was not reaching the store at all. A real system
>    would scope the query the same way, and leaving it unscoped would have
>    measured embedding boilerplate rather than governance.
> 4. **The firewall is inert in this benchmark and is removed from the §3 table.**
>    Scope promotion needs a boundary to cross, and Phase A is one agent over one
>    store. Implementing it here would have meant a lesson staying private to its
>    site until it earned contrastive evidence — which the deterministic `fabric`
>    arm can never generate, silently turning that arm into `local_rag` under
>    another name. That mechanism belongs to Phase B, where the boundary is real.
>    What remains in the `fabric` arm is the validation gate, contested marking
>    on disagreement, and quarantine on contradiction.

> ### Amendment, 2026-10-08 (second) — after the §5 pilot, before the registered run
>
> **Disclosure first.** §5 sanctions a pilot for checking that the world can
> measure anything, and this amendment comes out of that pilot, so it is written
> with the numbers it was prompted by, not without them. The one-seed, 12-episode
> pilot showed: `no_memory` 25%, `shared_memory` 75%, `shared_memory_decay` 83%,
> `local_rag` 92%, `fabric` 100%. Those are 12 episodes at one seed and are not a
> result; they are the reason for the two changes below. **No threshold in §6 is
> changed.**
>
> **1. A new baseline arm: `shared_memory_framed`.** This is a confound the
> original §3 missed, and the pilot made it visible. The fabric arms render
> retrieved memories through `adapters.context.build_context`, which delimits
> them, states that they are evidence rather than instructions, and says what is
> known about each one's value. The vector arms render plain text, because that
> is all a vector store has. So `fabric` beating `local_rag` could be the
> governance or it could be the wrapper, and as registered the two were not
> separable — the benchmark would have credited the machinery for a prompt.
>
> `shared_memory_framed` pools every site's lessons with no governance at all
> and renders them in the fabric's framing, with every block labelled
> `unevaluated` — which is exactly what the fabric's own `describe_evidence`
> returns for a memory with no contrastive evidence, so nothing is invented to
> flatter or weaken the baseline. It joins `best_ungoverned` in §6. **If it
> matches the fabric arms, the effect is the framing and the governance earned
> nothing**, and that is the finding.
>
> **2. `local_rag` is a stronger baseline than intended, and is left as
> registered.** It filters to lessons written at the episode's own site, which in
> this world is a *perfect* context partition: the lesson from this site is the
> correct one unless it was poisoned, and nothing contaminating is visible at all.
> It is therefore close to an oracle by construction, and it is the arm most
> likely to make PA fail.
>
> Leaving it is the right call twice over. It is what §6 asked for — the hardest
> available baseline — and metadata-filtered retrieval is what a competent team
> actually deploys, so beating it is the real bar. But it bounds what a null
> result would mean, and that bound is stated now rather than discovered in the
> write-up: **a loss to `local_rag` would show that an exact context partition
> beats governance, not that governance is worthless, because the partition is
> only available when the hazard is perfectly predictable from a field already in
> the data.** If PA is killed this way, the follow-up is a world where the
> context label is noisy or absent, registered separately as Phase A′ — not a
> re-run of this one with the baseline weakened.

> ### Amendment, 2026-10-08 (third) — mid-run, after the ceiling arm was beaten
>
> **The oracle was not a ceiling, and the first registered run is void on the two
> criteria that depend on it.**
>
> At seed 2 of the registered run, `shared_memory` scored 67% against the
> oracle's 62%. An ungoverned baseline beating the oracle is not a surprising
> result; it is a proof that the arm was mis-specified.
>
> The cause is an asymmetry in §3 that neither the pilot nor the §5 sanity
> conditions could reveal. Every other arm shows up to **three** memories. The
> oracle showed **one** — the single correct lesson. Three memories of which one
> is right beats one right memory alone, because the model commits more readily
> with more context. So the ceiling was depressed by the arm's retrieval budget
> rather than by the limits of selection, and §6 expresses two of its three
> criteria as shares of the headroom that ceiling reveals.
>
> **This is the H3 mistake in a new form.** H3 registered a margin of +0.030 when
> perfect knowledge could deliver +0.027, so nothing could pass. Principle 8a was
> written because of it, this registration quotes that principle, and the
> registration then violated it anyway — not by setting the bar too high, but by
> measuring the ceiling with an arm that could not reach it. The pilot showed the
> oracle at 100% over 12 episodes, which made it look unimpeachable; the flaw only
> appears once the task is hard enough that one memory is not enough.
>
> **The correction, which changes no threshold.** The oracle now gets the same
> retrieval budget as the arms it bounds: top-3 by similarity over the released
> corpus, with every lesson that is *wrong for this episode* removed. Perfect
> filtering at equal k. It remains bounded by the corpus rather than omniscient,
> so it still measures what selection could actually achieve.
>
> **What happens to the first run.** It is reported, not discarded — the
> comparisons among the seven non-oracle arms are unaffected, as are harm,
> contamination, degradation and cost. But §6 criteria (1) and (2) are
> **unevaluable** on it, and are reported as unevaluable rather than as a pass or
> a fail, because a headroom share against a known-wrong ceiling is worse than no
> number at all. Criterion (3) does not involve the oracle and stands. The
> registered verdict comes from the re-run with the corrected ceiling.

## 6. Ceiling and thresholds

Let `best_ungoverned = max(local_rag, shared_memory, shared_memory_framed, shared_memory_decay)` on the metric in question, chosen *after* the run — deliberately the hardest baseline available, so the comparison cannot be won by picking a weak one.

Headroom on success is `oracle − best_ungoverned`.

**PA supported** if all three hold:
1. `fabric_causal` captures **≥ 50%** of the success headroom, with the bootstrap interval on the paired difference against `best_ungoverned` clear of zero;
2. `fabric_causal` cuts `harmful_memory_rate` by **≥ 50%** of the headroom between `best_ungoverned` and `oracle` (the oracle's rate is the floor and is expected to be 0);
3. `memory_induced_improvement` for `fabric_causal` is **> 0** with its interval clear of zero — governed memory beats having no memory, which is not automatic in a world designed to contain harmful memories.

**PA killed** if `fabric_causal` does not beat `best_ungoverned` on success at all, or if (3) fails.

**PA partially supported** — reported as such, not rounded up — if the harm criterion (2) passes and the success criterion (1) does not. That is the shape the live multi-agent result already took: converting confident error into flagged uncertainty is worth something and is not the same as being right, and this benchmark is likely to find the same distinction again.

**Cost is a gate on the claim's wording, not on the claim.** Registered now so it cannot be quietly dropped: if `fabric_causal` passes (1)–(3) with token cost ≤ **1.5×** and added memory-path latency ≤ **50 ms/episode** against `best_ungoverned`, the result is reported as supported. Over either, it is reported as *supported at a stated cost*, with the numbers in the headline.

## 7. Design

- **Model:** `qwen2.5:3b` for the agent, chosen for speed. `nomic-embed-text` for embeddings.
- **Seeds:** 5 (0–4). **Evaluation episodes:** 24 per seed per arm. 8 arms → 960 verified decisions.
- **Statistics:** paired by (seed, episode) across arms, since every arm sees the identical episode sequence and the identical lesson corpus. Bootstrap CIs (10,000 resamples) on paired differences, as in H1–H4.
- **Verification:** the environment scores the answer. No self-reported outcomes (AGENTS.md).
- **Parsing:** the same prose-tolerant action parser as the live multi-agent run — "swap the pilot cable" counts as `swap_pilot_cable`. Scoring only the token form would record a confidently wrong answer as no answer, which biases the result in the fabric's favour.

## 8. Stated limitations (written now, before any result)

1. **One model, and a small one.** 3B parameters. A larger model may be less swayed by a wrong memory, which would shrink every effect here. The live validation found the opposite direction — a wrong memory misled *every* model tested, including 7B — but that is three models, not a scaling study.
2. **The corpus is held constant across arms.** This isolates selection and governance, and it means the benchmark says nothing about whether the fabric helps an agent *write better memories*. MemBuilder (PRIOR_ART.md) is the work that attacks that question, and this design cannot speak to it.
3. **The hazard is synthetic and its rate is a parameter.** 25% poisoning and a one-site-in-three exception are chosen to make the effect measurable, not measured from a real deployment. The honest reading of any effect size here is "under this hazard rate", and the hazard rate in a real fleet is unknown.
4. **Single agent, multiple sites.** Federation between genuinely separate agents is Phase B, not this.
5. **No adversary.** Poisoned lessons come from misleading diagnoses, not from an attacker choosing what to plant.
6. **`shared_memory_decay` is a baseline I invented.** It is not a published method, and it is probably stronger than what most teams actually deploy. That is the point, and it also means a loss against it is not evidence that published alternatives are better.

## 9. What gets reported

The full arm × metric table with intervals; the headroom share for each criterion; all three supported-conditions individually; the cost gate; the degradation figures; and the verdict against §6 — including "killed" or "partially supported" if that is what the numbers say.
