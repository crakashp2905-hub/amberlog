"""Trained retrievers: embedding models, a cross-encoder reranker, and one switch.

The built-in hashing embedder keeps the package at zero dependencies, and it
is the weakest arm on every real corpus measured (SciFact: 0.315 nDCG@10
against lexical's 0.621). A trained embedder fused with lexical scores 0.726
there. This module makes the trained path one line:

    from memory_fabric import MemoryFabric
    from memory_fabric.retrievers import best_available

    fabric = MemoryFabric("memory.db", **best_available())

`best_available()` returns the configuration that won the registered
comparison (`research/prereg/r3-best-retriever.md`), when its dependency is
installed (`pip install "memory-fabric[retrieval]"`), and the measured best
zero-dependency configuration (`lexical`) otherwise. It never downloads
anything silently: the model is fetched the first time it is used, into
`cache_dir`, and the call says so on stderr.

Three embedders, one protocol (`vectors.Embedder`):

- `FastEmbedEmbedder` -- ONNX models through `fastembed`. No PyTorch, CPU,
  the recommended default.
- `SentenceTransformerEmbedder` -- any `sentence-transformers` model, for
  teams that already run PyTorch or a GPU.
- `HttpEmbedder` -- any OpenAI-compatible `/v1/embeddings` endpoint (OpenAI,
  vLLM, TEI, LiteLLM, Ollama's compatibility API). The key is read from an
  environment variable at call time and never stored.

`CrossEncoderReranker` scores (query, memory) pairs with a cross-encoder and
reorders the candidate pool after fusion. It reorders only: what is eligible,
and the relevance floor, are decided before it runs, so a reranker cannot
surface a memory the gates excluded.

Every embedder caches vectors by (model, text). With `cache_path`, the cache
is a SQLite file and survives restarts, so reopening a store does not
re-embed it. Queries are cached too: on LongMemEval the dominant retrieval
cost was embedding the *query* (393 ms a call), not scanning the corpus.
"""

from __future__ import annotations

__stability__ = "beta"

import hashlib
import json
import os
import sqlite3
import sys
import threading
import urllib.request
from collections import OrderedDict
from typing import Any, Callable, Iterable, Iterator, Protocol, Sequence

DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
QUERY_CACHE_SIZE = 4096


class Reranker(Protocol):
    """Scores each text against the query; higher is more relevant."""

    def score(self, query: str, texts: Sequence[str]) -> list[float]: ...


class VectorCache:
    """Vectors keyed by (model, text): in memory, optionally on disk.

    The disk form is a single SQLite table, written in batches. It holds
    vectors of memory content, so it is as sensitive as the store itself:
    keep it beside the database, with the same permissions.
    """

    def __init__(self, model: str, path: str | None = None) -> None:
        self.model = model
        self._memory: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None
        if path:
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS vectors "
                             "(key TEXT PRIMARY KEY, vector TEXT NOT NULL)")
            self._db.commit()
            try:
                os.chmod(path, 0o600)
            except OSError:  # pragma: no cover - platform dependent
                pass

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\0{text}".encode("utf-8")).hexdigest()

    def get(self, text: str) -> list[float] | None:
        key = self._key(text)
        with self._lock:
            found = self._memory.get(key)
            if found is not None or self._db is None:
                return found
            row = self._db.execute("SELECT vector FROM vectors WHERE key = ?",
                                   (key,)).fetchone()
            if row is None:
                return None
            vector = json.loads(row[0])
            self._memory[key] = vector
            return vector

    def put_many(self, pairs: Iterable[tuple[str, list[float]]]) -> None:
        rows = [(self._key(text), vector) for text, vector in pairs]
        with self._lock:
            for key, vector in rows:
                self._memory[key] = vector
            if self._db is not None and rows:
                self._db.executemany(
                    "INSERT OR REPLACE INTO vectors (key, vector) VALUES (?, ?)",
                    [(key, json.dumps(vector)) for key, vector in rows])
                self._db.commit()

    def __len__(self) -> int:
        return len(self._memory)

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None


BATCH_CHARS_PER_TEXT = 2000


