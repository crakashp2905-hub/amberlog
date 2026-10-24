# Networked deployment: latency, partition, outage, concurrent corrections

Produced by `python -m experiments.net_bench` at commit `259eb33`; raw numbers in
[net-bench.json](net-bench.json). Three `federate` servers, each with its own
database, connected only over HTTP through TCP proxies that add latency per
hop and can cut a link. A → B → C share chain, background managers deliver
retractions every second. Separate processes on one machine, not several
physical machines. Not pre-registered.

| latency per hop (ms) | correction reached C (s) | C during outage / converged after restart (s) | partition: B withdrawn · C while cut / converged after heal (s) | two concurrent corrections converged at C (s) | every chain verifies |
|---|---|---|---|---|---|
| 0 | 1.29 | active / 0.92 | True · active / 1.02 | 1.06 | True |
| 50 | 1.28 | active / 0.92 | True · active / 1.03 | 1.61 | True |
| 200 | 1.03 | active / 1.68 | True · active / 1.53 | 2.08 | True |

## Reading (written after the run)

**Everything converges, at every latency, and every hash chain verifies.**
- **Partition:** a correction at A reached B, and C, cut off from B with
  both servers up, kept the withdrawn memory active. That is the inherent
  limit, and the reason for strict freshness leases (`freshness.py`). C
  converged within 1.0–1.5 s of the link healing, with no operator action.
- **Outage:** the same convergence after C restarts.
- **Concurrent corrections:** two corrections issued at the same moment at
  different stores (X at A, Y at B) both reached C within 1.1–2.1 s.

**One behaviour to know, which is by design.** A correction issued at B, a
recipient, withdraws B's copy and everything downstream of it, but not the
origin's memory at A (`concurrent_origin_y_still_active` is true).
Retractions travel along the direction things were shared. A recipient that
believes the origin is wrong reports it to the origin's owner; it cannot
withdraw another store's memory.

**Not covered:** several physical machines, packet loss short of a full cut,
and asymmetric partitions.
