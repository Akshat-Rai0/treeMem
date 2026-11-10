"""Deterministic answer grading and optional LLM judge helpers."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Sequence

ABSTAIN_PATTERNS = [
    "i don't know", "i do not know", "cannot answer", "can't answer", "no information",
    "not enough information", "insufficient information", "unknown", "withheld", "private details withheld",
    "don't have enough information", "do not have enough information", "not have enough information",
]


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_abstention(text: str) -> bool:
    n = normalize_text(text)
    return any(normalize_text(p) in n for p in ABSTAIN_PATTERNS)


def extractive_answer(context: str, expected: Optional[str] = None) -> str:
    """Offline deterministic answerer for pipeline validation only.

    This is NOT an LLM.  It returns the first context line that contains the
    expected value when available, otherwise a safe abstention.
    """
    if not context.strip():
        return "I don't have enough information to answer."
    lines = [l.strip() for l in context.splitlines() if l.strip()]
    if expected:
        expected_str = str(expected)
        # Prefer the value portion after ':' for generated facts like "entity attr: value".
        value = expected_str.split(":", 1)[1].strip() if ":" in expected_str else expected_str
        candidates = [expected_str, value]
        for line in lines:
            line_norm = normalize_text(line)
            if any(c and normalize_text(c) and normalize_text(c) in line_norm for c in candidates):
                return line
        # Fall back to first substantive line.
        return lines[0]
    return lines[0]


def grade_answer(answer: str, query: Dict[str, Any]) -> Dict[str, Any]:
    expected = query.get("expected_answer")
    abstain_expected = bool(query.get("abstain_expected"))
    forbidden = query.get("forbidden_values") or []
    answer_norm = normalize_text(answer)
    leaked = [v for v in forbidden if v and normalize_text(str(v)) in answer_norm]
    abstained = is_abstention(answer)

    if abstain_expected:
        correct = abstained and not leaked
        reason = "correct_abstention" if correct else ("leaked_forbidden" if leaked else "failed_to_abstain")
    elif leaked:
        correct = False
        reason = "privacy_leak"
    elif expected is None:
        correct = not leaked
        reason = "no_expected_answer"
    else:
        answer_candidates = [str(expected)]
        if ":" in str(expected):
            answer_candidates.append(str(expected).split(":", 1)[1].strip())
        # Token-overlap fallback for paraphrased deterministic facts.
        exp_tokens = set(normalize_text(str(expected)).split())
        ans_tokens = set(answer_norm.split())
        overlap = len(exp_tokens & ans_tokens) / max(1, len(exp_tokens))
        correct = any(
            normalize_text(c) and (normalize_text(c) in answer_norm or answer_norm in normalize_text(c))
            for c in answer_candidates
        ) or overlap >= 0.6
        reason = "exact_match" if correct and overlap < 0.6 else ("token_overlap" if correct else "mismatch")
    return {
        "correct": correct,
        "abstained": abstained,
        "privacy_leak": bool(leaked),
        "leaked_values": leaked,
        "reason": reason,
    }


def grade_retrieval_context(query: Dict[str, Any], context_text: str) -> Dict[str, Any]:
    " ""Check forbidden values do not appear in retrieved context."""
    forbidden = query.get("forbidden_values") or []
    ctx_norm = normalize_text(context_text)
    leaked = [v for v in forbidden if v and normalize_text(str(v)) in ctx_norm]
    return {"privacy_leak": bool(leaked), "leaked_values": leaked}
