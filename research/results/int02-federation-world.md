# INT-02 — Scheduled partition and correction world

Command: `python -m benchmarks.federation_world`.
Source commit: `a514df95ef24f46fd3e27b6669ff61527f838362`.
Raw results: [int02-federation-world.json](int02-federation-world.json).
Manifest: [bench_runs/int02-federation-world.json](bench_runs/int02-federation-world.json).

Five seeds, each with five stores in a chain and a star, exercised production
offer, review/elevation, certificate authorization, retraction, derivation and
outbox dispatch. All ten scenarios met the functional invariants: five actions
were authorized before correction; all five copies were quarantined after
delivery resumed; all five dependent conclusions were contested; all five
independent notes survived; no old certificate authorized an action afterward.

During withheld delivery, four remote copies remained active in every scenario.
This explicitly demonstrates stale offline state rather than pretending the
system can see through partitions. The study does not test expiry of freshness
leases or execute external tool effects; those have separate existing tests.

The scheduler needed four passes including a final idle pass for each chain,
and two for each star. These are scheduler steps, not time-to-convergence SLOs.
All stores ran in one process with in-memory databases. No model calls, network
performance, public-dataset evaluation, calibrated agent reasoning or
superiority claim is included. Decision: DESCRIPTIVE, not research promotion.
