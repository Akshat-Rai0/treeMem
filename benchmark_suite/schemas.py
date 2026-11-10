"""Shared schemas and constants for benchmark_suite."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = "1.0.0"
GENERATOR_VERSION = "benchmark_suite_v1"
DEFAULT_SEED = 7
DEFAULT_SCALES = [100, 1000, 10000, 50000]
DEFAULT_QUERIES_PER_SCALE = 2000
QUERY_SPLITS = ("dev", "val", "test")
SPLIT_FRACTIONS = {"dev": 0.20, "val": 0.20, "test": 0.60}
QUERY_CATEGORIES = (
    "direct", "semantic", "multi_hop", "hierarchical", "broad", "temporal",
    "update", "ambiguous", "multi_entity", "negative", "private", "long_context",
)
PRIVACY_MODES = ("public", "private", "inherited_private", "unplaced_private")
RETRIEVAL_ARMS = (
    "flat_all", "bm25", "dense", "hybrid", "hybrid_rerank",
    "treemem_manual", "treemem_guided", "treemem_guided_no_fallback", "treemem_search",
)
METRIC_KS = (1, 3, 5, 10)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def jsonl_dump(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def jsonl_load(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def json_dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def json_load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def stratified_split(items: List[Dict[str, Any]], key: str = "category") -> Dict[str, List[Dict[str, Any]]]:
    """Deterministically assign dev/val/test while preserving category balance."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        buckets.setdefault(str(item.get(key, "unknown")), []).append(item)
    out = {"dev": [], "val": [], "test": []}
    for rows in buckets.values():
        for i, row in enumerate(rows):
            frac = (i + 1) / len(rows)
            if frac <= SPLIT_FRACTIONS["dev"]:
                split = "dev"
            elif frac <= SPLIT_FRACTIONS["dev"] + SPLIT_FRACTIONS["val"]:
                split = "val"
            else:
                split = "test"
            row = dict(row)
            row["split"] = split
            out[split].append(row)
    return out


@dataclass
class MemoryRecord:
    memory_id: str
    content: str
    category: str
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    sensitivity: str = "normal"
    path: str = "general"
    parent_path: str = ""
    children: List[str] = field(default_factory=list)
    related_memory_ids: List[str] = field(default_factory=list)
    revision_group: Optional[str] = None
    revision_version: Optional[int] = None
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    temporal_valid_from: Optional[str] = None
    temporal_valid_to: Optional[str] = None
    duplicate_group: Optional[str] = None
    contradiction_group: Optional[str] = None
    privacy_canary: Optional[str] = None
    source: str = "deterministic"
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "category": self.category,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "sensitivity": self.sensitivity,
            "path": self.path,
            "parent_path": self.parent_path,
            "children": self.children,
            "related_memory_ids": self.related_memory_ids,
            "revision_group": self.revision_group,
            "revision_version": self.revision_version,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "temporal_valid_from": self.temporal_valid_from,
            "temporal_valid_to": self.temporal_valid_to,
            "duplicate_group": self.duplicate_group,
            "contradiction_group": self.contradiction_group,
            "privacy_canary": self.privacy_canary,
            "source": self.source,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class QueryRecord:
    query_id: str
    question: str
    category: str
    split: str
    expected_answer: Optional[str] = None
    relevant_memory_ids: List[str] = field(default_factory=list)
    graded_relevance: Dict[str, float] = field(default_factory=dict)
    expected_path: Optional[str] = None
    abstain_expected: bool = False
    privacy_expected: str = "public"
    temporal_expected_version: Optional[int] = None
    forbidden_values: List[str] = field(default_factory=list)
    difficulty: str = "medium"
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "question": self.question,
            "category": self.category,
            "split": self.split,
            "expected_answer": self.expected_answer,
            "relevant_memory_ids": self.relevant_memory_ids,
            "graded_relevance": self.graded_relevance,
            "expected_path": self.expected_path,
            "abstain_expected": self.abstain_expected,
            "privacy_expected": self.privacy_expected,
            "temporal_expected_version": self.temporal_expected_version,
            "forbidden_values": self.forbidden_values,
            "difficulty": self.difficulty,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QueryRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


AREAS = [
    "work", "home", "travel", "health", "finance", "learning",
    "creative", "family", "career", "research",
]

_CATEGORY_SLUGS = {
    "personal": "personal", "preferences": "preferences", "technical": "technical",
    "projects": "projects", "history": "history", "events": "events",
    "entities": "entities", "relationships": "relationships", "finance": "finance",
    "mixed": "mixed", "private": "private",
}


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "general"


def _area_for_topic(topic: Any) -> str:
    if not topic:
        return "general"
    digest = int(sha256_text(str(topic))[:8], 16)
    return AREAS[digest % len(AREAS)]


def memory_path_for(category: str, index: int, rng_state: Any, fields: Optional[Dict[str, Any]] = None) -> str:
    """Deterministic topical path with bounded branching and depth.

    Root children are the ten benchmark areas plus ``private`` and ``general``
    (12 total, matching TreeMem's default ``children_cap``).  Deeper levels are
    category, entity bucket, and fact bucket; summaries/teasers carry content
    terms so guided and manual traversal have topical signal.
    """
    fields = fields or {}
    if category == "private":
        return f"private/secrets/entity_{index % 12}/facts_{(index // 12) % 12}"
    area = _area_for_topic(fields.get("topic"))
    cat = _CATEGORY_SLUGS.get(category, _slug(category))
    entity = index % 12
    facts = (index // 12) % 12
    return f"{area}/{cat}/entity_{entity}/facts_{facts}"
