"""BM25 + TF-IDF + Dense Vector hybrid search index over log entries, leaves, and candidate scoring."""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

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
    get_embedding_provider,
    cosine_similarity_matrix,
)


_DEFAULT_PROVIDER = object()


def tokenize(text: str) -> List[str]:
    """Simple lowercase alphanumeric word tokenizer."""
    return [w.lower() for w in re.findall(r"\b\w+\b", text) if len(w) > 0]


class SearchIndex:
    """Maintains BM25 + TF-IDF + Dense Vector hybrid index over log entries and leaf nodes."""

    # Default weights when dense vectors are not active
    _W_TFIDF = 0.60
    _W_BM25 = 0.40

    def __init__(self, embedding_provider: Any = _DEFAULT_PROVIDER):
        self.entry_docs: List[Dict[str, Any]] = []
        self.placement_table: Dict[str, str] = {}  # entry_id -> leaf_path
        self.node_docs: List[Dict[str, Any]] = []  # path, name, aliases, summary
        self.bm25_entries: Optional[BM25Okapi] = None
        self.bm25_nodes: Optional[BM25Okapi] = None
        # TF-IDF semantic layer
        self._tfidf_vectorizer: Optional[Any] = None  # TfidfVectorizer
        self._tfidf_matrix: Optional[Any] = None      # fitted sparse matrix
        # Dense vector embedding layer
        if embedding_provider is _DEFAULT_PROVIDER:
            self.embedding_provider: Optional[EmbeddingProvider] = get_embedding_provider()
        else:
            self.embedding_provider = embedding_provider
        self._node_embeddings: Optional[Any] = None   # np.ndarray [M, D]
        self._entry_embeddings: Optional[Any] = None  # np.ndarray [N, D]

    def build(
        self,
        log_entries: List[Dict[str, Any]],
        leaf_facts: List[Dict[str, str]],
        nodes: List[Dict[str, Any]],
    ) -> None:
        """Rebuild index completely from log entries, leaves, and nodes."""
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
            }
            self.entry_docs.append(doc_obj)
            toks = tokenize(full_text)
            tokenized_corpus.append(toks if toks else ["empty"])

        if tokenized_corpus:
            self.bm25_entries = BM25Okapi(tokenized_corpus)
        else:
            self.bm25_entries = None

        node_corpus: List[List[str]] = []
        node_texts: List[str] = []
        for n in self.node_docs:
            aliases_str = " ".join(n.get("aliases", []))
            node_text = f"{n.get('name', '')} {aliases_str} {n.get('summary', '')}"
            node_texts.append(node_text)
            toks = tokenize(node_text)
            node_corpus.append(toks if toks else ["empty"])

        if node_corpus:
            self.bm25_nodes = BM25Okapi(node_corpus)
        else:
            self.bm25_nodes = None

        # Fit TF-IDF vectorizer on node texts (bigrams, sublinear_tf)
        self._tfidf_vectorizer = None
        self._tfidf_matrix = None
        if _SKLEARN_AVAILABLE and node_texts and len(node_texts) >= 1:
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
                # Graceful degradation: fall back to BM25-only
                self._tfidf_vectorizer = None
                self._tfidf_matrix = None

        # Compute dense embeddings if provider is available
        self._node_embeddings = None
        self._entry_embeddings = None
        if self.embedding_provider is not None and _NUMPY_AVAILABLE:
            try:
                if node_texts:
                    self._node_embeddings = self.embedding_provider.embed_batch(node_texts)
            except Exception as e:
                logger.warning("Failed to compute node dense embeddings: %s", e)
                self._node_embeddings = None

            try:
                entry_texts = [f"{d['text']} {d.get('hint', '')}".strip() for d in self.entry_docs]
                if entry_texts:
                    self._entry_embeddings = self.embedding_provider.embed_batch(entry_texts)
            except Exception as e:
                logger.debug("Failed to compute entry dense embeddings: %s", e)
                self._entry_embeddings = None

    def add_entry(self, entry_id: str, fact: str, hint: str = "") -> None:
        """Add an entry to in-memory store."""
        doc_obj = {
            "entry_id": entry_id,
            "text": fact,
            "hint": hint,
            "path": self.placement_table.get(entry_id, "unplaced"),
        }
        self.entry_docs.append(doc_obj)
        if (
            self.embedding_provider is not None
            and self._entry_embeddings is not None
            and _NUMPY_AVAILABLE
        ):
            try:
                entry_vec = self.embedding_provider.embed_text(f"{fact} {hint}".strip())
                self._entry_embeddings = np.vstack([self._entry_embeddings, entry_vec])
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

        # 3. Dense vector cosine similarity scores
        dense_cos: List[float] = [0.0] * len(self.node_docs)
        has_dense = False
        if (
            self.embedding_provider is not None
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
