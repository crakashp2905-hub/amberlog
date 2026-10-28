# Protocol — PM1: PersonaMem with a small local model (PUB-06). Descriptive.

**Fixed 2026-10-28**, before `benchmarks/personamem.py` was run once.

## Why descriptive

PersonaMem has no gold evidence labels, so no oracle with "the same budget, the same k, the same
mechanisms" (AGENTS.md 8b) can be built, and without a ceiling no threshold may be written (8a).
This run therefore reports numbers and makes **no claim** that any arm is better.

## Data

`bowen-upenn/PersonaMem`, split `32k` (MIT licence, read from the dataset card in CI before
ingestion). 120 questions, 17 or 18 per question type, drawn with `random.Random(1)`. Each question
is answered against its shared context up to `end_index_in_shared_context`.

## Model and budget

`ollama:qwen2.5:3b`, temperature as served, through `memory_fabric.models.ModelClient` (every call
logged with prompt hash and tokens). Every arm gets the same **1,200-word** context budget and the
same instruction: answer with the option letter.

## Arms

- `none`: question and options only.
- `recent`: the last 1,200 words of the conversation.
- `fabric`: every message written to a `MemoryFabric` (lexical retrieval), `retrieve(question, k=12)`,
  filled to 1,200 words in rank order.

## Reported

Accuracy overall and by question type, with a paired bootstrap CI for `fabric − recent` and
`fabric − none` (seeded), unparsable answers counted wrong, model calls and tokens. Vendor numbers
(TencentDB: 48% → 76%, their model and harness) are context only and never compared as if like for like.
