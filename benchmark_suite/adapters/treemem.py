"""TreeMem-backed retrieval adapters and vault construction."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from treemem.store import NodeData
from treemem.tokenizer import count_tokens
from treemem.tree_manager import TreeManager

from ..common import ROOT, atomic_write_json, json_dump
from ..schemas import MemoryRecord, QueryRecord
from .base import RetrievedItem, RetrievalResult, finalize_result, timer, elapsed_ms, tokens, visible_memories

WORD_RE = re.compile(r"\b\w+\b")


def qtokens(text: str) -> set[str]:
    return {t.lower() for t in WORD_RE.findall(text or "")}


def overlap_score(text: str, query: str) -> float:
    qt = qtokens(query)
    if not qt:
        return 0.0
    dt = qtokens(text)
    return len(qt & dt) / max(1, len(qt))


class TreeMemVault:
    """Builds and caches a TreeMem vault for a memory corpus."""

    def __init__(self, memories: Sequence[MemoryRecord], vault_root: Path, rebuild: bool = False):
        self.memories = list(memories)
        self.vault_root = Path(vault_root)
        self.mapping_path = self.vault_root.parent / "entry_map.json"
        self.meta_path = self.vault_root.parent / "vault_meta.json"
        self.entry_to_memory: Dict[str, str] = {}
        self.fact_to_memory: Dict[str, str] = {}
        self.manager: Optional[TreeManager] = None
        if not rebuild and self.vault_root.exists() and self.mapping_path.exists():
            try:
                self.entry_to_memory = json.loads(self.mapping_path.read_text())
                self.manager = TreeManager(self.vault_root)
                return
            except Exception:
                pass
        self._build()

    def _build(self) -> None:
        if self.vault_root.exists():
            shutil.rmtree(self.vault_root)
        self.vault_root.parent.mkdir(parents=True, exist_ok=True)
        mgr = TreeManager(self.vault_root)
        self.entry_to_memory = {}
        self.fact_to_memory = {}
        timings = {"remember_ms": 0.0, "place_ms": 0.0, "commit_ms": 0.0}
        for mem in self.memories:
            sensitivity = "private" if mem.sensitivity == "private" or mem.provenance.get("privacy_mode") in {"private", "inherited_private", "unplaced_private"} else "normal"
            # Unplaced private facts are logged but intentionally not placed.
            if mem.provenance.get("privacy_mode") == "unplaced_private":
                t0 = time.perf_counter()
                res = mgr.remember(fact=mem.content, hint=mem.category, session="benchmark", sensitivity=sensitivity)
                timings["remember_ms"] += (time.perf_counter() - t0) * 1000
                eid = res.get("entry_id") if isinstance(res, dict) else None
                if eid:
                    self.entry_to_memory[eid] = mem.memory_id
                    self.fact_to_memory[mem.content] = mem.memory_id
                continue
            t0 = time.perf_counter()
            res = mgr.remember(fact=mem.content, hint=mem.path, session="benchmark", sensitivity=sensitivity)
            timings["remember_ms"] += (time.perf_counter() - t0) * 1000
            eid = res.get("entry_id") if isinstance(res, dict) else None
            if not eid:
                continue
            self.entry_to_memory[eid] = mem.memory_id
            self.fact_to_memory[mem.content] = mem.memory_id
            t0 = time.perf_counter()
            mgr.place(entry_id=eid, path=mem.path, sensitivity=sensitivity, session="benchmark")
            timings["place_ms"] += (time.perf_counter() - t0) * 1000
        self._commit_summaries(mgr, timings)
        mgr.rebuild_index()
        self.manager = mgr
        json_dump(self.mapping_path, self.entry_to_memory)
        json_dump(self.meta_path, {"timings_ms": timings, "memory_count": len(self.memories), "vault": str(self.vault_root)})

    _STOP = {
        "the", "and", "for", "with", "that", "this", "from", "what", "when", "where",
        "which", "does", "user", "prefers", "uses", "has", "have", "are", "was",
    }

    @classmethod
    def _terms(cls, text: str, limit: int = 8) -> List[str]:
        from treemem.index import tokenize
        counts: Dict[str, int] = {}
        for tok in tokenize(text.lower()):
            if len(tok) < 4 or tok in cls._STOP or tok.isdigit():
                continue
            counts[tok] = counts.get(tok, 0) + 1
        return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]

    def _child_signal(self, mgr: TreeManager, child_path: str) -> str:
        node = mgr.store.read_node(child_path)
        if node is None:
            return ""
        if mgr.store.is_leaf(child_path):
            if mgr.is_private(child_path):
                return ""
            text = " ".join(f.get("fact", "") for f in node.facts[:3])
        else:
            text = node.summary or ""
        return " ".join(self._terms(text, 6))

    def _commit_summaries(self, mgr: TreeManager, timings: Dict[str, float]) -> None:
        """Deterministic bottom-up summaries with topical teasers."""
        paths = sorted(mgr.health_checker.get_all_node_paths(), key=lambda p: p.count("/"), reverse=True)
        for path in paths:
            node = mgr.store.read_node(path)
            if node is None or mgr.store.is_leaf(path):
                continue
            child_dirs = mgr.store.list_child_dirs(path)
            if not child_dirs:
                continue
            child_terms: Dict[str, str] = {}
            all_terms: List[str] = []
            lines = ["## Children"]
            for label in child_dirs:
                child_path = f"{path}/{label}" if path else label
                if mgr.is_private(child_path):
                    teaser = "contains private details"
                    signal = ""
                else:
                    signal = self._child_signal(mgr, child_path)
                    teaser = signal or f"Details on {label}"
                child_terms[label] = signal
                all_terms.extend(self._terms(signal, 4))
                lines.append(f"- [[{label}]] - {teaser}")
            top = ", ".join(dict.fromkeys(all_terms[:10])) or "mixed topics"
            summary = f"Topic '{node.name}' covers {top}.\n" + "\n".join(lines)
            t0 = time.perf_counter()
            res = mgr.commit_summary(path, summary, session="benchmark")
            timings["commit_ms"] += (time.perf_counter() - t0) * 1000
            if isinstance(res, dict) and res.get("ok") is False:
                minimal = "Topic summary.\n## Children\n" + "\n".join(f"- [[{c}]] - see node" for c in child_dirs)
                mgr.commit_summary(path, minimal, session="benchmark")

    def memory_for_entry(self, entry_id: Optional[str], text: Optional[str] = None) -> Optional[str]:
        if entry_id and entry_id in self.entry_to_memory:
            return self.entry_to_memory[entry_id]
        if text and text in self.fact_to_memory:
            return self.fact_to_memory[text]
        return None

    def memory_for_path(self, path: str) -> Optional[str]:
        # Leaf facts live in node.facts; find first matching entry.
        if not self.manager:
            return None
        node = self.manager.store.read_node(path)
        if not node:
            return None
        for fact in node.facts:
            mid = self.memory_for_entry(fact.get("entry_id"), fact.get("fact"))
            if mid:
                return mid
        return None


class TreeMemManualRetriever:
    """Deterministic manual traversal policy using recall/expand only.

    This is a benchmark-owned agent policy, not a claim about a specific LLM.
    It greedily follows the child teaser with the highest lexical overlap and
    expands the final leaf within a fixed tool-call budget.
    """

    name = "treemem_manual"

    def __init__(self, vault: TreeMemVault, max_steps: int = 8, expand_limit: int = 50):
        self.vault = vault
        self.max_steps = max_steps
        self.expand_limit = expand_limit

    def _collect_facts(self, path: str, reveal: bool) -> List[RetrievedItem]:
        mgr = self.vault.manager
        items: List[RetrievedItem] = []
        expanded = mgr.expand(path=path or "/", reveal=reveal)
        for rank, fact in enumerate((expanded.get("facts") or [])[: self.expand_limit], 1):
            text = fact.get("fact", "") if isinstance(fact, dict) else str(fact)
            mid = self.vault.memory_for_entry(fact.get("entry_id") if isinstance(fact, dict) else None, text)
            if mid:
                items.append(RetrievedItem(memory_id=mid, score=1.0 / rank, rank=rank, text=text, path=path, source=self.name))
        return items

    def retrieve(self, query: QueryRecord | str, k: int = 10, reveal: bool = False) -> RetrievalResult:
        start = timer()
        timings: Dict[str, float] = {}
        qid = query.query_id if isinstance(query, QueryRecord) else "adhoc"
        qtext = query.question if isinstance(query, QueryRecord) else str(query)
        mgr = self.vault.manager
        if mgr is None:
            return finalize_result(self.name, qid, [], timings, error="vault unavailable")
        path = ""
        visited = []
        tool_calls = 0
        expanded: Dict[str, Any] = {}
        for _ in range(self.max_steps):
            t0 = timer()
            expanded = mgr.expand(path=path or "/", reveal=reveal)
            timings["expand_ms"] = timings.get("expand_ms", 0.0) + elapsed_ms(t0)
            tool_calls += 1
            visited.append({"path": expanded.get("path"), "kind": "expand", "is_leaf": expanded.get("is_leaf")})
            if expanded.get("is_leaf") or expanded.get("withheld"):
                break
            children = expanded.get("children") or []
            scored = []
            for child in children:
                cpath = f"{path}/{child.get('label')}".strip("/") if path else child.get("label", "")
                text = f"{child.get('label','')} {child.get('teaser','')} {child.get('summary','')}"
                scored.append((overlap_score(text, qtext), cpath, child))
            scored = [s for s in scored if s[0] > 0 and not s[2].get("private")]
            if not scored:
                break
            _, path, _child = max(scored, key=lambda s: s[0])
        # If the step budget ended right after choosing a child, expand that child once.
        if path and (expanded.get("path") or "/") != (path or "/"):
            t0 = timer()
            expanded = mgr.expand(path=path, reveal=reveal)
            timings["expand_ms"] = timings.get("expand_ms", 0.0) + elapsed_ms(t0)
            tool_calls += 1
            visited.append({"path": expanded.get("path"), "kind": "expand", "is_leaf": expanded.get("is_leaf"), "final": True})
        items = self._collect_facts(path, reveal) if expanded.get("is_leaf") else []
        # If descent stalled at a non-leaf, inspect immediate leaf children only.
        if not items and expanded.get("children"):
            for child in expanded.get("children", [])[:k]:
                if child.get("private"):
                    continue
                cpath = f"{path}/{child.get('label')}".strip("/") if path else child.get("label", "")
                if mgr.store.is_leaf(cpath):
                    items.extend(self._collect_facts(cpath, reveal)[: max(1, k - len(items))])
                if len(items) >= k:
                    break
        meta = {"tool_calls": tool_calls, "visited": visited, "final_path": path, "max_steps": self.max_steps}
        return finalize_result(self.name, qid, items[:k], timings, meta)


class TreeMemGuidedRetriever:
    name = "treemem_guided"

    def __init__(self, vault: TreeMemVault, max_depth: int = 4, disable_fallback: bool = False):
        self.vault = vault
        self.max_depth = max_depth
        self.disable_fallback = disable_fallback
        if disable_fallback and vault.manager is not None:
            original_search = vault.manager.search
            def _no_fallback(*args, **kwargs):
                res = original_search(*args, **kwargs)
                if isinstance(res, dict):
                    res = dict(res)
                    res["hits"] = []
                    res["count"] = 0
                return res
            vault.manager.search = _no_fallback  # type: ignore[assignment]

    def retrieve(self, query: QueryRecord | str, k: int = 10, reveal: bool = False) -> RetrievalResult:
        start = timer()
        timings: Dict[str, float] = {}
        qid = query.query_id if isinstance(query, QueryRecord) else "adhoc"
        qtext = query.question if isinstance(query, QueryRecord) else str(query)
        mgr = self.vault.manager
        if mgr is None:
            return finalize_result(self.name, qid, [], timings, error="vault unavailable")
        t0 = timer()
        payload = mgr.recall(path="/", query=qtext, follow=True, max_depth=self.max_depth, reveal=reveal)
        timings["guided_ms"] = elapsed_ms(t0)
        items: List[RetrievedItem] = []
        seen = set()
        rank = 0
        # Leaf facts returned by guided descent.
        for fact in payload.get("facts", []) or []:
            text = fact.get("fact", "") if isinstance(fact, dict) else str(fact)
            mid = self.vault.memory_for_entry(fact.get("entry_id") if isinstance(fact, dict) else None, text)
            if mid and mid not in seen:
                seen.add(mid); rank += 1
                items.append(RetrievedItem(memory_id=mid, score=1.0 / rank, rank=rank, text=text, path=payload.get("path", ""), source=self.name))
        # Fallback search hits embedded in guided payload.
        search_result = payload.get("search") or payload.get("search_result") or payload.get("fallback") or {}
        hits = search_result.get("hits", []) if isinstance(search_result, dict) else []
        for hit in hits:
            mid = self.vault.memory_for_entry(hit.get("entry_id"), hit.get("text"))
            if mid and mid not in seen:
                seen.add(mid); rank += 1
                items.append(RetrievedItem(memory_id=mid, score=float(hit.get("score", 0.0)) or 1.0 / rank, rank=rank, text=hit.get("text", ""), path=hit.get("path", ""), source=self.name))
        # Include final summary as weak context item only if it maps to a known memory (rare).
        meta = {
            "stopped_reason": payload.get("stopped_reason"),
            "steps": payload.get("steps"),
            "traversal": payload.get("traversal"),
            "final_path": payload.get("path"),
            "withheld": payload.get("withheld", False),
            "disable_fallback": self.disable_fallback,
        }
        return finalize_result(self.name, qid, items[:k], timings, meta)


class TreeMemSearchRetriever:
    name = "treemem_search"

    def __init__(self, vault: TreeMemVault):
        self.vault = vault

    def retrieve(self, query: QueryRecord | str, k: int = 10, reveal: bool = False) -> RetrievalResult:
        start = timer()
        qid = query.query_id if isinstance(query, QueryRecord) else "adhoc"
        qtext = query.question if isinstance(query, QueryRecord) else str(query)
        mgr = self.vault.manager
        if mgr is None:
            return finalize_result(self.name, qid, [], {}, error="vault unavailable")
        t0 = timer()
        res = mgr.search(qtext, limit=k, reveal=reveal)
        elapsed = elapsed_ms(t0)
        items = []
        for rank, hit in enumerate(res.get("hits", []), 1):
            mid = self.vault.memory_for_entry(hit.get("entry_id"), hit.get("text"))
            if not mid:
                continue
            items.append(RetrievedItem(memory_id=mid, score=float(hit.get("score", 0.0)), rank=rank, text=hit.get("text", ""), path=hit.get("path", ""), source="treemem_search"))
        meta = {"withheld_private": res.get("withheld_private", 0), "withheld_unplaced": res.get("withheld_unplaced", 0), "count": res.get("count", 0)}
        return finalize_result(self.name, qid, items, {"search_ms": elapsed}, meta)


def build_arm(arm: str, memories: Sequence[MemoryRecord], vault: Optional[TreeMemVault], k: int = 10, config: Optional[Dict[str, Any]] = None) -> Any:
    config = config or {}
    if arm == "flat_all":
        from .lexical import FlatAllRetriever
        return FlatAllRetriever(memories)
    if arm == "bm25":
        from .lexical import BM25Retriever
        return BM25Retriever(memories)
    if arm == "dense":
        from .neural import DenseRetriever
        return DenseRetriever(memories, model=config.get("dense_model", "sentence-transformers/all-MiniLM-L6-v2"))
    if arm == "hybrid":
        from .neural import HybridRetriever
        return HybridRetriever(memories, dense_model=config.get("dense_model", "sentence-transformers/all-MiniLM-L6-v2"), rrf_k=config.get("rrf_k", 60))
    if arm == "hybrid_rerank":
        from .neural import HybridRerankRetriever
        return HybridRerankRetriever(memories, candidate_k=config.get("candidate_k", 50), rerank_k=k, dense_model=config.get("dense_model", "sentence-transformers/all-MiniLM-L6-v2"))
    if arm == "treemem_manual":
        if vault is None:
            raise ValueError("treemem_manual requires a vault")
        return TreeMemManualRetriever(vault, max_steps=config.get("manual_max_steps", 8))
    if arm == "treemem_guided":
        if vault is None:
            raise ValueError("treemem_guided requires a vault")
        return TreeMemGuidedRetriever(vault, max_depth=config.get("guided_max_depth", 4), disable_fallback=False)
    if arm == "treemem_guided_no_fallback":
        if vault is None:
            raise ValueError("treemem_guided_no_fallback requires a vault")
        return TreeMemGuidedRetriever(vault, max_depth=config.get("guided_max_depth", 4), disable_fallback=True)
    if arm == "treemem_search":
        if vault is None:
            raise ValueError("treemem_search requires a vault")
        return TreeMemSearchRetriever(vault)
    raise ValueError(f"unknown arm: {arm}")
