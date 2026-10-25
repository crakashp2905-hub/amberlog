# Retrieval: getting the best results

Memory Fabric decides **what may be shown** (lifecycle, tenancy, scope,
withdrawals). How well it **finds** the right memory depends on the retriever.
The default needs nothing installed; a trained retriever is one extra install
and one line.

## The one-line upgrade

```bash
pip install ".[retrieval]"          # ONNX models on CPU, no PyTorch
```

```python
from memory_fabric import MemoryFabric
from memory_fabric.retrievers import best_available

fabric = MemoryFabric("memory/store.db", **best_available(cache_path="memory/vectors.db"))
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
from memory_fabric.retrievers import CrossEncoderReranker, FastEmbedEmbedder, HttpEmbedder

fabric = MemoryFabric("store.db", retrieval="hybrid",
                      embedder=FastEmbedEmbedder("BAAI/bge-base-en-v1.5", cache_path="vectors.db"),
                      rerank=CrossEncoderReranker("Xenova/ms-marco-MiniLM-L-6-v2"))

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
