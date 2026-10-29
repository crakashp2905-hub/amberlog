# Amberlog 0.12.0 — release notes (in qualification)

**Not yet tagged.** 0.12.0 is released through the same gate as 0.11.0: CI
green on the exact commit, acceptance on a fresh machine, the release
evaluation, then the tag ([RELEASE_EVALUATION.md](RELEASE_EVALUATION.md)).
Every change is in [CHANGELOG.md](../CHANGELOG.md); this page is what to know.

## Upgrading

Schema 0.12.0 adds six event types and no projection change. A 0.11.0 store
opens and replays unchanged, and nothing needs migrating
([MIGRATION.md](MIGRATION.md)).

**Defaults that change behaviour.** Each was an owner's decision, or a fix
for a measured failure:

| change | effect | to restore 0.11.0 |
|---|---|---|
| The **directive screen** runs at ingest and share | Text that addresses its reader or voids other records is quarantined for review | `Firewall(directive_screen=False)` |
| **Contradictions are flagged** in context and recall | Disputed memories carry a `disputed` warning | not configurable; ignore the warning |
| **Hostile sources are withheld** from retrieval | Memories by an author an ingest screen caught injecting, here or at a peer, are not shown | `Amberlog(withhold_hostile_sources=False)` |
| **Origin-bound authority at the action gate** | Evidence from a tool output, web page, import or instruction, or descending from a withdrawn memory, is refused unless elevated | `ToolRule(min_authority="untrusted")` |
| **Claim checks** hold suspicious writes and refuse them as evidence | A write that restates a corrected value, is far out of range or contradicts an established fact is a candidate, not active; the gate answers `evidence_suspicious` | `Amberlog(hold_suspicious=False)`, `ToolRule(refuse_suspicious=False)` |
| **Imports stop at 16 hops** | An offer that would place a copy beyond where a retraction can reach is refused | none: a copy must not outrun its retraction |
| **The operator role has no `execute`** | An operator session cannot run protected tools | grant `perm:execute` explicitly |
| **Retention never retires a premise** of an active memory | Sources outlive the summaries and conclusions built on them | none |
| **Servers meter writes** | 256 KiB content, 600 writes per agent and 300 imports per peer per minute; HTTP 429 or 413 | library default has no quotas |
| **Servers run the background manager** | Retraction delivery, notices, retention (deprecation only), audit, conflicts, re-compaction, checkpoints | `--no-maintain`; deletions need `--retention-delete` |

## New

- **Federation across machines**: `amberlog federate` and
  `amberlog offer`, signed network offers that land as candidates,
  and `--share-policy reviewed`.
- **Fixed**: forwarded retractions over HTTP were refused at the second
  hop; a federation server could apply a retraction against a stale view.
  Upgrade every store in a federation.
- **Claim checks** (`validation.py`): every claim checked against the
  store's own knowledge; `amberlog suspicious` lists what is held.
- **Federation key rotation with an overlap window** (`previous_keys` in the
  peers file), drilled end to end.
- **Origin-bound authority** (`authority.py`): trust and kind bound at first
  write, inherited through summaries, copies and federation; elevation by a
  different approver, per version.
- **Exact-action grants**: short-lived, bound to tool, agent, tenant, target,
  parameters and evidence versions, consumed once.
- **The influence graph** (`influence.py`): typed edges; potentially
  contaminated, retrieved and confirmed use kept apart; possible paraphrases.
- **Seven permissions**: read, write, delete, correct, export, administer,
  execute.
- **Physical tenant isolation** (`tenancy.TenantRouter`).
- **Governed session compaction** (`compaction.py`, experimental).
- **MemoryObjectiveV2** (`objective_v2.py`, experimental): hard rules apart
  from preferences, safety evidence never filtered by an unreviewed rule.
- **The background manager** (`manager.py`) and the signed
  **hostile-source notice** between stores.
- **Operations**: `backup --with-keys --include`, manifest-checked
  `restore`, JSON logs, store-level limits, recovery states.
- **Docs**: quickstart, concepts, cookbook, FAQ, generated API and CLI
  references, integrations, scale, runbooks; every code block and example
  run by a test.
- **Release tooling**: the adversarial gate, the evidence bundle, the
  fresh-machine check, scheduled model-in-the-loop attacks.

## Performance and reach

| | |
|---|---|
| Capacity, one store | 130 memory operations a second sustained, p99 91 ms |
| Federation | a correction reaches every copy across chains of up to 16 hops, and stars and meshes of 100 stores |

## Known limitations

[LIMITATIONS.md](LIMITATIONS.md). No independent review has happened. The
package is not on PyPI, pending a name.
