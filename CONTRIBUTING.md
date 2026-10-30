# CONTRIBUTING.md

Read [AGENTS.md](AGENTS.md) first; its rules are binding.

The implementation uses `src/amberlog`. Use `python -m pip install -e .` for
interactive development. Source test packages add that source root explicitly;
clean-wheel acceptance clears source-path overrides and runs outside the checkout.

## Before you push

```bash
sh tools/install-hooks.sh      # once: refuses force-pushes and deletions of protected branches
python tools/check.py          # regenerate docs, lint, type-check, doc tests, adversarial gate
python tools/check.py --full   # and the full unit suite
```

Some documents are **generated**, and CI fails if they are stale:

| document | regenerate with |
|---|---|
| `STABILITY.md` tier lists | `python tools/gen_stability.py` |
| `docs/API.md`, `docs/CLI.md` | `python tools/gen_reference.py` |
| test counts in README.md and docs/VALIDATION.md | `python tools/count_tests.py --write` |

`tools/check.py` runs all three. Other checks that guard the docs:

- every relative link resolves (`tests/test_doc_links.py`);
- every doc in `docs/` is in `docs/README.md` (`tests/test_doc_index.py`);
- every Python block in the README, quickstart, concepts and cookbook runs
  (`tests/test_doc_examples.py`), and every offline example runs
  (`tests/test_examples_run.py`);
- every CLI option has help, and every action-gate and limit reason code is
  explained in `docs/TROUBLESHOOTING.md`;
- user-facing documents describe the product, not the research behind it:
  no links into `research/`, no experiment ids
  (`tests/test_user_docs_no_research.py`). Research belongs in `research/`
  and the maintainer documents.

A change to behaviour updates every affected document in the same commit,
including the CHANGELOG.

## Adding a feature
1. Name the milestone in [ROADMAP.md](ROADMAP.md) it belongs to. If its gate hasn't passed, the feature waits.
2. If it changes the memory schema or event types, update [SPEC.md](SPEC.md), bump `schema_version`, and add a migration.
3. Add unit tests. For estimators or policies, also add known-answer tests on RuleWorld.
4. A change to the store's behaviour goes in the service that owns it
   (`amberlog/_fabric/`, table in ARCHITECTURE.md §6), not in
   `fabric.py`. A new public `Amberlog` method is added to
   `tests/data/amberlog_api.json`, deliberately.
5. A new security guard (a tenant, visibility, signature, grant or limit
   check) gets a mutant in `tools/mutation_check.py` naming the tests that
   must notice it removed; CI fails on a survivor.
6. Declare the module's tier (`__stability__ = "stable" | "beta" | "experimental"`). New
   mechanisms start experimental and stay off the default path.
7. If it adds a refusal a user can see, give it a reason code and a row in
   `docs/TROUBLESHOOTING.md`. If it adds a CLI option, give it help text.

## Adding an experimental mechanism
1. Write a pre-registration in `research/prereg/<id>.md`: hypothesis, primary metric, threshold, baselines, seeds, expected cost.
2. Implement it behind the relevant protocol (estimator, exposure policy, conflict detector, firewall policy), not as a special case.
3. Run the baselines and ablations from [EVALUATION.md](EVALUATION.md).
4. Record the decision (proceed / kill / pivot) in `research/decisions/`.

## Graduating from research to product
A mechanism moves into the stable SDK only when it has:
- a reproducible result against its baselines
- a documented failure analysis
- a security review against [SECURITY.md](SECURITY.md)
- an API-stability review
