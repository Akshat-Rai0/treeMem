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


def gate_overlap_score(text: str, query: str) -> float:
    """Gate-style coverage: literal question words count 1.0, synonyms 0.5."""
    from treemem.descent_gate import query_word_groups, tokenize as gate_tokenize
    groups = query_word_groups(query, normalize=True)
    if not groups:
        return 0.0
    words = set(gate_tokenize((text or "").lower(), normalize=True))
    total = 0.0
    for word, synonyms in groups:
        if word in words:
            total += 1.0
        elif synonyms & words:
            total += 0.5
    return total / len(groups)


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
        # Order memories so supersession targets are written before their
        # successors — remember(supersedes=) needs the target's entry_id.
        ordered = self._dependency_order(self.memories)
        memory_entry: Dict[str, str] = {}
        for mem in ordered:
            sensitivity = "private" if mem.sensitivity == "private" or mem.provenance.get("privacy_mode") in {"private", "inherited_private", "unplaced_private"} else "normal"
            sup_entry = memory_entry.get(mem.supersedes) if getattr(mem, "supersedes", None) else None
            vf = getattr(mem, "temporal_valid_from", None) or ""
            vt = getattr(mem, "temporal_valid_to", None) or ""
            # Unplaced private facts are logged but intentionally not placed.
            if mem.provenance.get("privacy_mode") == "unplaced_private":
                t0 = time.perf_counter()
                res = mgr.remember(fact=mem.content, hint=mem.category, session="benchmark", sensitivity=sensitivity,
                                   supersedes=sup_entry or "", valid_from=vf, valid_to=vt)
                timings["remember_ms"] += (time.perf_counter() - t0) * 1000
                eid = res.get("entry_id") if isinstance(res, dict) else None
                if eid:
                    self.entry_to_memory[eid] = mem.memory_id
                    self.fact_to_memory[mem.content] = mem.memory_id
                    memory_entry[mem.memory_id] = eid
                continue
            t0 = time.perf_counter()
            res = mgr.remember(fact=mem.content, hint=mem.path, session="benchmark", sensitivity=sensitivity,
                               supersedes=sup_entry or "", valid_from=vf, valid_to=vt)
            timings["remember_ms"] += (time.perf_counter() - t0) * 1000
            eid = res.get("entry_id") if isinstance(res, dict) else None
            if not eid:
                continue
            self.entry_to_memory[eid] = mem.memory_id
            self.fact_to_memory[mem.content] = mem.memory_id
            memory_entry[mem.memory_id] = eid
            t0 = time.perf_counter()
            mgr.place(entry_id=eid, path=mem.path, sensitivity=sensitivity, session="benchmark")
            timings["place_ms"] += (time.perf_counter() - t0) * 1000
        self._commit_summaries(mgr, timings)
        mgr.rebuild_index()
        self.manager = mgr
        json_dump(self.mapping_path, self.entry_to_memory)
        json_dump(self.meta_path, {"timings_ms": timings, "memory_count": len(self.memories), "vault": str(self.vault_root)})

    @staticmethod
    def _dependency_order(memories: Sequence[MemoryRecord]) -> List[MemoryRecord]:
        """Order memories so supersedes targets are remembered before successors."""
        by_id = {m.memory_id: m for m in memories}
        pending = list(memories)
        pending_ids = {m.memory_id for m in pending}
        ordered: List[MemoryRecord] = []
        while pending:
            progressed = False
            for mem in list(pending):
                target_id = getattr(mem, "supersedes", None)
                if target_id and target_id in pending_ids:
                    continue
                ordered.append(mem)
                pending.remove(mem)
                pending_ids.discard(mem.memory_id)
                progressed = True
            if not progressed:  # cycle — write remaining in original order
                ordered.extend(pending)
                break
        return ordered

    _STOP = {
        "the", "and", "for", "with", "that", "this", "from", "what", "when", "where",
        "which", "does", "user", "prefers", "uses", "has", "have", "are", "was",
        # Template words that appear in every generated summary/teaser and would
        # otherwise dominate term extraction ("Topic 'x' covers ...").
        "topic", "covers", "cover", "placeholder", "summary", "summaries",
        "details", "detail", "subtopic", "mixed", "see", "node",
        # Conversational/function words common in dialogue corpora.
        "yeah", "okay", "ok", "oh", "um", "uh", "like", "know", "think", "going",
        "gonna", "want", "really", "very", "just", "also", "maybe", "right", "sure",
        "well", "hi", "hello", "bye", "thanks", "thank", "yes", "no", "not", "dont",
        "didnt", "im", "ive", "ill", "youre", "its", "thats", "theres", "whats", "lets",
        "got", "get", "make", "made", "lot", "lots", "kind", "sort", "thing", "things",
        "way", "people", "person", "time", "day", "today", "yesterday", "tomorrow",
        "now", "currently", "still", "again", "much", "many", "something", "anything",
        "everything", "nothing", "someone", "anyone", "everyone", "nobody", "would",
        "could", "should", "about", "into", "over", "after", "before", "because",
    }

    @classmethod
    def _terms(cls, text: str, limit: int = 8) -> List[str]:
        from treemem.descent_gate import tokenize as gate_tokenize
        counts: Dict[str, int] = {}
        for tok in gate_tokenize(text.lower(), normalize=True):
            if len(tok) < 3 or tok in cls._STOP or tok.isdigit():
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
            # Use the whole leaf, not just the first few facts: session leaves in
            # conversational corpora contain many turns and the answer may be late.
            text = " ".join(f.get("fact", "") for f in node.facts[:200])
            return " ".join(self._terms(text, 12))
        text = node.summary or ""
        return " ".join(self._terms(text, 8))

    def _commit_summaries(self, mgr: TreeManager, timings: Dict[str, float]) -> None:
        """Deterministic bottom-up summaries with topical teasers.

        Ordering matters: deepest nodes first, and the root LAST. Root and
        top-level areas share depth 0, so a plain depth sort can process the
        root before its children — capturing their pre-commit "Placeholder
        summary for X" text in teasers instead of real topical terms.
        """
        paths = sorted(
            mgr.health_checker.get_all_node_paths(),
            key=lambda p: (p.count("/"), p != ""),
            reverse=True,
        )
        leaf_paths = [p for p in paths if mgr.store.is_leaf(p)]
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
                all_terms.extend(self._terms(signal, 6))
                lines.append(f"- [[{label}]] - {teaser}")
            top = ", ".join(dict.fromkeys(all_terms[:14])) or "mixed topics"
            summary = f"Topic '{node.name}' covers {top}.\n" + "\n".join(lines)
            t0 = time.perf_counter()
            res = mgr.commit_summary(path, summary, session="benchmark")
            timings["commit_ms"] += (time.perf_counter() - t0) * 1000
            if isinstance(res, dict) and res.get("ok") is False:
                minimal = "Topic summary.\n## Children\n" + "\n".join(f"- [[{c}]] - see node" for c in child_dirs)
                mgr.commit_summary(path, minimal, session="benchmark")
        # Leaves are skipped above (their content is the facts themselves), but
        # place() leaves them dirty forever — producing hundreds of invariant-6
        # "clean parent has dirty descendants" violations. Mark them clean so
        # the vault health report reflects a fully summarized tree.
        for path in leaf_paths:
            node = mgr.store.read_node(path)
            if node is not None and node.dirty:
                node.dirty = False
                mgr.store.write_node_atomic(path, node)

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
                scored.append((gate_overlap_score(text, qtext), cpath, child))
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

    def __init__(self, vault: TreeMemVault, max_depth: int = 4, disable_fallback: bool = False,
                 global_search_limit: int = 0, name: Optional[str] = None):
        self.vault = vault
        self.max_depth = max_depth
        self.disable_fallback = disable_fallback
        # When >0, always union the guided payload with a bounded GLOBAL
        # search over the whole vault (the reviewer's parent-bypass idea):
        # hierarchy first, global lexical hits fill whatever budget remains.
        self.global_search_limit = max(0, int(global_search_limit))
        if name:
            self.name = name
        # NOTE: disable_fallback is applied post-hoc in retrieve() by ignoring
        # payload search hits. It must NOT monkeypatch vault.manager.search —
        # the manager is shared with other arms (treemem_search, guided) and
        # mutating it poisoned their results in earlier benchmark runs.

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
        fallback_hits_suppressed = 0
        if self.disable_fallback:
            fallback_hits_suppressed = len(hits)
            hits = []
        for hit in hits:
            mid = self.vault.memory_for_entry(hit.get("entry_id"), hit.get("text"))
            if mid and mid not in seen:
                seen.add(mid); rank += 1
                items.append(RetrievedItem(memory_id=mid, score=float(hit.get("score", 0.0)) or 1.0 / rank, rank=rank, text=hit.get("text", ""), path=hit.get("path", ""), source=self.name))
        global_hits = 0
        if self.global_search_limit > 0:
            try:
                gres = mgr.search(qtext, limit=self.global_search_limit, reveal=reveal)
            except Exception:
                gres = {}
            for hit in (gres.get("hits") or []):
                text = hit.get("text") or hit.get("fact") or ""
                mid = self.vault.memory_for_entry(hit.get("entry_id"), text)
                if mid and mid not in seen:
                    seen.add(mid); rank += 1
                    global_hits += 1
                    items.append(RetrievedItem(memory_id=mid, score=float(hit.get("score") or 0.0), rank=rank, text=text, path=hit.get("path"), source=f"{self.name}:global"))
        # Include final summary as weak context item only if it maps to a known memory (rare).
        meta = {
            "stopped_reason": payload.get("stopped_reason"),
            "steps": payload.get("steps"),
            "traversal": payload.get("traversal"),
            "final_path": payload.get("path"),
            "withheld": payload.get("withheld", False),
            "disable_fallback": self.disable_fallback,
            "fallback_hits_suppressed": fallback_hits_suppressed,
            "global_search_limit": self.global_search_limit,
            "global_hits": global_hits,
            "payload_tokens_final": payload.get("tokens"),
        }
        meta["budget_units"] = self._budget_units(payload, suppress_fallback=self.disable_fallback,
                                                  global_result=gres if self.global_search_limit > 0 else None)
        return finalize_result(self.name, qid, items[:k], timings, meta)

    def _budget_units(self, payload: Dict[str, Any], suppress_fallback: bool = False,
                      global_result: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Ordered context units matching what the guided payload returns.

        Order mirrors ``TreeManager._guided_recall`` token accounting: node
        summary + child teasers first, then leaf facts, then bounded search
        hits. Used by the budget-constrained experiment so the full returned
        payload (not just mapped facts) is charged against the token budget.
        """
        units: List[Dict[str, Any]] = []
        preamble_lines = [payload.get("summary", "") or ""]
        for child in payload.get("children", []) or []:
            preamble_lines.append(f"{child.get('label', '')}: {child.get('teaser', '')}")
        units.append({
            "text": "\n".join(preamble_lines),
            "memory_ids": [],
            "kind": "preamble",
        })
        for fact in payload.get("facts", []) or []:
            text = fact.get("fact", "") if isinstance(fact, dict) else str(fact)
            mid = self.vault.memory_for_entry(fact.get("entry_id") if isinstance(fact, dict) else None, text)
            units.append({"text": text, "memory_ids": [mid] if mid else [], "kind": "fact"})
        search_result = payload.get("search") or payload.get("search_result") or payload.get("fallback") or {}
        hits = search_result.get("hits", []) if isinstance(search_result, dict) else []
        if suppress_fallback:
            hits = []
        for hit in hits or []:
            mid = self.vault.memory_for_entry(hit.get("entry_id"), hit.get("text"))
            units.append({"text": hit.get("text", ""), "memory_ids": [mid] if mid else [], "kind": "search_hit"})
        if global_result:
            emitted = {mid for u in units for mid in u["memory_ids"]}
            for hit in global_result.get("hits") or []:
                text = hit.get("text") or hit.get("fact") or ""
                mid = self.vault.memory_for_entry(hit.get("entry_id"), text)
                if mid and mid in emitted:
                    continue
                if mid:
                    emitted.add(mid)
                units.append({"text": text, "memory_ids": [mid] if mid else [], "kind": "global_hit"})
        return units


class TreeMemBeamRetriever:
    """Beam-search TreeMem traversal over child teasers/summaries.

    Unlike guided descent (single suggested child), this keeps the top
    ``beam_width`` branches at each depth, reducing parent-level false
    negatives when a parent summary smooths over a rare detail.
    """

    name = "treemem_beam"

    def __init__(self, vault: TreeMemVault, beam_width: int = 6, max_depth: int = 4, expand_limit: int = 50):
        self.vault = vault
        self.beam_width = max(1, int(beam_width))
        self.max_depth = max(0, int(max_depth))
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
        qid = query.query_id if isinstance(query, QueryRecord) else "adhoc"
        qtext = query.question if isinstance(query, QueryRecord) else str(query)
        mgr = self.vault.manager
        if mgr is None:
            return finalize_result(self.name, qid, [], {}, error="vault unavailable")

        visited = {""}
        frontier = [("", 0)]
        collected: List[RetrievedItem] = []
        expansions = 0
        for depth in range(self.max_depth + 1):
            next_frontier: List[tuple[str, int]] = []
            for path, _d in frontier:
                if path in visited and path != "":
                    continue
                visited.add(path)
                expanded = mgr.expand(path=path or "/", reveal=reveal)
                expansions += 1
                if expanded.get("is_leaf") or expanded.get("withheld"):
                    collected.extend(self._collect_facts(path, reveal))
                    continue
                scored_children = []
                for child in expanded.get("children") or []:
                    if child.get("private"):
                        continue
                    label = child.get("label", "")
                    cpath = f"{path}/{label}".strip("/") if path else label
                    if cpath in visited:
                        continue
                    text = f"{label} {child.get('teaser', '')} {child.get('summary', '')}"
                    scored_children.append((gate_overlap_score(text, qtext), cpath))
                scored_children.sort(key=lambda x: x[0], reverse=True)
                for _score, cpath in scored_children[: self.beam_width]:
                    if cpath not in visited:
                        next_frontier.append((cpath, depth + 1))
            frontier = next_frontier
            if not frontier:
                break

        # Rank collected facts by lexical overlap with the query, then dedupe.
        ranked = sorted(collected, key=lambda it: (gate_overlap_score(it.text, qtext), -it.rank), reverse=True)
        seen = set()
        items: List[RetrievedItem] = []
        for rank, item in enumerate(ranked, 1):
            if item.memory_id in seen:
                continue
            seen.add(item.memory_id)
            items.append(RetrievedItem(memory_id=item.memory_id, score=item.score, rank=rank, text=item.text, path=item.path, source=self.name))
            if len(items) >= k:
                break
        # Beam facts are a small hierarchy prior placed before search hits; if
        # teasers are good they can beat search, otherwise search still fills k.
        beam_slots = max(1, k // 10)
        beam_items = items[:beam_slots]
        search_items: List[RetrievedItem] = []
        search_seen = set()
        try:
            search = mgr.search(qtext, limit=k, reveal=reveal)
        except Exception:
            search = {}
        for hit in search.get("hits") or []:
            text = hit.get("text") or hit.get("fact") or ""
            mid = self.vault.memory_for_entry(hit.get("entry_id"), text)
            if mid and mid not in search_seen:
                search_seen.add(mid)
                search_items.append(RetrievedItem(memory_id=mid, score=float(hit.get("score") or 0.0), rank=len(search_items) + 1, text=text, path=hit.get("path"), source=f"{self.name}:search"))
            if len(search_items) >= k:
                break
        merged: List[RetrievedItem] = []
        used = set()
        for it in beam_items + search_items + items:
            if len(merged) >= k:
                break
            if it.memory_id not in used:
                used.add(it.memory_id)
                merged.append(it)
        meta = {"beam_width": self.beam_width, "max_depth": self.max_depth, "expansions": expansions, "visited": len(visited), "beam_slots": len(beam_items)}
        return finalize_result(self.name, qid, merged, {}, meta)


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
    if arm == "treemem_guided_plus_global":
        if vault is None:
            raise ValueError("treemem_guided_plus_global requires a vault")
        return TreeMemGuidedRetriever(
            vault, max_depth=config.get("guided_max_depth", 4), disable_fallback=False,
            global_search_limit=config.get("plus_global_limit", 20), name="treemem_guided_plus_global")
    if arm == "treemem_beam":
        if vault is None:
            raise ValueError("treemem_beam requires a vault")
        return TreeMemBeamRetriever(vault, beam_width=config.get("beam_width", 6), max_depth=config.get("guided_max_depth", 4))
    if arm == "treemem_search":
        if vault is None:
            raise ValueError("treemem_search requires a vault")
        return TreeMemSearchRetriever(vault)
    raise ValueError(f"unknown arm: {arm}")
