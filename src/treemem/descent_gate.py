"""Heuristic Descent Gate for TreeMem.

Evaluates whether a parent topic summary is sufficient to answer a query
(Parent-Stop), or whether the agent should descend into a specific child topic,
or fallback to search. Uses TF-IDF cosine similarity and lexical token overlap.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("treemem.gate")

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.warning(
        "scikit-learn is not installed; Heuristic Descent Gate falling back to lexical scoring. "
        "Install with `pip install 'treemem[gate]'` for TF-IDF semantic scoring."
    )


# Common query stopwords that dilute topical similarity
_STOPWORDS = {
    "what", "is", "the", "a", "an", "and", "or", "in", "on", "at", "of", "to",
    "for", "with", "does", "do", "did", "user", "users", "my", "your", "their",
    "her", "his", "where", "which", "who", "when", "how", "s", "currently",
}

# Semantic expansions for common interrogative query concepts (strictly generic)
_SYNONYM_MAP: Dict[str, List[str]] = {
    "profession": ["engineer", "software", "job", "career", "work", "developer", "title"],
    "job": ["engineer", "profession", "career", "work", "role", "position"],
    "career": ["engineer", "job", "profession", "work"],
    "name": ["identity", "profile", "user"],
    "who": ["identity", "profile", "user"],
    "city": ["location", "live", "reside", "address"],
    "location": ["city", "live", "reside", "based"],
    "reside": ["city", "live", "location"],
    "exercise": ["gym", "workout", "fitness", "cycling", "training", "sports"],
    "workout": ["gym", "exercise", "fitness", "cycling", "training"],
    "gym": ["exercise", "workout", "fitness", "training"],
    "fitness": ["exercise", "gym", "workout", "cycling", "health"],
    "project": ["projects", "repository", "code", "software", "development"],
    "college": ["education", "university", "coursework", "degree", "school"],
    "degree": ["education", "university", "coursework", "academic", "diploma"],
    "university": ["education", "college", "coursework", "academic"],
    "school": ["education", "university", "college", "coursework"],
    "education": ["university", "college", "coursework", "degree", "school"],
}


def tokenize(text: str) -> List[str]:
    """Simple lowercase alphanumeric word tokenizer."""
    return [w.lower() for w in re.findall(r"\b\w+\b", text) if len(w) > 0]


def expand_query(query: str) -> Tuple[List[str], str]:
    """Filter stopwords and expand core question tokens with domain synonyms."""
    raw_toks = tokenize(query)
    content_toks = [w for w in raw_toks if w not in _STOPWORDS]
    if not content_toks:
        content_toks = raw_toks

    expanded = list(content_toks)
    for tok in content_toks:
        if tok in _SYNONYM_MAP:
            expanded.extend(_SYNONYM_MAP[tok])

    return content_toks, " ".join(expanded)


class DescentGate:
    """Evaluates (query, parent_summary, children) to predict parent sufficiency."""

    def __init__(
        self,
        parent_stop_threshold: float = 0.25,
        descend_delta: float = 0.15,
    ):
        self.parent_stop_threshold = parent_stop_threshold
        self.descend_delta = descend_delta

    @staticmethod
    def _semantic_enabled() -> bool:
        """True when scikit-learn is importable (read at call time so tests can monkeypatch)."""
        return _SKLEARN_AVAILABLE

    def evaluate(
        self,
        query: str,
        parent_path: str,
        parent_summary: str,
        children: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Evaluate query against parent summary and child teasers.

        Returns:
            Dict containing:
              - action: 'stop' | 'descend' | 'search_fallback'
              - parent_sufficient: bool
              - confidence: float (0.0 to 1.0)
              - suggested_child: Optional[str]
              - hint: str explanation
            Or None if query is empty.
        """
        if not query or not query.strip():
            return None

        clean_query = query.strip()
        content_toks, expanded_q_str = expand_query(clean_query)
        if not content_toks:
            return None

        q_tokens = set(tokenize(expanded_q_str))
        child_list = children or []

        # Prepare corpus: [parent_text, child_1_text, child_2_text, ...]
        parent_text = f"{parent_path} {parent_summary}".strip()
        child_texts = [
            f"{c.get('label', '')} {c.get('teaser', '')}".strip()
            for c in child_list
        ]
        all_texts = [parent_text] + child_texts

        # 1. Lexical overlap score (token intersection / len(content_toks))
        lexical_scores = []
        c_set = set(content_toks)
        for text in all_texts:
            t_tokens = set(tokenize(text))
            # Direct content match gets strong weight
            c_overlap = len(c_set.intersection(t_tokens))
            e_overlap = len(q_tokens.intersection(t_tokens))
            score = (c_overlap * 2.0 + e_overlap * 0.5) / (len(c_set) * 2.0) if c_set else 0.0
            lexical_scores.append(min(1.0, score))

        # 2. Semantic TF-IDF bigram cosine similarity
        semantic_scores = [0.0] * len(all_texts)
        if self._semantic_enabled() and any(t for t in all_texts):
            try:
                vect = TfidfVectorizer(
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                    strip_accents="unicode",
                )
                matrix = vect.fit_transform(all_texts)
                q_vec = vect.transform([expanded_q_str])
                sims = cosine_similarity(q_vec, matrix)[0]
                semantic_scores = [float(s) for s in sims]
            except Exception:
                pass

        # Combined hybrid scores. With scikit-learn: 50% semantic + 50% lexical.
        # Without it the semantic score is always 0, so use 100% lexical weight;
        # otherwise every score is halved and thresholds become miscalibrated.
        if self._semantic_enabled():
            semantic_weight = 0.50
            lexical_weight = 0.50
        else:
            semantic_weight = 0.0
            lexical_weight = 1.0

        combined_scores = []
        for i in range(len(all_texts)):
            score = semantic_weight * semantic_scores[i] + lexical_weight * lexical_scores[i]
            combined_scores.append(score)

        parent_score = combined_scores[0]
        child_scores = combined_scores[1:]

        # Find best child match
        best_child_idx = -1
        best_child_score = 0.0
        best_child_label = None

        if child_scores:
            best_child_score = max(child_scores)
            best_child_idx = child_scores.index(best_child_score)
            best_child_label = child_list[best_child_idx].get("label")

        # Gating Decision Logic:
        # Case A: Parent is sufficiently strong
        if parent_score >= self.parent_stop_threshold:
            # Check if a child is significantly better (stronger drill-down)
            if best_child_score > parent_score + self.descend_delta and best_child_label:
                return {
                    "action": "descend",
                    "parent_sufficient": False,
                    "confidence": round(min(0.95, best_child_score), 2),
                    "suggested_child": best_child_label,
                    "hint": f"Child topic [[{best_child_label}]] appears more specific for this query.",
                    "parent_score": round(parent_score, 3),
                    "child_score": round(best_child_score, 3),
                }
            # Otherwise parent summary answers the topic directly -> Parent-Stop!
            return {
                "action": "stop",
                "parent_sufficient": True,
                "confidence": round(min(0.95, max(0.60, parent_score)), 2),
                "suggested_child": None,
                "hint": "Parent summary appears sufficient to answer query. Stop descent unless more detail needed.",
                "parent_score": round(parent_score, 3),
                "child_score": round(best_child_score, 3),
            }

        # Case B: Parent score is below threshold
        if best_child_score >= self.parent_stop_threshold and best_child_label:
            return {
                "action": "descend",
                "parent_sufficient": False,
                "confidence": round(min(0.95, best_child_score), 2),
                "suggested_child": best_child_label,
                "hint": f"Parent summary lacks details; child [[{best_child_label}]] matches query.",
                "parent_score": round(parent_score, 3),
                "child_score": round(best_child_score, 3),
            }

        # Case C: Neither parent nor child matches query
        return {
            "action": "search_fallback",
            "parent_sufficient": False,
            "confidence": 0.40,
            "suggested_child": None,
            "hint": "Neither parent nor child teasers strongly match query. Consider search tool.",
            "parent_score": round(parent_score, 3),
            "child_score": round(best_child_score, 3),
        }
