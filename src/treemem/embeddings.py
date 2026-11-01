"""Dense vector embedding providers for semantic placement and hybrid retrieval."""

from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np

logger = logging.getLogger("treemem.embeddings")


def normalize_vector(v: np.ndarray) -> np.ndarray:
    """Normalize vector to unit length (L2 norm)."""
    norm = np.linalg.norm(v)
    if norm < 1e-12:
        return v
    return v / norm


def normalize_matrix(mat: np.ndarray) -> np.ndarray:
    """Normalize each row of matrix to unit length (L2 norm)."""
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    return mat / norms


def cosine_similarity(u: np.ndarray, v: np.ndarray) -> float:
    """Compute cosine similarity between two 1D vectors."""
    u_norm = np.linalg.norm(u)
    v_norm = np.linalg.norm(v)
    if u_norm < 1e-12 or v_norm < 1e-12:
        return 0.0
    return float(np.dot(u, v) / (u_norm * v_norm))


def cosine_similarity_matrix(query_vec: np.ndarray, doc_mat: np.ndarray) -> np.ndarray:
    """Compute cosine similarities between a 1D query vector and a 2D doc matrix [N, D].

    Assumes query_vec and rows of doc_mat are unit-normalized.
    Returns a 1D array of length N with similarity scores in [-1.0, 1.0].
    """
    if doc_mat.size == 0:
        return np.array([], dtype=np.float32)

    q = query_vec.astype(np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm > 1e-12:
        q = q / q_norm

    docs = doc_mat.astype(np.float32)
    dots = np.dot(docs, q)
    # Clip to valid cosine range
    return np.clip(dots, -1.0, 1.0)


class EmbeddingProvider(ABC):
    """Abstract base class for dense vector embedding models."""

    is_remote: bool = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the embedding provider."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding vector dimension."""
        ...

    @abstractmethod
    def embed_text(self, text: str) -> np.ndarray:
        """Generate a 1D unit-normalized float32 embedding vector for text."""
        ...

    @abstractmethod
    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        """Generate a 2D [N, D] unit-normalized float32 embedding matrix for texts."""
        ...


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Fast, deterministic hash-projection embedding generator for testing and offline environments.

    Projects token and character n-grams through a deterministic pseudo-random projection matrix.
    Requires no external model downloads or network calls.
    """

    is_remote: bool = False

    def __init__(self, dimension: int = 128, seed: int = 42):
        self._dim = dimension
        self._seed = seed
        self._rng = np.random.RandomState(seed)
        # 10,000 buckets projected into dimension D
        self._num_buckets = 10000
        self._proj = self._rng.randn(self._num_buckets, self._dim).astype(np.float32)
        # Normalize projection columns
        self._proj = normalize_matrix(self._proj)

    @property
    def name(self) -> str:
        return f"deterministic-{self._dim}d"

    @property
    def dimension(self) -> int:
        return self._dim

    def _hash_token(self, token: str) -> int:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        return h % self._num_buckets

    def embed_text(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dim, dtype=np.float32)
        clean = text.lower().strip()
        if not clean:
            return vec

        words = re.findall(r"\b\w+\b", clean)
        if not words:
            return vec

        for w in words:
            idx = self._hash_token(w)
            vec += self._proj[idx]

        # Add bigrams for local context sensitivity
        for i in range(len(words) - 1):
            bg = f"{words[i]}_{words[i+1]}"
            idx = self._hash_token(bg)
            vec += 0.5 * self._proj[idx]

        return normalize_vector(vec)

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        vecs = [self.embed_text(t) for t in texts]
        return np.vstack(vecs).astype(np.float32)


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """Embedding provider connecting to any OpenAI-compatible `/v1/embeddings` endpoint.

    Works with OpenAI, Voyage, Ollama, Together, vLLM, etc.
    """

    is_remote: bool = True

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        dimension: int = 1536,
        timeout: float = 30.0,
    ):
        self._api_key = api_key or os.getenv("TREEMEM_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self._base_url = (
            base_url
            or os.getenv("TREEMEM_EMBEDDING_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self._model = (
            model
            or os.getenv("TREEMEM_EMBEDDING_MODEL")
            or "text-embedding-3-small"
        )
        self._dim = dimension
        self._timeout = timeout

        try:
            import httpx
            self._httpx = httpx
        except ImportError:
            raise ImportError(
                "httpx is required for OpenAICompatibleEmbeddingProvider. Install with `pip install httpx`."
            )

    @property
    def name(self) -> str:
        return f"api-{self._model}"

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)

        url = f"{self._base_url}/embeddings"
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._model,
            "input": list(texts),
        }

        with self._httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Sort by index to maintain original order
        items = sorted(data["data"], key=lambda x: x["index"])
        raw_vecs = [item["embedding"] for item in items]
        mat = np.array(raw_vecs, dtype=np.float32)
        if mat.shape[1] != self._dim:
            self._dim = mat.shape[1]
        return normalize_matrix(mat)

    def embed_text(self, text: str) -> np.ndarray:
        mat = self.embed_batch([text])
        if mat.shape[0] == 0:
            return np.zeros(self._dim, dtype=np.float32)
        return mat[0]


class SentenceTransformersProvider(EmbeddingProvider):
    """Local dense embedding provider using HuggingFace sentence-transformers."""

    is_remote: bool = False

    def __init__(self, model_name: Optional[str] = None):
        self._model_name = (
            model_name
            or os.getenv("TREEMEM_EMBEDDING_MODEL")
            or "all-MiniLM-L6-v2"
        )
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            if hasattr(self._model, "get_embedding_dimension"):
                self._dim = self._model.get_embedding_dimension()
            else:
                self._dim = self._model.get_sentence_embedding_dimension()
        except ImportError:
            raise ImportError(
                "sentence-transformers is not installed. Install with `pip install sentence-transformers`."
            )

    @property
    def name(self) -> str:
        return f"st-{self._model_name}"

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_text(self, text: str) -> np.ndarray:
        vec = self._model.encode(text, normalize_embeddings=True)
        return np.asarray(vec, dtype=np.float32)

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        mat = self._model.encode(list(texts), normalize_embeddings=True)
        return np.asarray(mat, dtype=np.float32)


# Global singleton cache for provider
_GLOBAL_PROVIDER: Optional[EmbeddingProvider] = None


def get_embedding_provider(
    provider_name: Optional[str] = None,
    force_new: bool = False,
    **kwargs: Any,
) -> Optional[EmbeddingProvider]:
    """Factory to get or initialize an EmbeddingProvider.

    Embeddings are **opt-in**. With no explicit choice (argument or
    ``TREEMEM_EMBEDDING_PROVIDER`` env var), this function returns ``None``
    and no network call is made.

    Resolution order:
      1. ``provider_name`` argument, or env ``TREEMEM_EMBEDDING_PROVIDER``:
         - ``'deterministic'`` or ``'mock'`` -> DeterministicEmbeddingProvider
           (offline, deterministic hashing — does NOT demonstrate semantic quality)
         - ``'openai'`` or ``'api'``         -> OpenAICompatibleEmbeddingProvider
           (requires an API key; sends text to a remote endpoint)
         - ``'sentence-transformers'``        -> SentenceTransformersProvider
           (local HuggingFace model; downloads on first use)
         - ``'none'``, ``'disabled'``, etc.  -> None
      2. Otherwise                            -> None

    Remote embedding (``openai``/``api``) requires ``TREEMEM_EMBEDDING_PROVIDER``
    to be set explicitly.  Setting ``OPENAI_API_KEY`` or
    ``TREEMEM_EMBEDDING_API_KEY`` alone does **not** activate remote embedding.
    """
    global _GLOBAL_PROVIDER

    if not force_new and _GLOBAL_PROVIDER is not None and provider_name is None:
        return _GLOBAL_PROVIDER

    choice = provider_name or os.getenv("TREEMEM_EMBEDDING_PROVIDER")
    if choice:
        choice = choice.lower().strip()

    provider: Optional[EmbeddingProvider] = None

    if not choice or choice in ("none", "disabled", "off", "false"):
        # No explicit choice: return None — embeddings are opt-in.
        return None

    if choice in ("deterministic", "mock", "test"):
        dim = kwargs.get("dimension", 128)
        provider = DeterministicEmbeddingProvider(dimension=dim)
    elif choice in ("openai", "api"):
        provider = OpenAICompatibleEmbeddingProvider(**kwargs)
    elif choice in ("sentence-transformers", "st"):
        provider = SentenceTransformersProvider(**kwargs)
    else:
        logger.warning(
            "Unknown TREEMEM_EMBEDDING_PROVIDER value %r; returning None. "
            "Valid values: deterministic, openai, api, sentence-transformers.",
            choice,
        )
        return None

    if not force_new and provider is not None:
        _GLOBAL_PROVIDER = provider

    return provider
