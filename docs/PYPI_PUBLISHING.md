# Amberlog publishing

**NO-GO for publication.** Nothing has been uploaded, no release tag has been
created. The owner approved the GitHub rename to `crakashp2905-hub/amberlog`;
that rename and the About update are complete. Index accounts remain unchanged.

## Name investigation — 29 October 2026

The [PyPI JSON endpoint](https://pypi.org/pypi/amberlog/json) and
[TestPyPI JSON endpoint](https://test.pypi.org/pypi/amberlog/json) each returned
HTTP 404. This is absence of a visible project, not a reservation, permission to
register, or trademark clearance. An existing software company identifies its
brand as Amberlog on its [own website](https://amberlog.cc/). Domain and product
usage therefore need owner review. No alternative name is silently substituted.
GitHub destination links now match the renamed repository. No ownership of a
domain, organization or mark is claimed.

A second official-index check on the same date also returned HTTP 404 from
`https://pypi.org/simple/amberlog/`; pip's explicit official-index lookup,
including prereleases and ignoring Python-version filters, reported no matching
distribution. The owner subsequently clarified that no conflicting package page
was known and chose to retain the candidate name. These observations still do
not validate registration rights. Publication remains on hold.

## Local preparation

```
python -m pip install build twine
python -m build
python -m twine check --strict dist/*
python tools/fresh_machine.py dist/amberlog-0.14.0-py3-none-any.whl
```

Build wheel and sdist once from the approved clean commit. Inspect archive
members: only the canonical package, assets, typing marker and required legal/
packaging files should ship. Tests, datasets, databases, caches and credentials
must not ship. Install each independently outside the checkout. Save hashes,
test output and exact source SHA. The alpha status and proprietary license are
unchanged; a renamed distribution is not a stability qualification.

## Owner-side setup

Resolve naming rights and package-index acceptance first. Configure distinct
`testpypi` and `pypi` GitHub environments with required human reviewers and
deployment restrictions to approved version tags. Verify those protections
exist; a workflow declaration does not create review rules.

The GitHub `testpypi` and `pypi` environments are now configured and were read
back on 30 October 2026. Both require review by `crakashp2905-hub` and accept only
`v*` tags. Owner self-review is allowed; this is a human release-approval gate,
not an independent security assessment. Both name-clearance and release-gate
variables are explicitly `false`. Index-side trusted publishers have not been
verified: the browser integration could not initialize to inspect those accounts.
No upload, tag or approved-SHA flag has been created. Do not enable approval
variables or create a tag during preparation: the separate release workflow also
reacts to tags.

On each index, configure a trusted publisher (or pending publisher) with:

- Project: `amberlog`, only if accepted by the index.
- Owner: `crakashp2905-hub`.
- Repository: `amberlog`.
- Workflow: `publish-pypi.yml`.
- Environment: `testpypi` or `pypi`, matching the corresponding index.

Follow [official trusted-publishing guidance](https://docs.pypi.org/trusted-publishers/using-a-publisher/).
No API token is stored here. The GitHub workflow cannot configure index accounts
or guarantee acceptance of a pending project.

## Approval and upload

The workflow is manual-only, on an approved version tag. The owner must set
`AMBERLOG_NAME_CLEARED=true`, `AMBERLOG_RELEASE_GATES_PASSED=true` and
`AMBERLOG_APPROVED_SHA` to the exact approved commit. Leave these unset while
gates remain open. Qualification requires successful CI on that exact SHA,
matching versions, full tests, strict metadata checks and clean installations.
Only the publication job receives OIDC permission. It downloads the artifacts
built once by the qualification job and refuses duplicate uploads.

TestPyPI comes first. After a verified upload, install that exact version into
a clean environment with no source checkout on the import path:

```
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps amberlog==0.14.0
python -c "import amberlog; print(amberlog.__file__)"
amberlog --help
```

The core has zero dependencies, so no extra index is needed for this smoke test.
Do not claim this command succeeded until the uploaded artifact is tested.
Production upload requires a separate human approval and protected environment.
Do not dispatch production while any required review/pilot/release gate is open.