class _BatchEmbedder:
    """Shared caching and batching. Subclasses implement `_documents` and `_queries`."""

    model: str
    dim: int

    def __init__(self, model: str, cache_path: str | None, batch_size: int) -> None:
        self.model = model
        self.dim = 0
        self.batch_size = max(1, batch_size)
        self.cache = VectorCache(model, cache_path)
        self._queries_cache: OrderedDict[str, list[float]] = OrderedDict()
        self.calls = 0

    def close(self) -> None:
        """Close the on-disk vector cache, if any. The in-memory cache stays."""
        self.cache.close()

    def _documents(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        raise NotImplementedError

    def _queries(self, texts: list[str]) -> list[list[float]]:
        return self._documents(texts)

    def warm(self, texts: Sequence[str]) -> None:
        """Embed many documents in batches. Already-cached texts are skipped."""
        missing = [t for t in dict.fromkeys(texts) if self.cache.get(t) is None]
        # Similar lengths in one batch: a batch is padded to its longest text,
        # so mixing a 10-word turn with a 500-word one wastes most of the work.
        missing.sort(key=len)
        for batch in self._batches(missing):
            self.calls += 1
            vectors = self._documents(batch)
            if vectors:
                self.dim = len(vectors[0])
            self.cache.put_many(zip(batch, vectors))

    def _batches(self, texts: list[str]) -> Iterator[list[str]]:
        """At most `batch_size` texts and about `batch_size` x 2,000 characters.

        Sorted by length, the long texts end up together, and a long-context
        model pads the whole batch to them: 64 texts of 8,000 tokens asked
        onnxruntime for 29 GB. The character budget keeps the long batches small.
        """
        budget = self.batch_size * BATCH_CHARS_PER_TEXT
        batch: list[str] = []
        size = 0
        for text in texts:
            if batch and (len(batch) >= self.batch_size or size + len(text) > budget):
                yield batch
                batch, size = [], 0
            batch.append(text)
            size += len(text)
        if batch:
            yield batch

    def embed(self, text: str) -> list[float]:
        found = self.cache.get(text)
        if found is None:
            self.warm([text])
            found = self.cache.get(text) or []
        return found

    def embed_query(self, text: str) -> list[float]:
        """Queries may need a different encoding (an instruction prefix)."""
        found = self._queries_cache.get(text)
        if found is not None:
            self._queries_cache.move_to_end(text)
            return found
        self.calls += 1
        vector = self._queries([text])[0]
        self.dim = self.dim or len(vector)
        self._queries_cache[text] = vector
        if len(self._queries_cache) > QUERY_CACHE_SIZE:
            self._queries_cache.popitem(last=False)
        return vector


def _missing(package: str, extra: str = "retrieval") -> ImportError:
    return ImportError(f"{package} is not installed: pip install \"memory-fabric[{extra}]\" "
                       f"(or pip install {package})")


# Prefixes the model was trained with, which fastembed does not add. Without
# them arctic-m scored 0.118 nDCG@10 on SciFact, far below its published range
# (R3). bge v1.5 works without one and is left as measured.
MODEL_PREFIXES: dict[str, tuple[str, str]] = {
    "snowflake/snowflake-arctic-embed-m": ("Represent this sentence for searching relevant passages: ", ""),
    "snowflake/snowflake-arctic-embed-m-long": ("Represent this sentence for searching relevant passages: ", ""),
    "nomic-ai/nomic-embed-text-v1.5": ("search_query: ", "search_document: "),
    "nomic-ai/nomic-embed-text-v1.5-Q": ("search_query: ", "search_document: "),
}
"""model -> (query prefix, document prefix)."""


class FastEmbedEmbedder(_BatchEmbedder):
    """ONNX embedding models through `fastembed`. CPU, no PyTorch.

    `query_prefix` and `document_prefix` default to the model's own (see
    `MODEL_PREFIXES`); pass "" to turn one off.
    """

    def __init__(self, model: str = DEFAULT_EMBED_MODEL, cache_path: str | None = None,
                 cache_dir: str | None = None, batch_size: int = 64,
                 threads: int | None = None, query_prefix: str | None = None,
                 document_prefix: str | None = None) -> None:
        known_query, known_document = MODEL_PREFIXES.get(model, ("", ""))
        self.query_prefix = known_query if query_prefix is None else query_prefix
        self.document_prefix = known_document if document_prefix is None else document_prefix
        super().__init__(model, cache_path, batch_size)
        if self.document_prefix:
            # Cached vectors are for one document encoding; keep them apart.
            self.cache.model = f"{model}|{self.document_prefix}"
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise _missing("fastembed") from exc
        print(f"memory-fabric: loading embedding model {model} (downloaded on first use)",
              file=sys.stderr)
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir, threads=threads)

    def _documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.passage_embed(
            [self.document_prefix + t for t in texts], batch_size=self.batch_size)]

    def _queries(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.query_embed([self.query_prefix + t for t in texts])]


