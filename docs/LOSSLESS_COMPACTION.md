# Optional phrase-dictionary compaction (experimental)

```python
from memory_fabric.compaction import compact_session
from memory_fabric.lossless_compaction import dictionary_summary

report = compact_session(fabric, episode_id, "writer", summarise=dictionary_summary)
```

When dictionary encoding is selected, this opt-in summarizer factors repeated
phrases and preserves each source record exactly. It verifies decoding before returning an encoding,
has input/output/expansion limits, and falls back to the existing extractive
summarizer when no content-byte savings are available or disputes need explicit
display. That existing extractive fallback can omit chatter; raw sources remain
available for authorized drill-down. Literal marker text is preserved. No default behavior switches to this
codec, no external model is called, and no runtime dependency is added.

Consumers must understand the dictionary or use `decode_records` on an authorized
payload. Decoding expands the original text: byte savings are not a claim of
smaller actual model context or higher task success. `compact_session` adds its
normal header, checks retained values, preserves sources and writes a governed
derivation. The five-seed qualification measures the actual summary header and
reports source plus summary content together. Retaining originals means total
stored content increases; log, encryption and index overhead are not included.

Compaction now admits only sources currently readable by the requesting agent
in the selected tenant, omits hidden IDs from reports, forbids widening source
visibility, and rechecks versions/authorization before committing a summary.
Summarizers run outside metadata transaction fences. A correction or erasure
during summarization refuses the write. Source erasure reaches both decay-view
and `compaction_of` summaries; it does not leave encoded plaintext behind.

Qualification: `python -m benchmarks.lossless_compression`.
Raw results: `research/results/lossless-compression-qualification.json`.
The source commit is recorded in the report. Tests additionally cover private
inputs, foreign records, forbidden widening, mutation, malformed encodings and
oversized expansion. Existing compaction tests check authority inheritance,
dispute retention and correction propagation.

N25–N26 remain open for independently authored QA, matched-context comparisons,
local/approved model arms, actual tokenizer accounting and full monetary costs.
These functional fixtures cannot establish that the feature improves learning.
