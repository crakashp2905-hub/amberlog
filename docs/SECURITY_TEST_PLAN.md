# Security test plan

Every threat in [SAFETY_AND_SECURITY.md](SAFETY_AND_SECURITY.md) §4 maps to
tests here. All fixtures are synthetic and local. The "secrets" are vendor
documentation examples, no network service is contacted, and no real credential
is used. `tests/test_docs_evidence.py` checks that every test this file or the
threat model names actually exists, so the mapping cannot quietly go stale.

## How to run

| Scope | Command |
|---|---|
| Threat-mapped regression suite | `python -m unittest tests.test_security_regression -v` |
| Certificates and action gate | `python -m unittest tests.test_certificates -v` |
| Everything | `python -m unittest discover -s tests -t .` |
| Fault matrix (crash, partition, replay) | `python -m experiments.faultsim` |
| Same suites on Postgres | set `MF_TEST_POSTGRES_URL`, then see `.github/workflows/ci.yml` (`postgres` job) |
| Repository secret scan | `python tools/scan_secrets.py` |

## Mapping

| Threat | Fixture | What it shows |
|---|---|---|
| S1 poisoning | `test_security_regression.py::TestPoisoning` | A poisoned write is a candidate and is not retrievable. Quarantining it contests its conclusions and blocks an action already in flight. Independent support survives. |
| S2 injection | `test_security_regression.py::TestInjection`, `test_injection_patterns.py` | Quarantined on write, on revision, and when placed in metadata. Each pattern has a near-miss negative. |
| S3 tenant leakage | `test_security_regression.py::TestTenantIsolation`, `test_data_access_paths.py`, `test_service.py` | No read path crosses a tenant. A refusal reveals neither version nor lifecycle. Cross-tenant derivation is refused. Refusals are audited without content. |
| S4 unauthorized write | `test_security_regression.py::TestUnauthorizedWrite`, `test_auth.py`, `test_identity.py` | Forged agent, tenant, role or signature is refused. Unknown agents are refused. Agents cannot validate, quarantine or release. A revoked credential cannot write. |
| S5 replay / ordering | `test_security_regression.py::TestReplayAndOrdering`, `test_retraction_protocol.py`, faultsim | Five deliveries have one effect. An unauthorised sender changes nothing. A sequence below the cursor is superseded. |
| S6 log tampering | `test_integrity_chain.py`, `test_postgres.py::TestAppendOnly` | Edits, deletion, reordering and truncation are caught. A recomputed chain is caught only by an external checkpoint. |
| S7 retraction failure | `test_security_regression.py::TestFailedPeer`, `test_retraction_protocol.py`, `test_multiprocess_crash.py` | An offline peer is never reported enforced. Recovery happens by reconciliation. Delivery intent survives a crash. |
| S8 derived leakage | `test_security_regression.py::TestDerivedLeakage`, `test_certificates.py::TestDerivedEvidence` | A secret in a summary's text, `context` or `structured` field is quarantined and not inherited. A summary of withdrawn evidence is unusable. Ordinary metadata is not overblocked. |
| S9 exhaustion | `test_certificates.py::TestMalformed`, `test_agent_api.py::test_oversized_bodies_are_refused`, `test_chains.py` | Certificates over 64 evidence entries are refused. Bodies have a size limit. Search has budgets. |
| S11 key compromise | `test_cipher.py`, `test_key_migration.py`, `test_identity.py` | Authenticated suites with AAD binding. Keys move out of the database. Per-credential revocation. |
| S12 overblocking | `test_certificates.py::TestSelectiveReassessment`, `test_justification.py` | Selective reassessment keeps independently supported evidence where blanket invalidation refuses it. A copy is not independent support. |
| S13 authorization drift | `test_certificates.py::TestRevokedPermission` | A credential revoked after the certificate was issued stops the action. |
| S14 TOCTOU | `test_security_regression.py::TestStaleAndRetractedEvidence`, `test_certificates.py::TestToolPermission` | Revision and retraction after retrieval block the action, including across a restart. The residual race after `verify` returns is documented, not tested away. |
| Fail closed | `test_certificates.py::TestFailClosed`, `test_certificates.py::TestMalformed` | Unreadable state, unknown versions, unknown checks, unknown fields and 600 random mutations are all refused without raising. |
| Tool permission | `test_certificates.py::TestToolPermission` | A valid certificate does not grant a tool. Rules strengthen certificates and are never weakened by them. Human approval is bound to the certificate digest and cannot be self-approval. |

## Found by these tests

Two bypasses surfaced while writing the fixtures and are fixed in the same
change. Both regression tests failed before the fix (4 failures measured) and
pass after it:

1. **Metadata was not screened.** A secret or an injection in `context` or
   `structured` was stored active, in plaintext (only content is sealed), and
   copied into every memory `derive` drew from it.
2. **`revise` skipped the ingest screen.** A revision could add a secret or an
   injection to a memory that was already active and retrievable.

## Not covered (accepted gaps)

- Rate limiting and write-flood quotas. No control exists.
- Model compliance with retrieved injections. This system does not control it.
- A full-history rewrite without an external checkpoint. Documented.
- Hard tenant isolation. Tenancy is logical.
