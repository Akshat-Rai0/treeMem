"""Budget-constrained context packing for equal-budget retrieval comparisons.

Every retriever arm is reduced to an ordered list of context units (text +
memory ids). ``pack_to_budget`` greedily includes units in order while they
fit inside a strict token budget, truncating a single oversized unit to the
remaining budget and never exceeding it. Recall is then measured on the memory
ids that actually fit — the "knapsack" view of context efficiency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from treemem.tokenizer import count_tokens

from .adapters.base import RetrievalResult

PACKER_VERSION = "budget_packer_v1"
# Units are only added while at least this many tokens remain; below it no
# memory text can be usefully included, so packing stops early.
MIN_UNIT_TOKENS = 8
# Separator cost charged per packed unit so the rendered context text stays
# within budget even after "\n\n" joins.
SEP_TOKENS = count_tokens("\n\n")


def _encoder():
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


_ENCODER = _encoder()


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Return a prefix of ``text`` whose token count is <= ``max_tokens``."""
    if max_tokens <= 0 or not text:
        return ""
    if _ENCODER is not None:
        try:
            ids = _ENCODER.encode(text)
            if len(ids) <= max_tokens:
                return text
            out = _ENCODER.decode(ids[:max_tokens])
            # Guard against rare decode/re-encode drift.
            while out and count_tokens(out) > max_tokens:
                ids = ids[: max(0, len(ids) - 1)]
                out = _ENCODER.decode(ids) if ids else ""
            return out
        except Exception:
            pass
    words = text.split()
    while words and count_tokens(" ".join(words)) > max_tokens:
        words.pop()
    return " ".join(words)


@dataclass
class ContextUnit:
    text: str
    memory_ids: List[str] = field(default_factory=list)
    kind: str = "memory"  # memory | preamble | fact | search_hit
    tokens: int = 0
    truncated: bool = False

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = count_tokens(self.text)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "memory_ids": list(self.memory_ids),
            "kind": self.kind,
            "tokens": self.tokens,
            "truncated": self.truncated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextUnit":
        return cls(
            text=data.get("text", ""),
            memory_ids=list(data.get("memory_ids") or []),
            kind=data.get("kind", "memory"),
            tokens=int(data.get("tokens") or 0),
            truncated=bool(data.get("truncated", False)),
        )


@dataclass
class PackedContext:
    units: List[ContextUnit]
    context_text: str
    tokens_used: int
    budget: int
    units_included: int
    units_dropped: int
    truncated_count: int

    @property
    def packed_memory_ids(self) -> List[str]:
        ids: List[str] = []
        for u in self.units:
            ids.extend(u.memory_ids)
        return ids

    def to_dict(self) -> Dict[str, Any]:
        return {
            "budget": self.budget,
            "tokens_used": self.tokens_used,
            "utilization": (self.tokens_used / self.budget) if self.budget else 0.0,
            "units_included": self.units_included,
            "units_dropped": self.units_dropped,
            "truncated_count": self.truncated_count,
            "packed_memory_ids": self.packed_memory_ids,
            "context_text": self.context_text,
        }


def pack_to_budget(units: Sequence[ContextUnit], budget: int) -> PackedContext:
    """Greedily pack units under ``budget`` tokens.

    Units that carry retrievable memory ids are packed first in their given
    order, then units with no memory ids (e.g. TreeMem's navigational
    preamble) fill any leftover budget. This applies uniformly to every arm
    and prevents zero-evidence context from crowding out retrievable content
    — the packer maximizes recall@budget, the quantity under comparison.

    A unit is included whole when it fits in the remaining budget. When it does
    not fit but at least ``MIN_UNIT_TOKENS`` remain, the unit text is truncated
    to the remaining budget (recorded via ``truncated=True``). ``tokens_used``
    never exceeds ``budget``.
    """
    budget = max(0, int(budget))
    ordered = [u for u in units if u.memory_ids] + [u for u in units if not u.memory_ids]
    remaining = budget
    packed: List[ContextUnit] = []
    dropped = 0
    truncated_count = 0
    for unit in ordered:
        cost = unit.tokens + SEP_TOKENS
        if cost <= remaining:
            packed.append(unit)
            remaining -= cost
            continue
        # Does not fit whole: only truncation can still use the remainder.
        room = remaining - SEP_TOKENS
        if room >= MIN_UNIT_TOKENS:
            text = truncate_to_tokens(unit.text, room)
            tok = count_tokens(text)
            if 0 < tok <= room:
                packed.append(ContextUnit(
                    text=text, memory_ids=list(unit.memory_ids), kind=unit.kind,
                    tokens=tok, truncated=True,
                ))
                remaining -= tok + SEP_TOKENS
                truncated_count += 1
                continue
        dropped += 1
    context_text = "\n\n".join(u.text for u in packed if u.text)
    rendered = count_tokens(context_text) if context_text else 0
    # Each packed unit was charged tokens + SEP_TOKENS against the budget, so
    # the accounted cost is always <= budget. Report the true rendered count
    # whenever it fits; fall back to the accounted cost on boundary drift.
    accounted = sum(u.tokens + SEP_TOKENS for u in packed)
    tokens_used = rendered if rendered <= budget else accounted
    return PackedContext(
        units=packed,
        context_text=context_text,
        tokens_used=min(tokens_used, budget),
        budget=budget,
        units_included=len(packed),
        units_dropped=dropped,
        truncated_count=truncated_count,
    )


def units_from_result(result: RetrievalResult, unit_cap: Optional[int] = None) -> List[ContextUnit]:
    """Derive ordered context units from a retrieval result.

    Guided TreeMem results carry ``metadata["budget_units"]`` (preamble +
    facts + search hits in arrival order). All other arms fall back to one
    unit per retrieved item in rank order. ``unit_cap`` bounds the number of
    units considered (protects against corpus-order arms like ``flat_all``).
    """
    meta_units = (result.metadata or {}).get("budget_units")
    if meta_units:
        units = [ContextUnit.from_dict(u) for u in meta_units]
    else:
        units = [
            ContextUnit(text=item.text, memory_ids=[item.memory_id] if item.memory_id else [], kind="memory")
            for item in result.items
        ]
    if unit_cap is not None:
        units = units[:unit_cap]
    return units
