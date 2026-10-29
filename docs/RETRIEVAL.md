# Retrieval: getting the best results

Amberlog decides **what may be shown** (lifecycle, tenancy, scope,
withdrawals). How well it **finds** the right memory depends on the retriever.
The default needs nothing installed; a trained retriever is one extra install
and one line.

## The one-line upgrade

```bash
pip install ".[retrieval]"          # ONNX models on CPU, no PyTorch
```

```python
from amberlog import Amberlog
from amberlog.retrievers import best_available

fabric = Amberlog("memory/store.db", **best_available(cache_path="memory/vectors.db"))
```

`best_available()` returns the configuration that won a measured comparison
on third-party benchmarks, or the built-in `lexical` ranking if the extra is
not installed. The model is downloaded once, on first use, and `cache_path`
keeps document vectors between restarts so a store is not re-embedded when it
is reopened. Keep that file beside the store: it is derived from memory
content.

What it chose, and by how much: see **Measured** below.

## Choosing yourself

| you have | use |
|---|---|
| nothing extra installed | the default (`retrieval="lexical"`) |
| a CPU and `pip install ".[retrieval]"` | `best_available()`, or `FastEmbedEmbedder(model)` with `retrieval="hybrid"` |
| PyTorch or a GPU already | `SentenceTransformerEmbedder(model)` with `retrieval="hybrid"` |
| an embeddings service (OpenAI, vLLM, TEI, LiteLLM, Ollama) | `HttpEmbedder(url, model, api_key_env="...")` with `retrieval="hybrid"` |

```python
from amberlog.retrievers import CrossEncoderReranker, FastEmbedEmbedder, HttpEmbedder

fabric = Amberlog("store.db", retrieval="hybrid",
                      embedder=FastEmbedEmbedder("BAAI/bge-base-en-v1.5", cache_path="vectors.db"),
                      rerank=CrossEncoderReranker("jinaai/jina-reranker-v1-turbo-en"))

remote = HttpEmbedder("https://api.openai.com/v1", "text-embedding-3-small",
                      api_key_env="OPENAI_API_KEY")
```

`HttpEmbedder` sends memory content to that endpoint. Use one inside your
trust boundary for anything sensitive. The key is read from the environment
for each request and never stored.

**Fuse only a strong arm.** `retrieval="hybrid"` fuses the embedder with
lexical ranking. With the built-in hashing embedder that is worse than
lexical alone; with a trained model it is better. So switch to `hybrid` when,
and only when, you plug in a trained embedder.

**A reranker reorders, it does not admit.** It runs after eligibility, so it
cannot surface a withdrawn memory or another tenant's.

## Speed

Lexical ranking scores only memories that share a query's rarer words and
stops once nothing unseen can reach the top results: about 0.6 ms a
retrieval at 10,000 memories. A trained embedder adds a model call for the
query (cached for repeated questions) and a scan of the vectors; a reranker
adds one model call per candidate it reorders (30 by default).

## Measured

Two third-party benchmarks, measured in CI on a shared runner (runs 40235543450 and 40401777737):
**SciFact** (300 questions over 5,183 scientific abstracts, nDCG@10) and
**LongMemEval** (60 long chat histories of about 490 turns each, share of the
answer-bearing turns found in the top 10), through the same `retrieve` you
call.

| configuration | SciFact | LongMemEval | time a search |
|---|---|---|---|
| default (`lexical`, nothing installed) | 0.621 | 0.768 | 9 ms |
| **`best_available()`: bge-base + lexical** | **0.743** | **0.861** | 46 ms |
| nomic-embed-text v1.5 + lexical | 0.735 | 0.855 | 69 ms |
| bge-small + lexical | 0.734 | 0.797 | 32 ms |
| snowflake arctic-embed-m + lexical | 0.732 | 0.845 | 35 ms |
| bge-small + lexical + jina reranker | 0.754 | 0.876 | 3.6 s |
| lexical + jina reranker | 0.720 | 0.851 | 3.5 s |

**What to take from it.** The trained embedder adds 12 points on scientific
text and 9 on conversation for about 40 ms a search. A reranker adds at most
two more points and costs seconds a search on a CPU, so `best_available()`
does not include one; add `rerank=CrossEncoderReranker(...)` yourself if your
searches are rare and quality matters more than latency, or you have a GPU.

**Conversation logs written by one agent:** set
`withhold_hostile_sources=False` (see LIMITATIONS). The LongMemEval numbers
above are measured that way.
