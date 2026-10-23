"""BM25 search index over log entries, leaves, and candidate scoring."""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from rank_bm25 import BM25Okapi


def tokenize(text: str) -> List[str]:
    """Simple lowercase alphanumeric word tokenizer."""
    return [w.lower() for w in re.findall(r"\b\w+\b", text) if len(w) > 0]


class SearchIndex:
    """Maintains BM25 index over log entries and leaf nodes with placement mapping."""

    def __init__(self):
        self.entry_docs: List[Dict[str, Any]] = []
        self.placement_table: Dict[str, str] = {}  # entry_id -> leaf_path
        self.node_docs: List[Dict[str, Any]] = []  # path, name, aliases, summary
        self.bm25_entries: Optional[BM25Okapi] = None
        self.bm25_nodes: Optional[BM25Okapi] = None

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
        for n in self.node_docs:
            aliases_str = " ".join(n.get("aliases", []))
            node_text = f"{n.get('name', '')} {aliases_str} {n.get('summary', '')}"
            toks = tokenize(node_text)
            node_corpus.append(toks if toks else ["empty"])

        if node_corpus:
            self.bm25_nodes = BM25Okapi(node_corpus)
        else:
            self.bm25_nodes = None

    def add_entry(self, entry_id: str, fact: str, hint: str = "") -> None:
        """Add an entry to in-memory store."""
        doc_obj = {
            "entry_id": entry_id,
            "text": fact,
            "hint": hint,
            "path": self.placement_table.get(entry_id, "unplaced"),
        }
        self.entry_docs.append(doc_obj)

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
        """Propose candidate nodes for placing a fact."""
        candidates: List[Dict[str, Any]] = []
        seen_paths: Set[str] = set()

        clean_hint = hint.strip().strip("/")
        if clean_hint and all_node_paths and clean_hint in all_node_paths:
            candidates.append({"path": clean_hint, "score": 1.0})
            seen_paths.add(clean_hint)

        query_text = f"{fact} {hint}"
        toks = tokenize(query_text)
        query_words = set(toks)

        if self.node_docs:
            ranked_nodes: List[Tuple[Dict[str, Any], float]] = []
            for n in self.node_docs:
                p = n["path"]
                if p in seen_paths:
                    continue
                node_text = f"{n.get('name', '')} {' '.join(n.get('aliases', []))} {n.get('summary', '')}".lower()
                node_toks = set(tokenize(node_text))
                overlap = query_words.intersection(node_toks)
                if overlap:
                    ranked_nodes.append((n, float(len(overlap))))

            ranked_nodes.sort(key=lambda x: x[1], reverse=True)
            for node, s in ranked_nodes:
                p = node["path"]
                candidates.append({"path": p, "score": round(min(1.0, s / 5.0), 3)})
                seen_paths.add(p)
                if len(candidates) >= limit:
                    break

        return candidates[:limit]
