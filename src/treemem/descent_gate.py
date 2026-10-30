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


# Plain English function words (pronouns, auxiliaries, question words). Only used when better_tokens=True.
_EXTRA_STOPWORDS = {
    "he", "she", "him", "it", "its", "they", "them", "i", "me", "we", "you", "our", "this", "that",
    "these", "those", "there", "here", "be", "been", "being", "am", "are", "was", "were", "has", "have",
    "had", "having", "can", "could", "would", "should", "will", "shall", "may", "might", "must",
    "about", "from", "by", "as", "into", "than", "then", "so", "if", "any", "some", "ever", "also",
    "many", "much", "often", "long", "now", "right", "currently", "kind", "type", "tell", "me",
    "whom", "whose", "why", "not", "no", "yes", "his", "hers", "own",
}


def stem(token: str) -> str:
    """Very light suffix stripping so 'projects' matches 'project' and 'languages' matches 'language'.

    Deliberately simple and generic: no vocabulary, no dictionary.
    """
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es") and token[-3] in "sxz":
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def query_word_groups(query: str, normalize: bool = False) -> List[Tuple[str, set]]:
    """One entry per content word of the question: (the word itself, its generic synonyms).

    Matching the word itself is stronger evidence than matching a synonym, so callers can weight them.
    """
    raw_toks = [w.lower() for w in re.findall(r"\b\w+\b", query)]
    stopwords = _STOPWORDS | _EXTRA_STOPWORDS if normalize else _STOPWORDS
    kept = [w for w in raw_toks if w not in stopwords]
    if not kept:
        kept = raw_toks
    groups: List[Tuple[str, set]] = []
    for word in kept:
        synonyms = list(_SYNONYM_MAP.get(word, []))
        if normalize:
            groups.append((stem(word), {stem(m) for m in synonyms}))
        else:
            groups.append((word, set(synonyms)))
    return groups


def tokenize(text: str, normalize: bool = False) -> List[str]:
    """Lowercase alphanumeric word tokenizer. normalize=True also stems each token."""
    words = [w.lower() for w in re.findall(r"\b\w+\b", text) if len(w) > 0]
    if normalize:
        return [stem(w) for w in words]
    return words


def expand_query(query: str, normalize: bool = False) -> Tuple[List[str], str]:
    """Filter stopwords and expand core question tokens with domain synonyms."""
    raw_toks = [w.lower() for w in re.findall(r"\b\w+\b", query)]
    stopwords = _STOPWORDS | _EXTRA_STOPWORDS if normalize else _STOPWORDS
    kept = [w for w in raw_toks if w not in stopwords]
    if not kept:
        kept = raw_toks

    expanded = list(kept)
    for tok in kept:
        if tok in _SYNONYM_MAP:
            expanded.extend(_SYNONYM_MAP[tok])

    if normalize:
        content_toks = [stem(w) for w in kept]
        expanded_str = " ".join(stem(w) for w in expanded)
        return content_toks, expanded_str
    return kept, " ".join(expanded)