class SentenceTransformerEmbedder(_BatchEmbedder):
    """Any `sentence-transformers` model. `query_prefix` for models that want one."""

    def __init__(self, model: str = DEFAULT_EMBED_MODEL, cache_path: str | None = None,
                 batch_size: int = 64, device: str | None = None,
                 query_prefix: str = "", document_prefix: str = "") -> None:
        super().__init__(model, cache_path, batch_size)
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise _missing("sentence-transformers", "retrieval-torch") from exc
        self._model = SentenceTransformer(model, device=device)
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix

    def _encode(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.encode(
            texts, batch_size=self.batch_size, normalize_embeddings=True)]

    def _documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self.document_prefix + t for t in texts])

    def _queries(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self.query_prefix + t for t in texts])


class HttpEmbedder(_BatchEmbedder):
    """An OpenAI-compatible `/v1/embeddings` endpoint.

    `api_key_env` names the environment variable holding the key; the key is
    read for each request and never kept on the object, logged or cached.
    Memory content is sent to that endpoint: use one inside your trust
    boundary for anything sensitive.
    """

    def __init__(self, url: str, model: str, api_key_env: str | None = None,
                 cache_path: str | None = None, batch_size: int = 64,
                 timeout: float = 60.0,
                 opener: Callable[..., Any] | None = None) -> None:
        super().__init__(model, cache_path, batch_size)
        self.url = url.rstrip("/")
        if not self.url.endswith("/embeddings"):
            self.url += "/embeddings"
        self.api_key_env = api_key_env
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def _documents(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key_env:
            bearer = os.environ.get(self.api_key_env)
            if not bearer:
                raise RuntimeError(f"{self.api_key_env} is not set")
            headers["Authorization"] = "Bearer " + bearer
        request = urllib.request.Request(
            self.url, data=json.dumps({"model": self.model, "input": texts}).encode(),
            headers=headers, method="POST")
        with self._open(request, timeout=self.timeout) as response:
            body = json.loads(response.read())
        rows = sorted(body.get("data", []), key=lambda r: r.get("index", 0))
        if len(rows) != len(texts):
            raise RuntimeError(f"embedding endpoint returned {len(rows)} vectors "
                               f"for {len(texts)} inputs")
        return [list(map(float, r["embedding"])) for r in rows]


class CrossEncoderReranker:
    """A cross-encoder over (query, memory) pairs, through `fastembed`.

    `pool` caps how many candidates are scored per query: a cross-encoder is a
    model call per pair, so its cost grows with the pool, not the store.
    """

    def __init__(self, model: str = DEFAULT_RERANK_MODEL, cache_dir: str | None = None,
                 batch_size: int = 32, pool: int = 30,
                 backend: Any = None) -> None:
        self.model = model
        self.batch_size = batch_size
        self.pool = pool
        if backend is not None:
            self._model = backend
            return
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as exc:
            raise _missing("fastembed") from exc
        print(f"memory-fabric: loading reranker {model} (downloaded on first use)",
              file=sys.stderr)
        self._model = TextCrossEncoder(model_name=model, cache_dir=cache_dir)

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        return [float(s) for s in self._model.rerank(query, list(texts),
                                                     batch_size=self.batch_size)]


def apply_reranker(reranker: Reranker, query: str, hits: Sequence[tuple[str, float]],
                   contents: Callable[[str], str]) -> list[tuple[str, float]]:
    """Reorder the head of `hits` by the reranker.

    Relevance values stay the retriever's values, reassigned in the new order,
    so floors and thresholds keep their scale. Candidates past the reranker's
    pool keep their place behind it.
    """
    pool = max(1, int(getattr(reranker, "pool", len(hits)) or len(hits)))
    head, tail = list(hits[:pool]), list(hits[pool:])
    if len(head) < 2:
        return list(hits)
    scores = reranker.score(query, [contents(mid) for mid, _ in head])
    order = sorted(range(len(head)), key=lambda i: (-scores[i], i))
    # Exposure policies rank by relevance, so the new order must be carried
    # by the scores. The head's own scores are handed out again, best first:
    # the same values (floors keep their meaning), in the reranker's order.
    values = sorted((score for _, score in head), reverse=True)
    return [(head[i][0], values[rank]) for rank, i in enumerate(order)] + tail


def fastembed_available() -> bool:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


def best_available(cache_path: str | None = None, rerank: bool = True,
                   cache_dir: str | None = None) -> dict[str, Any]:
    """`MemoryFabric` keyword arguments for the best retriever this machine can run.

    With `fastembed` installed: the registered winner, `bge-base` fused with
    lexical (`research/results/r3-best-retriever.md`). No reranker passed the
    comparison's cost bound, so `rerank` adds one only if `BEST` names one. Without it: `lexical`, the best
    zero-dependency arm on every external benchmark.
    """
    if not fastembed_available():
        return {"retrieval": "lexical"}
    config: dict[str, Any] = {
        "retrieval": "hybrid",
        "embedder": FastEmbedEmbedder(str(BEST["embedder"]), cache_path=cache_path,
                                      cache_dir=cache_dir),
    }
    if rerank and BEST.get("reranker"):
        config["rerank"] = CrossEncoderReranker(str(BEST["reranker"]), cache_dir=cache_dir)
    return config


# The configuration `best_available` builds. Set from the registered result,
# not by taste: changing it means re-running experiments/retriever_eval.py.
# R3 (research/results/r3-best-retriever.md): bge-base fused with lexical
# passed every bar; every reranker failed the 250 ms cost bound.
BEST: dict[str, str | None] = {
    "embedder": "BAAI/bge-base-en-v1.5",
    "reranker": None,
}


ENV_EMBEDDER = "MEMORY_FABRIC_EMBEDDER"
ENV_RERANKER = "MEMORY_FABRIC_RERANKER"


def embedder_from_spec(spec: str, cache_path: str | None = None) -> Any:
    """An embedder named the way models are (`models.py`):

        fastembed:BAAI/bge-small-en-v1.5        local ONNX
        st:sentence-transformers/all-MiniLM-L6-v2
        openai:text-embedding-3-small           OPENAI_API_KEY
        ollama:nomic-embed-text                 local server
        gemini:text-embedding-004, mistral:mistral-embed, together:..., vllm:...
        compat:<model>@https://host/v1          any OpenAI-compatible endpoint
    """
    from .models import OPENAI_COMPATIBLE, ModelSpec

    provider, _, model = spec.partition(":")
    provider = provider.lower()
    if provider == "fastembed":
        return FastEmbedEmbedder(model, cache_path=cache_path)
    if provider in ("st", "sentence-transformers"):
        return SentenceTransformerEmbedder(model, cache_path=cache_path)
    parsed = ModelSpec.parse(spec)
    if parsed.provider == "compat":
        return HttpEmbedder(parsed.base_url or "", parsed.model, api_key_env="MF_COMPAT_API_KEY",
                            cache_path=cache_path)
    if parsed.provider not in OPENAI_COMPATIBLE:
        raise ValueError(f"{parsed.provider} has no embeddings endpoint here; use fastembed:, "
                         "st:, openai:, ollama:, gemini:, mistral:, together:, vllm: or compat:")
    base, key_env = OPENAI_COMPATIBLE[parsed.provider]
    if base.startswith("$"):
        base = os.environ.get(base[1:], "")
    return HttpEmbedder(base, parsed.model, api_key_env=key_env if key_env and os.environ.get(
        key_env) else None, cache_path=cache_path)


def from_environment(cache_path: str | None = None) -> dict[str, Any]:
    """`MemoryFabric` keyword arguments from MEMORY_FABRIC_EMBEDDER / _RERANKER,
    falling back to `best_available()` when neither is set."""
    emb, rr = os.environ.get(ENV_EMBEDDER), os.environ.get(ENV_RERANKER)
    if not emb and not rr:
        return best_available(cache_path=cache_path)
    config: dict[str, Any] = {"retrieval": "lexical"}
    if emb:
        config.update(retrieval="hybrid", embedder=embedder_from_spec(emb, cache_path))
    if rr:
        config["rerank"] = CrossEncoderReranker(rr.split(":", 1)[-1])
    return config
