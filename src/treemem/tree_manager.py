"""Core TreeMem business logic: path management, dirty propagation, validation, and tool execution."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from treemem.events import EventBus
from treemem.health import HealthChecker
from treemem.index import SearchIndex
from treemem.log_writer import LogWriter
from treemem.store import NodeData, Store
from treemem.tokenizer import count_tokens


def norm_path(path: str) -> str:
    """Normalize path to strip leading/trailing slashes and whitespace."""
    if not path or path == "/":
        return ""
    cleaned = path.strip().strip("/")
    # Replace multiple slashes
    parts = [p.strip() for p in cleaned.split("/") if p.strip()]
    return "/".join(parts)


def parent_path(path: str) -> str:
    """Get the parent path of a normalized path."""
    if not path:
        return ""
    parts = path.split("/")
    if len(parts) <= 1:
        return ""
    return "/".join(parts[:-1])


def get_ancestor_paths(path: str) -> List[str]:
    """Get all ancestor paths up to and including root (''). Ordered root-to-leaf."""
    if not path:
        return []
    parts = path.split("/")
    ancestors = [""]
    for i in range(1, len(parts)):
        ancestors.append("/".join(parts[:i]))
    return ancestors


class TreeManager:
    """Orchestrates tree operations, dirty propagation, validations, and tool execution."""

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir).resolve()
        self.store = Store(self.root_dir)
        self.log_writer = LogWriter(self.root_dir)
        self.event_bus = EventBus(self.root_dir)
        self.index = SearchIndex()
        self.health_checker = HealthChecker(self.store, self.log_writer)
        self.init_tree()
        self.rebuild_index()

    def init_tree(self) -> None:
        """Initialize the root memory vault if not present."""
        if not self.store.exists(""):
            root_node = NodeData(
                name="root",
                summary="Root catalog of personal memory.",
                aliases=["root", "vault"],
                dirty=False,
                updated=datetime.now(timezone.utc).isoformat(),
                tokens=0,
                sensitivity="normal",
                children_cap=12,
            )
            self.store.write_node_atomic("", root_node)

    def rebuild_index(self) -> None:
        """Rebuild the search index from disk."""
        log_entries = self.log_writer.read_all_entries()
        leaf_facts: List[Dict[str, str]] = []
        nodes: List[Dict[str, Any]] = []

        for p in self.health_checker.get_all_node_paths():
            n = self.store.read_node(p)
            if n:
                nodes.append({
                    "path": p,
                    "name": n.name,
                    "aliases": n.aliases,
                    "summary": n.summary,
                })
                for f in n.facts:
                    leaf_facts.append({
                        "entry_id": f.get("entry_id", ""),
                        "fact": f.get("fact", ""),
                        "path": p,
                    })

        self.index.build(log_entries, leaf_facts, nodes)

    def get_dirty_nodes(self) -> List[str]:
        """Return all dirty node paths sorted deepest first."""
        all_paths = self.health_checker.get_all_node_paths()
        dirty = []
        for p in all_paths:
            n = self.store.read_node(p)
            if n and n.dirty:
                dirty.append(p)
        # Deepest first (by slash count, then length, descending)
        dirty.sort(key=lambda x: (x.count("/"), len(x)), reverse=True)
        return dirty

    def remember(
        self,
        fact: str,
        hint: str = "",
        session: str = "default",
    ) -> Dict[str, Any]:
        """
        Tool: remember(fact, hint?)
        1. Append to today's log.
        2. Propose candidate nodes.
        3. Return {entry_id, candidates:[{path, score}], create_option:{suggested_path}}.
        """
        entry_id = self.log_writer.append(fact=fact, hint=hint, session=session)
        self.index.add_entry(entry_id, fact, hint)

        all_node_paths = self.health_checker.get_all_node_paths()
        candidates = self.index.candidate_nodes(
            fact=fact,
            hint=hint,
            limit=3,
            all_node_paths=all_node_paths,
        )

        suggested_path = hint.strip("/").strip() if hint else "general"
        if not suggested_path:
            suggested_path = "general"

        result = {
            "entry_id": entry_id,
            "candidates": candidates,
            "create_option": {"suggested_path": suggested_path},
            "tokens": count_tokens(str(candidates)),
        }
        return result

    def place(
        self,
        entry_id: str,
        path: str,
        sensitivity: str = "normal",
        session: str = "default",
    ) -> Dict[str, Any]:
        """
        Tool: place(entry_id, path)
        Writes the fact into the leaf at path. Creates intermediate nodes if missing.
        Enforces branching cap.
        Marks leaf and ALL ancestors dirty: true.
        """
        clean_path = norm_path(path)
        if not clean_path:
            raise ValueError("Cannot place fact directly at root. Specify a topic node path (e.g. 'identity/age').")

        # Check log entry exists
        log_entry = self.log_writer.get_entry(entry_id)
        if not log_entry:
            raise ValueError(f"Log entry '{entry_id}' not found in daily log.")
        fact_text = log_entry.get("fact", "")

        ancestors = get_ancestor_paths(clean_path)
        all_lock_paths = ancestors + [clean_path]

        with self.store.lock_paths(all_lock_paths, timeout=5.0):
            # 1. Create missing intermediate nodes
            current_ancestor = ""
            for seg in clean_path.split("/")[:-1]:
                next_ancestor = f"{current_ancestor}/{seg}" if current_ancestor else seg
                if not self.store.exists(next_ancestor):
                    # Check parent's children cap before creating intermediate node
                    p_node = self.store.read_node(current_ancestor)
                    if p_node:
                        child_dirs = self.store.list_child_dirs(current_ancestor)
                        if len(child_dirs) >= p_node.children_cap:
                            raise RuntimeError(
                                f"Branching cap exceeded at '{current_ancestor or '/'}': already has {len(child_dirs)} children (cap={p_node.children_cap}). Call split() first."
                            )

                    node_obj = NodeData(
                        name=seg,
                        summary=f"Placeholder summary for {seg}.",
                        aliases=[seg],
                        dirty=True,
                        sensitivity="normal",
                        children_cap=12,
                    )
                    self.store.write_node_atomic(next_ancestor, node_obj)
                    # Update parent's children list
                    if p_node:
                        labels = {c["label"] for c in p_node.children}
                        if seg not in labels:
                            p_node.children.append({"label": seg, "teaser": f"Subtopic {seg}"})
                            p_node.dirty = True
                            self.store.write_node_atomic(current_ancestor, p_node)
                current_ancestor = next_ancestor

            # Check immediate parent's children cap if leaf is new
            leaf_parent = parent_path(clean_path)
            leaf_name = clean_path.split("/")[-1]
            p_node = self.store.read_node(leaf_parent)
            if p_node and not self.store.exists(clean_path):
                child_dirs = self.store.list_child_dirs(leaf_parent)
                if len(child_dirs) >= p_node.children_cap:
                    raise RuntimeError(
                        f"Branching cap exceeded at '{leaf_parent or '/'}': already has {len(child_dirs)} children (cap={p_node.children_cap}). Call split() first."
                    )

            # 2. Read or create leaf node
            leaf_node = self.store.read_node(clean_path)
            if not leaf_node:
                leaf_node = NodeData(
                    name=leaf_name,
                    summary=f"Leaf notes on {leaf_name}.",
                    aliases=[leaf_name],
                    dirty=True,
                    sensitivity=sensitivity,
                    children_cap=12,
                )
            else:
                leaf_node.dirty = True
                if sensitivity == "private":
                    leaf_node.sensitivity = "private"

            # Append fact if not already present
            if not any(f.get("entry_id") == entry_id for f in leaf_node.facts):
                leaf_node.facts.append({"fact": fact_text, "entry_id": entry_id})

            self.store.write_node_atomic(clean_path, leaf_node)

            # Update immediate parent's children list to include leaf
            if p_node:
                child_labels = {c["label"] for c in p_node.children}
                if leaf_name not in child_labels:
                    teaser = "contains private details" if leaf_node.sensitivity == "private" else f"Details on {leaf_name}"
                    p_node.children.append({"label": leaf_name, "teaser": teaser})
                p_node.dirty = True
                self.store.write_node_atomic(leaf_parent, p_node)

            # 3. Propagate dirty flag to ALL ancestors
            dirtied_paths = [clean_path]
            for anc in ancestors:
                anc_node = self.store.read_node(anc)
                if anc_node:
                    anc_node.dirty = True
                    self.store.write_node_atomic(anc, anc_node)
                    dirtied_paths.append(anc)

        # Update index placement
        self.index.record_placement(entry_id, clean_path)

        # Emit write event
        self.event_bus.emit(
            event_type="write",
            payload={"entry_id": entry_id, "path": clean_path, "dirtied": dirtied_paths},
            session=session,
        )

        return {
            "status": "placed",
            "entry_id": entry_id,
            "path": clean_path,
            "dirtied": dirtied_paths,
            "tokens": count_tokens(fact_text),
        }

    def recall(
        self,
        path: str = "/",
        query_id: Optional[str] = None,
        session: str = "default",
    ) -> Dict[str, Any]:
        """
        Tool: recall(path="/")
        Returns {summary, children:[{label, teaser}], dirty, sensitivity, tokens, stale_note?}.
        MUST NOT return child bodies.
        """
        clean_path = norm_path(path)
        node = self.store.read_node(clean_path)
        if not node:
            all_paths = self.health_checker.get_all_node_paths()
            suggestions = [p for p in all_paths if clean_path.split("/")[-1].lower() in p.lower()][:3]
            raise FileNotFoundError(f"Node '{clean_path or '/'}' not found. Closest paths: {suggestions}")

        # Format children with privacy rules
        child_teasers: List[Dict[str, str]] = []
        for ch in node.children:
            ch_label = ch["label"]
            ch_path = f"{clean_path}/{ch_label}" if clean_path else ch_label
            ch_node = self.store.read_node(ch_path)
            teaser = ch.get("teaser", "")
            if ch_node and ch_node.sensitivity == "private":
                teaser = "contains private details, expand to view"
            child_teasers.append({"label": ch_label, "teaser": teaser})

        payload: Dict[str, Any] = {
            "path": clean_path or "/",
            "name": node.name,
            "summary": node.summary,
            "children": child_teasers,
            "dirty": node.dirty,
            "sensitivity": node.sensitivity,
        }

        if node.dirty:
            payload["stale_note"] = f"Warning: This node was last summarized at {node.updated}. Its children or facts have changed since. Run compress('{clean_path or '/'}') to refresh."

        # Compute tokens
        rendered = f"{node.summary}\n" + "\n".join(f"{c['label']}: {c['teaser']}" for c in child_teasers)
        tok_count = count_tokens(rendered)
        payload["tokens"] = tok_count

        depth = 0 if not clean_path else clean_path.count("/") + 1

        self.event_bus.emit(
            event_type="recall",
            payload={"path": clean_path or "/", "tokens": tok_count, "dirty": node.dirty, "depth": depth},
            session=session,
            query_id=query_id,
        )

        return payload

    def expand(
        self,
        path: str,
        reveal: bool = False,
        query_id: Optional[str] = None,
        session: str = "default",
    ) -> Dict[str, Any]:
        """
        Tool: expand(path)
        Returns child summaries (or raw facts if path is a leaf).
        Private children return teaser only unless reveal=true is passed explicitly.
        """
        clean_path = norm_path(path)
        node = self.store.read_node(clean_path)
        if not node:
            raise FileNotFoundError(f"Node '{clean_path or '/'}' not found.")

        is_leaf = self.store.is_leaf(clean_path)
        payload: Dict[str, Any] = {
            "path": clean_path or "/",
            "is_leaf": is_leaf,
        }

        if is_leaf:
            # Leaf facts
            if node.sensitivity == "private" and not reveal:
                payload["facts"] = [{"fact": "[Private details withheld. Pass reveal=true to expand]", "entry_id": ""}]
                payload["private"] = True
            else:
                payload["facts"] = node.facts
                payload["private"] = (node.sensitivity == "private")
            text_repr = "\n".join(f["fact"] for f in payload["facts"])
        else:
            # Child summaries
            children_data: List[Dict[str, Any]] = []
            for ch in node.children:
                ch_label = ch["label"]
                ch_path = f"{clean_path}/{ch_label}" if clean_path else ch_label
                ch_node = self.store.read_node(ch_path)
                if not ch_node:
                    continue
                if ch_node.sensitivity == "private" and not reveal:
                    children_data.append({
                        "label": ch_label,
                        "teaser": "contains private details, expand with reveal=true to view",
                        "summary": "[Private details withheld]",
                        "private": True,
                    })
                else:
                    children_data.append({
                        "label": ch_label,
                        "teaser": ch.get("teaser", ""),
                        "summary": ch_node.summary,
                        "private": ch_node.sensitivity == "private",
                    })
            payload["children"] = children_data
            text_repr = "\n".join(c.get("summary", "") for c in children_data)

        tok_count = count_tokens(text_repr)
        payload["tokens"] = tok_count

        self.event_bus.emit(
            event_type="expand",
            payload={
                "path": clean_path or "/",
                "tokens": tok_count,
                "children_returned": len(payload.get("children", payload.get("facts", []))),
            },
            session=session,
            query_id=query_id,
        )

        return payload

    def compress(self, path: str) -> Dict[str, Any]:
        """
        Tool: compress(path)
        Returns {prompt, inputs:[child summaries or facts], length_cap, required_sections}.
        Does not modify anything.
        """
        clean_path = norm_path(path)
        node = self.store.read_node(clean_path)
        if not node:
            raise FileNotFoundError(f"Node '{clean_path or '/'}' not found.")

        is_leaf = self.store.is_leaf(clean_path)
        inputs: List[Dict[str, Any]] = []

        if is_leaf:
            for f in node.facts:
                inputs.append({"type": "fact", "text": f["fact"], "entry_id": f["entry_id"]})
        else:
            for ch in node.children:
                ch_label = ch["label"]
                ch_path = f"{clean_path}/{ch_label}" if clean_path else ch_label
                ch_node = self.store.read_node(ch_path)
                if ch_node:
                    inputs.append({
                        "type": "child_summary",
                        "label": ch_label,
                        "summary": ch_node.summary,
                        "sensitivity": ch_node.sensitivity,
                    })

        child_dirs = self.store.list_child_dirs(clean_path)
        prompt = (
            f"You are summarizing the topic '{node.name}'. Write a clear, concise summary "
            f"between 40 and 120 tokens (max 150 tokens). "
            f"You MUST include a '## Children' section listing every child exactly as: '- [[child_label]] - teaser'. "
            f"Do NOT include details from any child marked sensitivity: private."
        )

        return {
            "path": clean_path or "/",
            "prompt": prompt,
            "inputs": inputs,
            "length_cap": 150,
            "required_children": child_dirs,
            "required_sections": ["## Children"] if child_dirs else [],
            "tokens": count_tokens(prompt + str(inputs)),
        }

    def commit_summary(
        self,
        path: str,
        text: str,
        session: str = "default",
    ) -> Dict[str, Any]:
        """
        Tool: commit_summary(path, text)
        Validates then writes atomically:
        - length <= cap (150 tokens)
        - contains ## Children list matching actual children on disk (no missing, no invented)
        - no content from sensitivity: private children
        """
        clean_path = norm_path(path)
        node = self.store.read_node(clean_path)
        if not node:
            raise FileNotFoundError(f"Node '{clean_path or '/'}' not found.")

        # Parse submitted text
        fm, summary, children_parsed, facts_parsed = self.store.parse_summary_md(text)
        submitted_tokens = count_tokens(summary)

        # Validation 1: Length cap
        if submitted_tokens > 150:
            err = f"Summary exceeds length cap of 150 tokens (got {submitted_tokens} tokens). Overage: {submitted_tokens - 150} tokens."
            self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
            return {"ok": False, "error": err}

        # Validation 2: Children matching actual children
        actual_children = set(self.store.list_child_dirs(clean_path))
        submitted_children = {c["label"] for c in children_parsed}
        if actual_children != submitted_children:
            missing = list(actual_children - submitted_children)
            extra = list(submitted_children - actual_children)
            err_parts = []
            if missing:
                err_parts.append(f"missing child labels: {missing}")
            if extra:
                err_parts.append(f"invented child labels not on disk: {extra}")
            err = f"Summary children do not match disk directories: {'; '.join(err_parts)}"
            self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
            return {"ok": False, "error": err}

        # Validation 3: Privacy check - no content from private descendants
        all_node_paths = self.health_checker.get_all_node_paths()
        prefix = (clean_path + "/") if clean_path else ""
        descendant_paths = [p for p in all_node_paths if p.startswith(prefix) and p != clean_path]
        for ch_path in descendant_paths:
            ch_node = self.store.read_node(ch_path)
            if ch_node and ch_node.sensitivity == "private":
                # Check summary substring
                if ch_node.summary and len(ch_node.summary) > 10 and ch_node.summary.lower() in summary.lower():
                    err = f"Summary leaks exact content from private child '{ch_path}'"
                    self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
                    return {"ok": False, "error": err}

                # Check fact text substrings and token overlap
                for f in ch_node.facts:
                    f_text = f.get("fact", "").strip().lower()
                    if len(f_text) > 5 and f_text in summary.lower():
                        err = f"Summary leaks private fact from child '{ch_path}': '{f_text}'"
                        self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
                        return {"ok": False, "error": err}
                    for token in re.findall(r"\b\w+\b", f_text):
                        if (len(token) >= 5 or token.isdigit()) and token in summary.lower():
                            if token not in {"user", "details", "private", "information", "about", "their"}:
                                err = f"Summary leaks private details from child '{ch_path}' (term: '{token}')"
                                self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
                                return {"ok": False, "error": err}

                # Check word overlap
                priv_words = set(re.findall(r"\b\w{4,}\b", (ch_node.summary + " " + " ".join(f["fact"] for f in ch_node.facts)).lower()))
                sum_words = set(re.findall(r"\b\w{4,}\b", summary.lower()))
                overlap = priv_words.intersection(sum_words) - {"child", "details", "private", "expand", "view"}
                if len(overlap) >= 3:
                    err = f"Summary leaks private details from child '{ch_path}' (overlapping terms: {list(overlap)[:3]})"
                    self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
                    return {"ok": False, "error": err}

        # Passed validations: write node atomically
        node.summary = summary
        node.children = children_parsed
        node.dirty = False
        node.updated = datetime.now(timezone.utc).isoformat()
        node.tokens = submitted_tokens

        with self.store.lock_paths([clean_path], timeout=5.0):
            self.store.write_node_atomic(clean_path, node)

        self.rebuild_index()

        self.event_bus.emit(
            event_type="summary",
            payload={"path": clean_path or "/", "tokens": submitted_tokens, "ok": True},
            session=session,
        )

        return {"ok": True, "path": clean_path or "/", "tokens": submitted_tokens, "dirty": False}

    def search(self, query: str, limit: int = 10, session: str = "default") -> Dict[str, Any]:
        """
        Tool: search(query, limit=10)
        Lexical search over log and leaves. Fallback when descent fails.
        """
        hits = self.index.query(query, limit=limit)
        tok_count = count_tokens(query + str(hits))
        self.event_bus.emit(
            event_type="search",
            payload={"query": query, "hits": len(hits)},
            session=session,
        )
        return {
            "query": query,
            "hits": hits,
            "count": len(hits),
            "tokens": tok_count,
        }

    def split(self, path: str, groups: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Tool: split(path, groups)
        groups = [{"name": "intermediate_name", "children": ["child1", "child2"]}]
        Moves existing child folders under new intermediate group directories.
        """
        clean_path = norm_path(path)
        node = self.store.read_node(clean_path)
        if not node:
            raise FileNotFoundError(f"Node '{clean_path or '/'}' not found.")

        ndir = self.store.node_dir(clean_path)
        new_children = []

        with self.store.lock_paths([clean_path], timeout=5.0):
            for grp in groups:
                grp_name = grp["name"].strip()
                grp_dir = ndir / grp_name
                grp_dir.mkdir(parents=True, exist_ok=True)

                grp_children = []
                for ch in grp.get("children", []):
                    ch_src = ndir / ch
                    ch_dst = grp_dir / ch
                    if ch_src.exists() and ch_src.is_dir():
                        os.rename(ch_src, ch_dst)
                        grp_children.append({"label": ch, "teaser": f"Details on {ch}"})

                grp_node = NodeData(
                    name=grp_name,
                    summary=f"Intermediate grouping for {grp_name}.",
                    children=grp_children,
                    dirty=True,
                    sensitivity="normal",
                    children_cap=12,
                )
                grp_path = f"{clean_path}/{grp_name}" if clean_path else grp_name
                self.store.write_node_atomic(grp_path, grp_node)
                new_children.append({"label": grp_name, "teaser": f"Group {grp_name}"})

            node.children = new_children
            node.dirty = True
            self.store.write_node_atomic(clean_path, node)

        self.rebuild_index()
        return {"ok": True, "path": clean_path or "/", "new_groups": [g["name"] for g in groups]}

    def rebuild(self, path: Optional[str] = None) -> Dict[str, Any]:
        """
        Tool / Command: rebuild(path=None)
        Rebuild tree from append-only log facts.
        """
        all_entries = self.log_writer.read_all_entries()
        rebuilt_count = 0

        # Ensure root exists
        self.init_tree()

        for entry in all_entries:
            eid = entry["entry_id"]
            fact = entry["fact"]
            hint = entry.get("hint", "") or "general"
            target_path = norm_path(hint)
            if not target_path:
                target_path = "general"

            if path and norm_path(path) != target_path:
                continue

            try:
                self.place(entry_id=eid, path=target_path)
                rebuilt_count += 1
            except Exception:
                pass

        self.rebuild_index()
        return {"ok": True, "rebuilt_facts": rebuilt_count}