class DescentGate:
    """Evaluates (query, parent_summary, children) to predict parent sufficiency."""

    def __init__(
        self,
        parent_stop_threshold: float = 0.25,
        descend_delta: float = 0.15,
        better_tokens: bool = True,
        min_stop_coverage: float = 0.5,
        specific_term_tiebreak: bool = True,
        tiebreak_margin: float = 0.05,
        descend_floor: float = 0.15,
        descend_ratio: float = 0.3,
    ):
        """
        parent_stop_threshold: minimum parent score for the parent to count as an answer.
        descend_delta: a child must beat the parent by this much to be preferred outright.
        better_tokens: stem words and drop plain English function words (pronouns, auxiliaries).
        min_stop_coverage: the parent text must contain at least this fraction of the question's
            content words before "stop" is allowed. 0.0 turns the check off.
        specific_term_tiebreak: if a child contains a question word the parent lacks and scores
            about as well as the parent, descend instead of stopping.
        tiebreak_margin: how far below the parent a child may score and still win the tie-break.
        descend_floor: minimum child score for descending when the parent is not sufficient.
        descend_ratio: in guided descent an extra step costs nothing but a wrong stop costs correctness,
            so (only when eager_descent is set) descend when the best child scores at least this fraction of the parent (0.0 = off). The default 0.3 sits in the middle of a plateau (0.2 to 0.4) where results do not change.
        """
        self.parent_stop_threshold = parent_stop_threshold
        self.descend_delta = descend_delta
        self.better_tokens = better_tokens
        self.min_stop_coverage = min_stop_coverage
        self.specific_term_tiebreak = specific_term_tiebreak
        self.tiebreak_margin = tiebreak_margin
        self.descend_floor = descend_floor
        self.descend_ratio = descend_ratio

    @classmethod
    def legacy(cls) -> "DescentGate":
        """The gate as it behaved before the premature-stop fix (for offline comparison)."""
        return cls(
            better_tokens=False,
            min_stop_coverage=0.0,
            specific_term_tiebreak=False,
            descend_floor=0.25,
            descend_ratio=0.0,
        )

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
        eager_descent: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Evaluate query against parent summary and child teasers.

        eager_descent: True during guided descent (recall with follow=True), where an extra
            server-side step is nearly free. It enables the descend_ratio rule. In manual mode
            every extra step is a tool call the agent pays for, so the rule stays off.

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
        content_toks, expanded_q_str = expand_query(clean_query, normalize=self.better_tokens)
        if not content_toks:
            return None

        q_tokens = set(tokenize(expanded_q_str, normalize=self.better_tokens))
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
            t_tokens = set(tokenize(text, normalize=self.better_tokens))
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

        # How well does each text cover the question's own words? A literal match counts 1.0,
        # a match on a generic synonym counts 0.5 (weaker evidence), no match counts 0.
        groups = query_word_groups(clean_query, normalize=self.better_tokens)
        parent_words = set(tokenize(parent_text, normalize=self.better_tokens))

        def cover_value(word: str, synonyms: set, words: set) -> float:
            if word in words:
                return 1.0
            if synonyms & words:
                return 0.5
            return 0.0

        parent_cover_values = [cover_value(word, syns, parent_words) for word, syns in groups]
        parent_coverage = (sum(parent_cover_values) / len(groups)) if groups else 0.0

        # Question words the best child matches literally but the parent matches only weakly or not at all.
        child_extra_terms = 0
        if best_child_idx >= 0:
            best_child_words = set(tokenize(child_texts[best_child_idx], normalize=self.better_tokens))
            for index, (word, _syns) in enumerate(groups):
                if word in best_child_words and parent_cover_values[index] < 1.0:
                    child_extra_terms += 1

        scores = {
            "parent_score": round(parent_score, 3),
            "child_score": round(best_child_score, 3),
            "parent_coverage": round(parent_coverage, 3),
        }

        parent_strong = parent_score >= self.parent_stop_threshold
        parent_covers = parent_coverage >= self.min_stop_coverage
        parent_sufficient = parent_strong and parent_covers

        # Case A: the parent looks sufficient.
        if parent_sufficient:
            child_clearly_better = best_child_score > parent_score + self.descend_delta
            child_close_enough = (
                eager_descent
                and self.descend_ratio > 0.0
                and best_child_score >= self.descend_floor
                and parent_score > 0.0
                and best_child_score >= self.descend_ratio * parent_score
            )
            child_ties_with_new_term = (
                self.specific_term_tiebreak
                and child_extra_terms > 0
                and best_child_score >= parent_score - self.tiebreak_margin
            )
            if best_child_label and (child_clearly_better or child_ties_with_new_term or child_close_enough):
                if child_clearly_better:
                    reason = f"Child topic [[{best_child_label}]] appears more specific for this query."
                elif child_ties_with_new_term:
                    reason = f"Child topic [[{best_child_label}]] contains question words the parent summary lacks."
                else:
                    reason = f"Child topic [[{best_child_label}]] is a close match; descending is cheap and avoids a wrong stop."
                return {
                    "action": "descend",
                    "parent_sufficient": False,
                    "confidence": round(min(0.95, best_child_score), 2),
                    "suggested_child": best_child_label,
                    "hint": reason,
                    **scores,
                }
            return {
                "action": "stop",
                "parent_sufficient": True,
                "confidence": round(min(0.95, max(0.60, parent_score)), 2),
                "suggested_child": None,
                "hint": "Parent summary appears sufficient to answer query. Stop descent unless more detail needed.",
                **scores,
            }

        # Case B: the parent is not sufficient (weak match, or it misses most of the question's words).
        if best_child_label and best_child_score >= self.descend_floor:
            return {
                "action": "descend",
                "parent_sufficient": False,
                "confidence": round(min(0.95, best_child_score), 2),
                "suggested_child": best_child_label,
                "hint": f"Parent summary lacks details; child [[{best_child_label}]] matches query.",
                **scores,
            }

        # Case C: neither the parent nor any child matches.
        return {
            "action": "search_fallback",
            "parent_sufficient": False,
            "confidence": 0.40,
            "suggested_child": None,
            "hint": "Neither parent nor child teasers strongly match query. Consider search tool.",
            **scores,
        }
