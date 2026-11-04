"""BM25 + TF-IDF + Dense Vector hybrid search index over log entries, leaves, and candidate scoring."""

import logging
import re
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from rank_bm25 import BM25Okapi

logger = logging.getLogger("treemem.index")

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.warning(
        "scikit-learn is not installed; candidate placement falling back to lexical-only scoring. "
        "Install with `pip install 'treemem[gate]'` for hybrid TF-IDF scoring."
    )

from treemem.embeddings import (
    EmbeddingProvider,
    cosine_similarity_matrix,
)

# Maximum number of embeddings kept in the LRU text-to-vector cache.
_EMBED_CACHE_MAX = 20000


def tokenize(text: str) -> List[str]:
    """Simple lowercase alphanumeric word tokenizer."""
    return [w.lower() for w in re.findall(r"\b\w+\b", text) if len(w) > 0]


class SearchIndex:
    """Maintains BM25 + TF-IDF + Dense Vector hybrid index over log entries and leaf nodes.

    Embeddings are **opt-in**: pass an EmbeddingProvider explicitly or leave as
    None (the default) for lexical-only operation.  No provider is auto-detected
    and no network call is made unless the caller explicitly passes a remote provider.

    Private-path safety: the caller MUST pass ``private_paths`` (a set of node
    paths whose sensitivity is 'private', including all ancestor paths of every
    private node) so that build() and add_entry() can skip embedding private text.
    """

    # Default weights when dense vectors are not active
    _W_TFIDF = 0.60
    _W_BM25 = 0.40

    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        private_paths: Optional[Set[str]] = None,
        is_private_path_fn: Optional[Callable[[str], bool]] = None,
    ):
        self.entry_docs: List[Dict[str, Any]] = []
        self.placement_table: Dict[str, str] = {}  # entry_id -> leaf_path
        self.node_docs: List[Dict[str, Any]] = []  # path, name, aliases, summary
        self.bm25_entries: Optional[BM25Okapi] = None
        self.bm25_nodes: Optional[BM25Okapi] = None
        # Cached tokenization of entry docs (parallel to entry_docs) and dirty flags.
        # Lexical statistics (BM25 / TF-IDF) are refit lazily on the next query so that
        # incremental updates give exactly the same scores as a full build().
        self._entry_tokens: List[List[str]] = []
        self._entries_dirty: bool = False
        self._nodes_dirty: bool = False
        # TF-IDF semantic layer
        self._tfidf_vectorizer: Optional[Any] = None  # TfidfVectorizer
        self._tfidf_matrix: Optional[Any] = None      # fitted sparse matrix
        # Dense vector embedding layer — None by default (opt-in)
        self.embedding_provider: Optional[EmbeddingProvider] = embedding_provider
        self._node_embeddings: Optional[Any] = None   # np.ndarray [M, D]
        self._entry_embeddings: Optional[Any] = None  # np.ndarray [N, D]
        # Set of node paths (and their ancestors) that are private — never embedded.
        self._private_paths: Set[str] = private_paths if private_paths is not None else set()
        self._is_private_path_fn: Optional[Callable[[str], bool]] = is_private_path_fn
        # LRU embedding cache: text -> np.ndarray (1-D unit vector)
        # Prevents re-embedding the same text across rebuilds.
        self._embed_cache: "OrderedDict[str, Any]" = OrderedDict()

    def _is_private_path(self, path: str) -> bool:
        """Return True when path is private or is a descendant of a private node."""
        if not path:
            return False
        if self._is_private_path_fn is not None:
            try:
                return self._is_private_path_fn(path)
            except Exception:
                pass
        clean = path.strip("/")
        if clean in self._private_paths:
            return True
        # Check every prefix segment
        parts = clean.split("/")
        for i in range(len(parts)):
            prefix = "/".join(parts[: i + 1])
            if prefix in self._private_paths:
                return True
        return False

    def _may_embed_entry(self, entry: Dict[str, Any]) -> bool:
        """Decide whether an entry may be passed to the embedding provider.

        Rules:
        - If the entry is placed and its node or any ancestor is private:
          never embed (for ANY provider).
        - If the provider is remote (provider.is_remote is True):
          refuse when the entry is not yet placed (no path or path == 'unplaced'),
          or when its hint resolves to a private node or descendant of a private node.
          Unknown sensitivity counts as private for remote providers.
        - If the provider is local (provider.is_remote is False):
          unplaced entries are embedded so local search keeps working.
        """
        if self.embedding_provider is None:
            return False

        is_remote = bool(getattr(self.embedding_provider, "is_remote", False))

        eid = entry.get("entry_id", "")
        raw_path = self.placement_table.get(eid, entry.get("path", ""))
        clean_path = raw_path.strip().strip("/") if raw_path else ""
        is_placed = bool(clean_path and clean_path != "unplaced")

        # Placed entry: if its node or any ancestor is private, never embed (for ANY provider)
        if is_placed and self._is_private_path(clean_path):
            return False

        if is_remote:
            # Remote provider: unplaced entries have unknown sensitivity -> refuse
            if not is_placed:
                return False
            # Check hint: if hint resolves to a private path -> refuse
            hint = entry.get("hint", "").strip().strip("/")
            if hint and self._is_private_path(hint):
                return False
            # Unknown sensitivity counts as private: node must exist in known node_docs
            known_paths = {n.get("path", "") for n in self.node_docs}
            if clean_path not in known_paths:
                return False
            return True
        else:
            # Local provider: unplaced entries and placed non-private entries may be embedded
            return True

    def _cached_embed_batch(self, texts: List[str]) -> "Optional[Any]":
        """Embed texts using the cache.

        Returns a 2-D np.ndarray [len(texts), D] aligned to the input list.
        Texts already in the cache do not trigger a provider call.
        Returns None if the provider is unavailable.
        """
        if self.embedding_provider is None or not _NUMPY_AVAILABLE:
            return None
        if not texts:
            dim = self.embedding_provider.dimension
            return np.zeros((0, dim), dtype=np.float32)

        # Identify which texts need embedding
        missing_indices: List[int] = []
        missing_texts: List[str] = []
        for i, t in enumerate(texts):
            if t not in self._embed_cache:
                missing_indices.append(i)
                missing_texts.append(t)

        # Batch-embed only the missing texts
        if missing_texts:
            try:
                new_vecs = self.embedding_provider.embed_batch(missing_texts)
                for j, t in enumerate(missing_texts):
                    vec = new_vecs[j]
                    # Trim cache if at capacity (drop oldest)
                    if len(self._embed_cache) >= _EMBED_CACHE_MAX:
                        self._embed_cache.popitem(last=False)
                    self._embed_cache[t] = vec
            except Exception as e:
                logger.warning("embed_batch failed: %s", e)
                return None

        # Assemble final matrix in input order
        dim = self.embedding_provider.dimension
        result = np.zeros((len(texts), dim), dtype=np.float32)
        for i, t in enumerate(texts):
            if t in self._embed_cache:
                result[i] = self._embed_cache[t]
        return result

    def build(
        self,
        log_entries: List[Dict[str, Any]],
        leaf_facts: List[Dict[str, str]],
        nodes: List[Dict[str, Any]],
        private_paths: Optional[Set[str]] = None,
    ) -> None:
        """Rebuild index completely from log entries, leaves, and nodes.

        ``private_paths`` overrides or supplements the set passed at construction.
        Texts whose path is private (or a descendant of a private path) are
        never passed to the embedding provider.
        """
        if private_paths is not None:
            self._private_paths = private_paths

        self.entry_docs = []
        self.placement_table = {}
        self.node_docs = nodes

        for lf in leaf_facts:
            eid = lf.get("entry_id")
            path = lf.get("path")
            if eid and path:
                self.placement_table[eid] = path

        tokenized_corpus: List[List[str]] = []
        for entry in log_entries:
            eid = entry["entry_id"]
            fact_text = entry.get("fact", "")
            hint_text = entry.get("hint", "")
            full_text = f"{fact_text} {hint_text}"
            doc_obj = {
                "entry_id": eid,
                "text": fact_text,
                "hint": hint_text,
                "path": self.placement_table.get(eid, "unplaced"),
                "sensitivity": entry.get("sensitivity", "normal"),
            }
            self.entry_docs.append(doc_obj)
            toks = tokenize(full_text)
            tokenized_corpus.append(toks if toks else ["empty"])

        self._entry_tokens = tokenized_corpus
        self._entries_dirty = True
        self._ensure_entry_bm25()

        node_texts: List[str] = [self._node_text(n) for n in self.node_docs]
        self._refit_node_lexical()

        # Compute dense embeddings — skip private nodes entirely.
        self._node_embeddings = None
        self._entry_embeddings = None
        if self.embedding_provider is not None and _NUMPY_AVAILABLE:
            # Node embeddings: substitute a zero vector for private nodes so that
            # the matrix rows remain aligned with self.node_docs.
            node_embed_texts: List[str] = []
            node_private_mask: List[bool] = []
            for n, nt in zip(self.node_docs, node_texts):
                is_priv = self._is_private_path(n.get("path", ""))
                node_private_mask.append(is_priv)
                node_embed_texts.append("" if is_priv else nt)

            public_node_texts = [t for t, priv in zip(node_embed_texts, node_private_mask) if not priv]
            try:
                if node_texts:
                    dim = self.embedding_provider.dimension
                    result_nodes = np.zeros((len(node_texts), dim), dtype=np.float32)
                    pub_idx = [i for i, priv in enumerate(node_private_mask) if not priv]
                    if public_node_texts:
                        pub_mat = self._cached_embed_batch(public_node_texts)
                        if pub_mat is not None:
                            for list_pos, node_idx in enumerate(pub_idx):
                                result_nodes[node_idx] = pub_mat[list_pos]
                    self._node_embeddings = result_nodes
            except Exception as e:
                logger.warning("Failed to compute node dense embeddings: %s", e)
                self._node_embeddings = None

            # Entry embeddings: skip entries that may not be embedded.
            entry_texts_all: List[str] = []
            entry_allowed_mask: List[bool] = []
            for d in self.entry_docs:
                allowed = self._may_embed_entry(d)
                entry_allowed_mask.append(allowed)
                entry_texts_all.append(f"{d['text']} {d.get('hint', '')}".strip() if allowed else "")

            public_entry_texts = [t for t, allowed in zip(entry_texts_all, entry_allowed_mask) if allowed]
            try:
                if entry_texts_all:
                    dim = self.embedding_provider.dimension
                    result_entries = np.zeros((len(entry_texts_all), dim), dtype=np.float32)
                    pub_idx = [i for i, allowed in enumerate(entry_allowed_mask) if allowed]
                    if public_entry_texts:
                        pub_mat = self._cached_embed_batch(public_entry_texts)
                        if pub_mat is not None:
                            for list_pos, entry_idx in enumerate(pub_idx):
                                result_entries[entry_idx] = pub_mat[list_pos]
                    self._entry_embeddings = result_entries
            except Exception as e:
                logger.debug("Failed to compute entry dense embeddings: %s", e)
                self._entry_embeddings = None

    @staticmethod
    def _node_text(n: Dict[str, Any]) -> str:
        """Single source of truth for the text indexed for a node (build and refresh agree)."""
        aliases_str = " ".join(n.get("aliases", []) or [])
        return f"{n.get('name', '')} {aliases_str} {n.get('summary', '')}"

    def _ensure_entry_bm25(self) -> None:
        """Refit entry BM25 from cached tokens if entries were added since the last fit."""
        if not self._entries_dirty and (self.bm25_entries is not None or not self._entry_tokens):
            return
        self.bm25_entries = BM25Okapi(self._entry_tokens) if self._entry_tokens else None
        self._entries_dirty = False

    def _refit_node_lexical(self) -> None:
        """Fit node BM25 and TF-IDF over the current node_docs."""
        node_texts = [self._node_text(n) for n in self.node_docs]
        node_corpus = []
        for t in node_texts:
            toks = tokenize(t)
            node_corpus.append(toks if toks else ["empty"])
        self.bm25_nodes = BM25Okapi(node_corpus) if node_corpus else None

        self._tfidf_vectorizer = None
        self._tfidf_matrix = None
        if _SKLEARN_AVAILABLE and node_texts:
            try:
                vect = TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=1,
                    sublinear_tf=True,
                    strip_accents="unicode",
                    analyzer="word",
                )
                self._tfidf_matrix = vect.fit_transform(node_texts)
                self._tfidf_vectorizer = vect
            except Exception:
                self._tfidf_vectorizer = None
                self._tfidf_matrix = None
        self._nodes_dirty = False

    def _ensure_node_stats(self) -> None:
        if self._nodes_dirty:
            self._refit_node_lexical()

    def _node_index(self, node_path: str) -> Optional[int]:
        for i, n in enumerate(self.node_docs):
            if n.get("path") == node_path:
                return i
        return None

    def _embedding_rows_aligned(self, expected_rows: int) -> bool:
        return (
            self.embedding_provider is not None
            and _NUMPY_AVAILABLE
            and self._node_embeddings is not None
            and len(self._node_embeddings) == expected_rows
        )

    def refresh_node(self, path: str, node_data: Dict[str, Any]) -> None:
        """Update or add a single node without refitting anything eagerly.

        The node keeps its position (so dense-embedding rows stay aligned); lexical
        statistics are refit lazily on the next candidate_nodes() call, which makes the
        result identical to a full build() over the same nodes.
        """
        node_path = path or ""
        doc = {
            "path": node_path,
            "name": node_data.get("name", ""),
            "summary": node_data.get("summary", ""),
            "aliases": node_data.get("aliases", []) or [],
            "sensitivity": node_data.get("sensitivity", "normal"),
        }
        text = self._node_text(doc).strip()
        idx = self._node_index(node_path)
        rows_before = len(self.node_docs)
        was_aligned = self._embedding_rows_aligned(rows_before)

        if idx is not None:
            self.node_docs[idx] = doc
        elif text:
            self.node_docs.append(doc)
            idx = len(self.node_docs) - 1
        else:
            return

        if was_aligned:
            try:
                dim = self._node_embeddings.shape[1]
                row = np.zeros((1, dim), dtype=np.float32)
                if not self._is_private_path(node_path):
                    vecs = self._cached_embed_batch([text])
                    if vecs is not None:
                        row[0] = vecs[0]
                if idx < rows_before:
                    self._node_embeddings[idx] = row[0]
                else:
                    self._node_embeddings = np.vstack([self._node_embeddings, row])
            except Exception as e:
                logger.warning("Failed to refresh node embedding for '%s': %s", node_path, e)
                self._node_embeddings = None
        elif self._node_embeddings is not None:
            # Rows no longer line up with node_docs; drop dense signal until the next full build.
            self._node_embeddings = None

        self._nodes_dirty = True

    def remove_node(self, path: str) -> None:
        """Remove a node (used by split when nodes are moved or deleted)."""
        node_path = path or ""
        idx = self._node_index(node_path)
        if idx is None:
            return
        rows_before = len(self.node_docs)
        was_aligned = self._embedding_rows_aligned(rows_before)
        del self.node_docs[idx]
        if was_aligned:
            self._node_embeddings = np.delete(self._node_embeddings, idx, axis=0)
        elif self._node_embeddings is not None:
            self._node_embeddings = None
        self._nodes_dirty = True

    def add_entry(self, entry_id: str, fact: str, hint: str = "", path: str = "", sensitivity: str = "normal") -> None:
        """Add an entry to in-memory store.

        If the entry may not be embedded (e.g. private, or unplaced/hint-private for
        remote providers), the text is NOT passed to the embedding provider.
        """
        doc_obj = {
            "entry_id": entry_id,
            "text": fact,
            "hint": hint,
            "path": self.placement_table.get(entry_id, path or "unplaced"),
            "sensitivity": sensitivity,
        }
        self.entry_docs.append(doc_obj)
        toks = tokenize(f"{fact} {hint}")
        self._entry_tokens.append(toks if toks else ["empty"])
        self._entries_dirty = True

        if (
            self._may_embed_entry(doc_obj)
            and self.embedding_provider is not None
            and self._entry_embeddings is not None
            and _NUMPY_AVAILABLE
        ):
            try:
                text = f"{fact} {hint}".strip()
                vecs = self._cached_embed_batch([text])
                if vecs is not None:
                    self._entry_embeddings = np.vstack([self._entry_embeddings, vecs[0]])
            except Exception:
                pass
        elif self._entry_embeddings is not None and _NUMPY_AVAILABLE:
            # Keep row alignment: append a zero vector for skipped entry
            try:
                dim = self.embedding_provider.dimension if self.embedding_provider else self._entry_embeddings.shape[1]
                zero = np.zeros((1, dim), dtype=np.float32)
                self._entry_embeddings = np.vstack([self._entry_embeddings, zero])
            except Exception:
                pass

    def record_placement(self, entry_id: str, path: str) -> None:
        """Record where an entry is placed in the tree."""
        self.placement_table[entry_id] = path
        for doc in self.entry_docs:
            if doc["entry_id"] == entry_id:
                doc["path"] = path

    def query(self, query_str: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search over log entries and return matching hits."""
        if not self.entry_docs or not query_str.strip():
            return []

        self._ensure_entry_bm25()
        toks = tokenize(query_str)
        q_lower = query_str.lower()
        query_words = set(toks)

        scored_docs: List[Tuple[int, float]] = []

        bm25_scores = None
        if self.bm25_entries is not None and toks:
            try:
                bm25_scores = self.bm25_entries.get_scores(toks)
            except Exception:
                bm25_scores = None

        dense_entry_sims = None
        if (
            self.embedding_provider is not None
            and self._entry_embeddings is not None
            and len(self._entry_embeddings) == len(self.entry_docs)
            and _NUMPY_AVAILABLE
        ):
            try:
                q_vec = self.embedding_provider.embed_text(query_str)
                dense_entry_sims = cosine_similarity_matrix(q_vec, self._entry_embeddings)
            except Exception:
                dense_entry_sims = None

        for idx, doc in enumerate(self.entry_docs):
            full_text = f"{doc['text']} {doc.get('hint', '')}".lower()
            doc_toks = set(tokenize(full_text))

            score = 0.0
            if bm25_scores is not None and len(bm25_scores) > idx:
                score = float(bm25_scores[idx])

            # Exact keyword match bonus (ensures small corpora with zero IDF still score positively)
            overlap = query_words.intersection(doc_toks)
            if overlap:
                score += len(overlap) * 1.5

            if q_lower in full_text:
                score += 3.0

            if dense_entry_sims is not None and len(dense_entry_sims) > idx:
                d_sim = float(dense_entry_sims[idx])
                if d_sim > 0:
                    score += d_sim * 2.5

            if score > 0:
                scored_docs.append((idx, score))

        scored_docs.sort(key=lambda x: x[1], reverse=True)

        hits: List[Dict[str, Any]] = []
        for idx, score in scored_docs[:limit]:
            doc = self.entry_docs[idx]
            hits.append({
                "entry_id": doc["entry_id"],
                "text": doc["text"],
                "path": self.placement_table.get(doc["entry_id"], "unplaced"),
                "sensitivity": doc.get("sensitivity", "normal"),
                "score": round(score, 3),
            })
        return hits

    def candidate_nodes(
        self,
        fact: str,
        hint: str = "",
        limit: int = 3,
        all_node_paths: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Propose candidate nodes for placing a fact using BM25 + TF-IDF + Dense Vector hybrid scoring.

        Scoring formula:
          - If dense and tfidf active: 0.50 * dense + 0.30 * tfidf + 0.20 * bm25/lexical
          - If dense only: 0.70 * dense + 0.30 * bm25/lexical
          - If tfidf only: 0.60 * tfidf + 0.40 * bm25/lexical
          - If lexical only: 1.00 * lexical
        Results are ranked by combined score descending.
        """
        candidates: List[Dict[str, Any]] = []
        seen_paths: Set[str] = set()

        # 1. Exact hint match → always surfaces first at score 1.0
        clean_hint = hint.strip().strip("/")
        if clean_hint and all_node_paths and clean_hint in all_node_paths:
            candidates.append({"path": clean_hint, "score": 1.0, "source": "hint"})
            seen_paths.add(clean_hint)

        if not self.node_docs:
            return candidates[:limit]

        self._ensure_node_stats()
        query_text = f"{fact} {hint}".strip()
        toks = tokenize(query_text)
        query_words = set(toks)

        # 2. BM25 overlap scores (word-level, normalised to [0, 1])
        bm25_scores: List[float] = [0.0] * len(self.node_docs)
        if self.bm25_nodes is not None and toks:
            try:
                raw = self.bm25_nodes.get_scores(toks)
                max_raw = float(max(raw)) if max(raw) > 0 else 1.0
                bm25_scores = [float(s) / max_raw for s in raw]
            except Exception:
                pass

        # Also compute simple word-overlap count (for corpora where BM25 IDF is flat)
        overlap_counts: List[float] = []
        for n in self.node_docs:
            node_text = (
                f"{n.get('name', '')} {' '.join(n.get('aliases', []))} {n.get('summary', '')}"
            ).lower()
            nt = set(tokenize(node_text))
            overlap_counts.append(float(len(query_words.intersection(nt))))
        max_overlap = max(overlap_counts) if max(overlap_counts) > 0 else 1.0
        norm_overlap = [c / max_overlap for c in overlap_counts]

        # Combine BM25 and word-overlap to form a robust lexical signal
        lexical: List[float] = [
            0.5 * bm25_scores[i] + 0.5 * norm_overlap[i]
            for i in range(len(self.node_docs))
        ]

        # 3. Dense vector cosine similarity scores (local providers only — remote providers never see unplaced text)
        dense_cos: List[float] = [0.0] * len(self.node_docs)
        has_dense = False
        is_remote = bool(getattr(self.embedding_provider, "is_remote", False))
        if (
            self.embedding_provider is not None
            and not is_remote
            and self._node_embeddings is not None
            and len(self._node_embeddings) == len(self.node_docs)
            and query_text
            and _NUMPY_AVAILABLE
        ):
            try:
                q_vec = self.embedding_provider.embed_text(query_text)
                sims = cosine_similarity_matrix(q_vec, self._node_embeddings)
                dense_cos = [max(0.0, float(s)) for s in sims]
                has_dense = any(s > 0 for s in dense_cos)
            except Exception as e:
                logger.debug("Failed to compute dense candidate similarities: %s", e)

        # 4. TF-IDF cosine similarity scores (semantic signal)
        tfidf_cos: List[float] = [0.0] * len(self.node_docs)
        has_tfidf = False
        if (
            _SKLEARN_AVAILABLE
            and self._tfidf_vectorizer is not None
            and self._tfidf_matrix is not None
            and query_text
        ):
            try:
                q_vec = self._tfidf_vectorizer.transform([query_text])
                sims = cosine_similarity(q_vec, self._tfidf_matrix)[0]
                tfidf_cos = [max(0.0, float(s)) for s in sims]
                has_tfidf = any(s > 0 for s in tfidf_cos)
            except Exception:
                pass

        # 5. Hybrid combination and ranking
        if has_dense and has_tfidf:
            w_dense, w_tfidf, w_bm25 = 0.50, 0.30, 0.20
        elif has_dense:
            w_dense, w_tfidf, w_bm25 = 0.70, 0.0, 0.30
        elif has_tfidf:
            w_dense, w_tfidf, w_bm25 = 0.0, self._W_TFIDF, self._W_BM25
        else:
            w_dense, w_tfidf, w_bm25 = 0.0, 0.0, 1.0

        ranked: List[Tuple[int, float, str]] = []  # (node_idx, score, source)
        for i, n in enumerate(self.node_docs):
            p = n["path"]
            if p in seen_paths:
                continue
            combined = w_dense * dense_cos[i] + w_tfidf * tfidf_cos[i] + w_bm25 * lexical[i]
            if combined > 0:
                # Determine dominant signal for transparency
                contribs = [
                    (w_dense * dense_cos[i], "dense"),
                    (w_tfidf * tfidf_cos[i], "tfidf"),
                    (w_bm25 * lexical[i], "bm25"),
                ]
                contribs.sort(key=lambda x: x[0], reverse=True)
                src = contribs[0][1]
                ranked.append((i, combined, src))

        ranked.sort(key=lambda x: x[1], reverse=True)

        for i, score, src in ranked:
            p = self.node_docs[i]["path"]
            candidates.append({"path": p, "score": round(min(1.0, score), 3), "source": src})
            seen_paths.add(p)
            if len(candidates) >= limit:
                break

        return candidates[:limit]
