# Pre-registration — K1: a topic tree as a way in, beside search

**Registered 2026-10-27**, before `experiments/k1_navigation.py` or the topic
tree (`navigation.py`) existed.

## 1. Question

Sarvam's knowledge fabric reports large gains from letting agents *walk* a
compiled structure instead of retrieving passages. Amberlog already
groups memories into named topics for its map. Does entering through a topic
find the evidence lexical search misses?

## 2. Benchmark

LongMemEval `s`, the 60 stratified instances R3 used (`longmemeval_bench.load(limit=60)`),
through the product path, default settings. Metric: **turn recall@10**. Baseline
`B` = `lexical`, re-measured in the same run (R3 measured 0.768). Oracle 1.0.

## 3. Arms

| arm | |
|---|---|
| `lexical` | `retrieve`, k = 10 (baseline) |
| `nav` | a deterministic navigator: score each topic of the store's topic tree by the query words it shares (IDF-weighted), open the best two topics, rank their memories lexically, return 10 (filling from `lexical` if short) |
| `nav+lexical` | `nav` and `lexical` fused by reciprocal rank, 10 returned |
| `oracle` | the gold turns |

**8c:** no registered arm can trivially max turn recall@10; `oracle` is the only arm with labels.

## 4. Thresholds

- **K1a:** `nav+lexical` turn recall ≥ `B + 0.25 × (1 − B)` (about 0.826 if B = 0.768), positive
  gain over `lexical` in all five bootstrap resamples of the 60 instances.
- **K1b:** its median latency ≤ 250 ms (the R3 cost bound).

Pass: the navigator may be offered as a retrieval method. **The browse tools ship either way**: they
are an interface for an agent that wants to look around, not a claim that it finds more. Fail: the
result says so and no documentation claims navigation finds more.

## 5. Secondary, descriptive only (no claim)

12 of the 60 instances, each answered by a model agent (`claude-cli:haiku`) over the MCP server,
once with `recall` only and once with `recall` plus the browse tools. Reported: share of instances
where the memories the agent cited include a gold turn, and tool calls used. Twelve instances
support no claim and none will be made from them.
