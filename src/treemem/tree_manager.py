"""Core TreeMem business logic: path management, dirty propagation, validation, and tool execution."""

import os
import re
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from treemem.events import EventBus
from treemem.health import HealthChecker
from treemem.index import SearchIndex
from treemem.log_writer import LogWriter
from treemem.store import NodeData, Store
from treemem.tokenizer import count_tokens
from treemem.transclusion import TransclusionManager
from treemem.descent_gate import DescentGate


_MAX_PATH_DEPTH = 8


def validate_segment(segment: str) -> str:
    """Validate a single path segment. Raises ValueError if illegal.

    Rules (after NFC normalization):
    - Length 1 to 100 characters
    - First character must be a Unicode letter or digit (str.isalnum())
    - Every character must be: letter, digit, combining mark (category starts with "M"),
      or one of: underscore, hyphen, dot, plus, hash, space
    - No leading or trailing space
    - No two consecutive dots
    - Not "." or ".."
    - Not "log" (reserved)
    - Not starting with "."
    - No "/", "\", NUL or any control character (category starts with "C")
    """
    if segment is None:
        raise ValueError("Empty path segment is not allowed")
    seg = segment if isinstance(segment, str) else str(segment)
    if not seg:
        raise ValueError("Empty path segment is not allowed")

    # Check for leading/trailing space
    if seg.startswith(" ") or seg.endswith(" "):
        raise ValueError("Path segment cannot have leading or trailing space")

    # Normalize to NFC
    seg = unicodedata.normalize("NFC", seg)

    # Length check
    if len(seg) < 1 or len(seg) > 100:
        raise ValueError(f"Path segment must be 1-100 characters, got {len(seg)}")

    # Not "." or ".."
    if seg in (".", ".."):
        raise ValueError(f"Path segment '{seg}' is not allowed")

    # Not starting with "."
    if seg.startswith("."):
        raise ValueError("Path segments cannot start with '.'")

    # First character must be alphanumeric
    if not seg[0].isalnum():
        raise ValueError(f"Path segment must start with a letter or digit, got '{seg[0]}'")

    # Check each character
    allowed_special = set("_-.+# ")
    for i, ch in enumerate(seg):
        cat = unicodedata.category(ch)
        # Reject NUL specifically first
        if ch == "\x00":
            raise ValueError("Path segment cannot contain NUL")

        # Reject control characters
        if cat.startswith("C"):
            raise ValueError(f"Control character not allowed in path segment")

        # Reject backslash (slash is handled by norm_path splitting)
        if ch == "\\":
            raise ValueError(f"Path segment cannot contain '\\'")

        # Allow letters, digits, combining marks, or special chars
        if not (ch.isalnum() or cat.startswith("M") or ch in allowed_special):
            raise ValueError(f"Invalid character '{ch}' at position {i} in path segment")

    # No two consecutive dots
    if ".." in seg:
        raise ValueError("Path segment cannot contain two consecutive dots")

    # Not "log" (reserved)
    if seg.lower() == "log":
        raise ValueError("The path segment 'log' is reserved")

    return seg


def norm_path(path: str) -> str:
    """Normalize and validate a vault-relative node path.

    Root is "". Raises ValueError for traversal, absolute paths, reserved
    names, and illegal segments. Used by every tool, the dashboard, and the CLI.
    Normalizes the entire path to NFC for Unicode consistency.
    """
    if path is None:
        raise ValueError("Path is required")
    raw = path.strip() if isinstance(path, str) else str(path).strip()
    if not raw or raw == "/":
        return ""
    if "\x00" in raw:
        raise ValueError("Path cannot contain NUL")
    if "\\" in raw:
        raise ValueError("Backslashes are not allowed in paths")
    if raw.startswith("/") or raw.startswith("~"):
        raise ValueError("Absolute paths are not allowed")
    cleaned = raw.strip("/")
    if not cleaned:
        return ""
    parts = cleaned.split("/")
    if len(parts) > _MAX_PATH_DEPTH:
        raise ValueError(f"Maximum path depth is {_MAX_PATH_DEPTH}")
    validated = [validate_segment(p) for p in parts]
    # Normalize the entire path to NFC
    return unicodedata.normalize("NFC", "/".join(validated))


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

    def __init__(self, root_dir: Path, embedding_provider: Optional[Any] = None):
        self.root_dir = Path(root_dir).resolve()
        self.placements_file = self.root_dir / ".placements.jsonl"
        self.store = Store(self.root_dir)
        self.log_writer = LogWriter(self.root_dir)
        self.event_bus = EventBus(self.root_dir)
        self.embedding_provider = embedding_provider
        self.index = SearchIndex(
            embedding_provider=self.embedding_provider,
            is_private_path_fn=self._is_private_path,
        )
        self.health_checker = HealthChecker(self.store, self.log_writer)
        self.transclusion_mgr = TransclusionManager(self.store, is_private_fn=self.is_private)
        self.descent_gate = DescentGate()
        self.init_tree()
        self.rebuild_index()
        self.transclusion_mgr.rebuild_index(self.health_checker.get_all_node_paths())

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
        """Rebuild the search index from disk.

        Collects all private node paths (and their ancestors) so the index
        can skip embedding private text regardless of which provider is active.
        Single-pass: reads each node once, computes private paths from prefixes.
        """
        log_entries = self.log_writer.read_all_entries()
        leaf_facts: List[Dict[str, str]] = []
        nodes: List[Dict[str, Any]] = []

        all_paths = self.health_checker.get_all_node_paths()

        # Build the private-paths set in single pass using prefix matching
        # First, collect all directly private nodes
        directly_private: set = set()
        node_data = {}  # path -> node
        for p in all_paths:
            n = self.store.read_node(p)
            if n:
                node_data[p] = n
                if n.sensitivity == "private":
                    directly_private.add(p)

        # Then compute effective private paths: a path is private if it or any ancestor is private
        private_paths: set = set()
        for p in all_paths:
            # Check if p or any ancestor is in directly_private
            if p in directly_private:
                private_paths.add(p)
            else:
                # Check all ancestors
                parts = p.split("/") if p else []
                for i in range(len(parts)):
                    ancestor = "/".join(parts[:i+1])
                    if ancestor in directly_private:
                        private_paths.add(p)
                        break

        # Build leaf_facts and nodes in single pass
        for p in all_paths:
            n = node_data.get(p)
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

        self.index.build(log_entries, leaf_facts, nodes, private_paths=private_paths)

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
        sensitivity: str = "normal",
    ) -> Dict[str, Any]:
        """
        Tool: remember(fact, hint?)
        1. Append to today's log.
        2. Propose candidate nodes.
        3. Return {entry_id, candidates:[{path, score}], create_option:{suggested_path}}.
        """
        if sensitivity not in {"normal", "private"}:
            raise ValueError("sensitivity must be 'normal' or 'private'")
        entry_id = self.log_writer.append(fact=fact, hint=hint, session=session, sensitivity=sensitivity)
        self.index.add_entry(entry_id, fact, hint, sensitivity=sensitivity)

        all_node_paths = self.health_checker.get_all_node_paths()
        candidates = self.index.candidate_nodes(
            fact=fact,
            hint=hint,
            limit=3,
            all_node_paths=all_node_paths,
        )

        suggested_path = "general"
        hint_rejected = False
        hint_error = None
        if hint:
            try:
                candidate = norm_path(hint)
                if candidate:
                    suggested_path = candidate
            except ValueError as exc:
                suggested_path = "general"
                hint_rejected = True
                hint_error = str(exc)

        result = {
            "entry_id": entry_id,
            "candidates": candidates,
            "create_option": {"suggested_path": suggested_path},
            "tokens": count_tokens(str(candidates)),
            "hint_rejected": hint_rejected,
            "hint_error": hint_error,
        }
        return result

    def place(
        self,
        entry_id: str,
        path: str,
        sensitivity: Optional[str] = None,
        volatile: bool = False,
        session: str = "default",
        record_journal: bool = True,
    ) -> Dict[str, Any]:
        """
        Tool: place(entry_id, path, sensitivity="normal", volatile=False)
        Writes the fact into the leaf at path. Creates intermediate nodes if missing.
        Enforces branching cap.
        Marks leaf and ancestors dirty: true (skipping ancestors that transclude this target).
        """
        clean_path = norm_path(path)
        if not clean_path:
            raise ValueError("Cannot place fact directly at root. Specify a topic node path (e.g. 'identity/age').")

        # Check log entry exists
        log_entry = self.log_writer.get_entry(entry_id)
        if not log_entry:
            raise ValueError(f"Log entry '{entry_id}' not found in daily log.")
        fact_text = log_entry.get("fact", "")
        if sensitivity is None:
            sensitivity = log_entry.get("sensitivity", "normal")
        if sensitivity not in {"normal", "private"}:
            raise ValueError("sensitivity must be 'normal' or 'private'")

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

            # Append fact if not already present, or update if existing
            existing_fact = next((f for f in leaf_node.facts if f.get("entry_id") == entry_id), None)
            if not existing_fact:
                leaf_node.facts.append({"fact": fact_text, "entry_id": entry_id, "volatile": volatile})
            else:
                existing_fact["fact"] = fact_text
                if volatile:
                    existing_fact["volatile"] = True

            self.store.write_node_atomic(clean_path, leaf_node)

            # Update immediate parent's children list to include leaf
            embedding_parents = self.transclusion_mgr.get_embedding_parents(clean_path)
            if p_node:
                child_labels = {c["label"] for c in p_node.children}
                if leaf_name not in child_labels:
                    teaser = "contains private details" if leaf_node.sensitivity == "private" else f"Details on {leaf_name}"
                    p_node.children.append({"label": leaf_name, "teaser": teaser})
                if leaf_parent not in embedding_parents:
                    p_node.dirty = True
                self.store.write_node_atomic(leaf_parent, p_node)

            # 3. Propagate dirty flag to ancestors (skipping ancestors that transclude this target)
            dirtied_paths = [clean_path]
            for anc in ancestors:
                if anc in embedding_parents:
                    # Ancestor transcludes this fact dynamically; do not mark dirty
                    continue
                anc_node = self.store.read_node(anc)
                if anc_node:
                    anc_node.dirty = True
                    self.store.write_node_atomic(anc, anc_node)
                    dirtied_paths.append(anc)

        # Update index placement
        self.index.record_placement(entry_id, clean_path)
        # Refresh the leaf node in the index
        self.index.refresh_node(clean_path, {
            "name": leaf_node.name,
            "summary": leaf_node.summary,
            "aliases": leaf_node.aliases,
            "sensitivity": leaf_node.sensitivity,
        })
        if record_journal:
            self._append_placement(entry_id, clean_path, sensitivity, volatile)

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

    def _append_placement(self, entry_id: str, path: str, sensitivity: str, volatile: bool) -> None:
        """Persist placement intent; the log remains the fact source of truth."""
        record = {
            "ts": datetime.now(timezone.utc).isoformat(), "entry_id": entry_id,
            "path": path, "sensitivity": sensitivity, "volatile": bool(volatile),
        }
        with open(self.placements_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _placement_records(self) -> Dict[str, Dict[str, Any]]:
        """Read the append-only journal; last record for an entry wins."""
        records: Dict[str, Dict[str, Any]] = {}
        if not self.placements_file.exists():
            return records
        with open(self.placements_file, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    eid = record.get("entry_id")
                    if not eid:
                        raise ValueError("missing entry_id")
                    record["path"] = norm_path(record.get("path", ""))
                    records[eid] = record
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    # A malformed journal line must not silently alter placement.
                    records[f"__error__{line_no}"] = {"error": f"journal line {line_no}: {exc}"}
        return records

    def _placed_entry_ids(self) -> Set[str]:
        placed: Set[str] = set()
        for p in self.health_checker.get_all_node_paths():
            node = self.store.read_node(p)
            if node:
                placed.update(f.get("entry_id", "") for f in node.facts)
        placed.discard("")
        return placed

    def recall(
        self,
        path: str = "/",
        query: Optional[str] = None,
        query_id: Optional[str] = None,
        session: str = "default",
        follow: bool = False,
        max_depth: int = 3,
        eager_descent: bool = False,
        reveal: bool = False,
    ) -> Dict[str, Any]:
        """
        Tool: recall(path="/", query=None, follow=False, max_depth=3)
        (eager_descent is internal: guided descent sets it so the gate prefers close children.)
        Returns {summary, children:[{label, teaser}], dirty, sensitivity, tokens, stale_note?, gate?}.
        MUST NOT return child bodies.
        If query is provided, evaluates descent gate for parent sufficiency.
        If follow=True and a query is given, the server follows the gate's
        suggestions (read-only) and returns the node where the descent stopped.
        """
        if follow and query:
            return self._guided_recall(
                path=path,
                query=query,
                max_depth=max_depth,
                query_id=query_id,
                session=session,
            )
        clean_path = norm_path(path)
        node = self.store.read_node(clean_path)
        if not node:
            all_paths = self.health_checker.get_all_node_paths()
            suggestions = [p for p in all_paths if clean_path.split("/")[-1].lower() in p.lower()][:3]
            raise FileNotFoundError(f"Node '{clean_path or '/'}' not found. Closest paths: {suggestions}")

        if self.is_private(clean_path) and not reveal:
            payload = {
                "path": clean_path or "/", "name": node.name,
                "summary": "[Private details withheld]", "children": [],
                "dirty": node.dirty, "sensitivity": "private", "withheld": True,
                "tokens": count_tokens("[Private details withheld]"),
            }
            self.event_bus.emit("recall", {"path": clean_path or "/", "tokens": payload["tokens"], "dirty": node.dirty, "depth": 0 if not clean_path else clean_path.count("/") + 1}, session, query_id)
            return payload

        # Format children with privacy rules
        child_teasers: List[Dict[str, str]] = []
        for ch in node.children:
            ch_label = ch["label"]
            ch_path = f"{clean_path}/{ch_label}" if clean_path else ch_label
            ch_node = self.store.read_node(ch_path)
            teaser = ch.get("teaser", "")
            if ch_node and self.is_private(ch_path):
                teaser = "contains private details, expand to view"
            child_teasers.append({"label": ch_label, "teaser": teaser})

        # Dynamically resolve ![[path#ref]] transclusion embeds at read time
        resolved_summary, embeds = self.transclusion_mgr.resolve_summary(node.summary)

        payload: Dict[str, Any] = {
            "path": clean_path or "/",
            "name": node.name,
            "summary": resolved_summary,
            "raw_summary": node.summary,
            "embeds": embeds,
            "children": child_teasers,
            "dirty": node.dirty,
            "sensitivity": node.sensitivity,
        }
        # An explicit, operator-authorized reveal may inspect a private leaf in
        # one call.  Normal recalls remain summary-only.
        if reveal and self.is_private(clean_path) and self.store.is_leaf(clean_path):
            payload["facts"] = list(node.facts)

        # Evaluate predictive descent gate if query is provided
        if query:
            gate_eval = self.descent_gate.evaluate(
                query=query,
                parent_path=clean_path,
                parent_summary=resolved_summary,
                children=child_teasers,
                eager_descent=eager_descent,
            )
            if gate_eval:
                payload["gate"] = gate_eval

        if node.dirty:
            payload["stale_note"] = f"Warning: This node was last summarized at {node.updated}. Its children or facts have changed since. Run compress('{clean_path or '/'}') to refresh."

        # Compute tokens from resolved text
        rendered = f"{resolved_summary}\n" + "\n".join(f"{c['label']}: {c['teaser']}" for c in child_teasers)
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

    def _guided_recall(
        self,
        path: str,
        query: str,
        max_depth: int = 3,
        query_id: Optional[str] = None,
        session: str = "default",
    ) -> Dict[str, Any]:
        """
        Read-only guided descent. Starting at `path`, repeatedly ask the descent gate
        what to do and follow its suggestion until it says stop, hits a private node,
        reaches a leaf, runs out of depth, or falls back to search.

        Never writes files, never changes dirty flags, never takes write locks.
        Never steps into (or exposes) a node whose sensitivity is private.
        """
        if max_depth < 0:
            max_depth = 0

        current_path = norm_path(path)
        visited = set()
        traversal: List[Dict[str, Any]] = []
        stopped_reason = "max_depth"
        extra: Dict[str, Any] = {}
        search_result: Optional[Dict[str, Any]] = None
        steps_taken = 0
        final_payload: Dict[str, Any] = {}

        while True:
            visited.add(current_path)

            # recall() without follow reads the node and emits one "recall" event per step.
            final_payload = self.recall(
                path=current_path or "/",
                query=query,
                query_id=query_id,
                session=session,
                follow=False,
                eager_descent=True,
            )
            gate = final_payload.get("gate") or {}
            action = gate.get("action", "stop")

            traversal.append({
                "path": current_path or "/",
                "action": action,
                "parent_score": gate.get("parent_score"),
                "child_score": gate.get("child_score"),
            })

            # A leaf node has no children to follow; its facts are the answer.
            if not final_payload.get("children"):
                stopped_reason = "leaf"
                break

            if action == "stop":
                stopped_reason = "stop"
                break

            if action == "search_fallback":
                search_result = self.search(query=query, limit=5, session=session)
                stopped_reason = "search_fallback"
                break

            # action == "descend"
            suggested = gate.get("suggested_child")
            if not suggested:
                stopped_reason = "stop"
                break

            if steps_taken >= max_depth:
                stopped_reason = "max_depth"
                break

            child_path = f"{current_path}/{suggested}" if current_path else suggested
            child_node = self.store.read_node(child_path)
            if child_node is None:
                stopped_reason = "stop"
                break

            if self.is_private(child_path):
                stopped_reason = "private"
                extra["stopped_at_private"] = True
                extra["suggested_child"] = suggested
                extra["message"] = (
                    f"Suggested topic '{suggested}' has sensitivity: private. "
                    "Auto-descent halted. Explicit recall or expand with reveal=true is required."
                )
                break

            if child_path in visited:
                stopped_reason = "stop"
                break

            current_path = child_path
            steps_taken += 1

        # Leaf facts are returned only for non-private nodes.
        facts: List[Dict[str, Any]] = []
        if stopped_reason == "leaf":
            leaf_node = self.store.read_node(current_path)
            if leaf_node is not None:
                if self.is_private(current_path):
                    facts = [{"fact": "[Private details withheld. Pass reveal=true to expand]", "entry_id": ""}]
                else:
                    facts = list(leaf_node.facts)

        result: Dict[str, Any] = dict(final_payload)
        result["final_path"] = current_path or "/"
        result["traversal"] = traversal
        result["steps"] = steps_taken
        result["stopped_reason"] = stopped_reason
        if facts:
            result["facts"] = facts
        if search_result is not None:
            result["search"] = self._bound_search_result(search_result, max_tokens=400)
        for key, value in extra.items():
            result[key] = value

        # Tokens reflect only what is returned to the agent (intermediate nodes are not sent).
        returned_text = result.get("summary", "") + "\n"
        for child in result.get("children", []):
            returned_text += f"{child['label']}: {child['teaser']}\n"
        for fact in facts:
            returned_text += fact.get("fact", "") + "\n"
        if "search" in result:
            returned_text += str(result["search"].get("hits", ""))
        result["tokens"] = count_tokens(returned_text)
        return result

    @staticmethod
    def _bound_search_result(search_result: Dict[str, Any], max_tokens: int = 400) -> Dict[str, Any]:
        """Keep search hits only while their combined size stays under max_tokens."""
        kept_hits: List[Any] = []
        used_tokens = 0
        for hit in search_result.get("hits", []):
            hit_tokens = count_tokens(str(hit))
            if used_tokens + hit_tokens > max_tokens:
                break
            kept_hits.append(hit)
            used_tokens += hit_tokens
        return {
            "query": search_result.get("query", ""),
            "hits": kept_hits,
            "count": len(kept_hits),
            "tokens": used_tokens,
            "truncated": len(kept_hits) < len(search_result.get("hits", [])),
        }

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

        if self.is_private(clean_path) and not reveal:
            payload.update({"private": True, "withheld": True})
            if is_leaf:
                payload["facts"] = [{"fact": "[Private details withheld]", "entry_id": ""}]
            else:
                payload["children"] = []
            payload["tokens"] = count_tokens("[Private details withheld]")
            return payload

        if is_leaf:
            # Leaf facts
            if self.is_private(clean_path) and not reveal:
                payload["facts"] = [{"fact": "[Private details withheld. Pass reveal=true to expand]", "entry_id": ""}]
                payload["private"] = True
            else:
                payload["facts"] = node.facts
                payload["private"] = self.is_private(clean_path)
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
                if self.is_private(ch_path) and not reveal:
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
                        "private": self.is_private(ch_path),
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

    def compress(self, path: str, reveal: bool = False) -> Dict[str, Any]:
        """
        Tool: compress(path)
        Returns {prompt, inputs:[child summaries or facts], length_cap, required_sections}.
        Does not modify anything.
        """
        clean_path = norm_path(path)
        node = self.store.read_node(clean_path)
        if not node:
            raise FileNotFoundError(f"Node '{clean_path or '/'}' not found.")

        if self.is_private(clean_path) and not reveal:
            return {"ok": False, "path": clean_path or "/", "skipped_private": True}

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
                if ch_node and self.is_private(ch_path) and not reveal:
                    inputs.append({"type": "private_placeholder", "label": ch_label})
                elif ch_node:
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
        expected_updated: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Tool: commit_summary(path, text)
        Validates then writes atomically inside a single lock:
        - re-reads the node fresh from disk inside the lock
        - optimistic concurrency conflict check against the FRESH node
        - length <= cap (150 tokens)
        - contains ## Children list matching actual children on disk (no missing, no invented)
        - no content from sensitivity: private children
        Writes back ONLY summary, children, dirty, updated, tokens onto the fresh node.
        Never overwrites facts, sensitivity, aliases or any other field from a stale copy.
        Does NOT call rebuild_index(), transclusion indexing or the event bus while holding the lock.
        """
        clean_path = norm_path(path)

        # Fast existence check before taking the lock (no lock needed for exists()).
        if not self.store.exists(clean_path):
            raise FileNotFoundError(f"Node '{clean_path or '/'}' not found.")

        # Parse and validate the submitted text BEFORE taking the lock
        # (pure CPU work; no disk writes; safe to do unlocked).
        fm, summary, children_parsed, facts_parsed = self.store.parse_summary_md(text)
        submitted_tokens = count_tokens(summary)

        # Validation 1: Length cap
        if submitted_tokens > 150:
            err = f"Summary exceeds length cap of 150 tokens (got {submitted_tokens} tokens). Overage: {submitted_tokens - 150} tokens."
            self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
            return {"ok": False, "error": err}

        # Validation 1b: Transclusion embeds cap (max 5)
        embed_count = self.transclusion_mgr.count_embeds(summary)
        if embed_count > self.transclusion_mgr.max_embeds:
            err = f"Summary exceeds maximum allowed transclusion embeds (cap is {self.transclusion_mgr.max_embeds}, got {embed_count})."
            self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
            return {"ok": False, "error": err}

        # --- Single lock block: re-read, conflict check, children validation, write ---
        with self.store.lock_paths([clean_path], timeout=5.0):
            # Re-read the node fresh from disk inside the lock.
            fresh_node = self.store.read_node(clean_path)
            if not fresh_node:
                raise FileNotFoundError(f"Node '{clean_path or '/'}' not found.")

            # Concurrency / conflict check against the FRESH node.
            if expected_updated is not None and fresh_node.updated != expected_updated:
                err = (
                    f"Conflict: Node '{clean_path or '/'}' was modified since version {expected_updated} "
                    f"(current: {fresh_node.updated})."
                )
                self.event_bus.emit(
                    "summary",
                    {"path": clean_path or "/", "tokens": 0, "ok": False, "error": err, "conflict": True},
                    session,
                )
                return {
                    "ok": False,
                    "conflict": True,
                    "error": err,
                    "current_updated": fresh_node.updated,
                    "current_summary": fresh_node.summary,
                }

            # Validation 2: Children matching actual children on disk (inside lock so
            # directory listing is consistent with the lock-protected state).
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

            # Validation 3: Privacy check — no content from private descendants.
            # Read descendant nodes inside the lock for a consistent view.
            all_node_paths = self.health_checker.get_all_node_paths()
            prefix = (clean_path + "/") if clean_path else ""
            descendant_paths = [p for p in all_node_paths if p.startswith(prefix) and p != clean_path]
            for ch_path in descendant_paths:
                ch_node = self.store.read_node(ch_path)
                if ch_node and ch_node.sensitivity == "private":
                    # Check summary substring using whole-word tokenization
                    priv_summary_tokens = set(re.findall(r"[^\W_]+", ch_node.summary.lower(), re.UNICODE))
                    sum_tokens = set(re.findall(r"[^\W_]+", summary.lower(), re.UNICODE))
                    if priv_summary_tokens.intersection(sum_tokens):
                        # Check if any private summary token is significant (5+ chars or 3+ digit number)
                        for token in priv_summary_tokens.intersection(sum_tokens):
                            if len(token) >= 5 or (token.isdigit() and len(token) >= 3):
                                err = f"Summary leaks exact content from private child '{ch_path}' (term: '{token}')"
                                self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
                                return {"ok": False, "error": err}

                    # Check fact text using whole-word tokenization
                    for f in ch_node.facts:
                        f_text = f.get("fact", "").strip().lower()
                        fact_tokens = set(re.findall(r"[^\W_]+", f_text, re.UNICODE))
                        # Check for exact fact substring (only if fact is 5+ chars total)
                        if len(f_text) >= 5 and f_text in summary.lower():
                            err = f"Summary leaks private fact from child '{ch_path}': '{f_text}'"
                            self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
                            return {"ok": False, "error": err}
                        # Check token overlap (only significant tokens)
                        for token in fact_tokens.intersection(sum_tokens):
                            if len(token) >= 5 or (token.isdigit() and len(token) >= 3):
                                if token not in {"user", "details", "private", "information", "about", "their", "child", "expand", "view"}:
                                    err = f"Summary leaks private details from child '{ch_path}' (term: '{token}')"
                                    self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
                                    return {"ok": False, "error": err}

                    # Check word overlap using whole-word tokenization
                    priv_words = set(re.findall(r"[^\W_]+", (ch_node.summary + " " + " ".join(f["fact"] for f in ch_node.facts)).lower(), re.UNICODE))
                    # Filter to significant words (4+ chars or 3+ digit numbers)
                    priv_significant = {w for w in priv_words if len(w) >= 4 or (w.isdigit() and len(w) >= 3)}
                    sum_significant = {w for w in sum_tokens if len(w) >= 4 or (w.isdigit() and len(w) >= 3)}
                    overlap = priv_significant.intersection(sum_significant) - {"child", "details", "private", "expand", "view"}
                    if len(overlap) >= 3:
                        err = f"Summary leaks private details from child '{ch_path}' (overlapping terms: {list(overlap)[:3]})"
                        self.event_bus.emit("summary", {"path": clean_path or "/", "tokens": submitted_tokens, "ok": False, "error": err}, session)
                        return {"ok": False, "error": err}

            # Passed all validations: apply ONLY the summary-owned fields onto the
            # fresh node.  facts, sensitivity, aliases, children_cap, name etc. are
            # preserved from the fresh read — never from a stale copy.
            fresh_node.summary = summary
            fresh_node.children = children_parsed
            fresh_node.dirty = False
            fresh_node.updated = datetime.now(timezone.utc).isoformat()
            fresh_node.tokens = submitted_tokens

            self.store.write_node_atomic(clean_path, fresh_node)
        # --- Lock released ---

        # Heavy work happens outside the lock.
        self.transclusion_mgr.index_node(clean_path)
        # Refresh just this node in the index instead of full rebuild
        self.index.refresh_node(clean_path, {
            "name": fresh_node.name,
            "summary": fresh_node.summary,
            "aliases": fresh_node.aliases,
            "sensitivity": fresh_node.sensitivity,
        })

        self.event_bus.emit(
            event_type="summary",
            payload={"path": clean_path or "/", "tokens": submitted_tokens, "ok": True},
            session=session,
        )

        return {"ok": True, "path": clean_path or "/", "tokens": submitted_tokens, "dirty": False}

    def is_private(self, hit_path: str) -> bool:
        """True if the node at hit_path, or any ancestor of it, has sensitivity: private."""
        clean = norm_path(hit_path or "")
        if not clean:
            return False
        candidate_paths = get_ancestor_paths(clean) + [clean]
        for candidate in candidate_paths:
            node = self.store.read_node(candidate)
            if node is not None and node.sensitivity == "private":
                return True
        return False

    # Kept for index integrations written before the public method was named.
    _is_private_path = is_private

    def search(
        self,
        query: str,
        limit: int = 10,
        session: str = "default",
        reveal: bool = False,
    ) -> Dict[str, Any]:
        """
        Tool: search(query, limit=10, reveal=False)
        Lexical search over log and leaves. Fallback when descent fails.
        Hits that live under a private node are withheld unless reveal=True.
        Unplaced facts with sensitivity 'private' are also withheld unless reveal=True.
        """
        raw_hits = self.index.query(query, limit=limit)
        hits: List[Any] = []
        withheld_private = 0
        withheld_unplaced = 0
        for hit in raw_hits:
            hit_path = hit.get("path", "") if isinstance(hit, dict) else ""
            hit_sensitivity = hit.get("sensitivity", "normal") if isinstance(hit, dict) else "normal"
            
            if not reveal:
                # Withhold if under a private node
                if self.is_private(hit_path):
                    withheld_private += 1
                    continue
                # Withhold if unplaced and sensitivity is private
                if (not hit_path or hit_path == "unplaced") and hit_sensitivity == "private":
                    withheld_unplaced += 1
                    continue
            hits.append(hit)

        tok_count = count_tokens(query + str(hits))
        self.event_bus.emit(
            event_type="search",
            payload={"query_len": len(query), "query_sha256": __import__("hashlib").sha256(query.encode("utf-8")).hexdigest()[:8], "hits": len(hits)},
            session=session,
        )
        result: Dict[str, Any] = {
            "query": query,
            "hits": hits,
            "count": len(hits),
            "tokens": tok_count,
        }
        if withheld_private:
            result["withheld_private"] = withheld_private
            result["note_private"] = f"{withheld_private} matches are under private nodes and were withheld. Pass reveal=true to include them."
        if withheld_unplaced:
            result["withheld_unplaced"] = withheld_unplaced
            result["note_unplaced"] = f"{withheld_unplaced} unplaced matches have sensitivity 'private' and were withheld. Pass reveal=true to include them."
        return result

    def split(self, path: str, groups: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Tool: split(path, groups)
        groups = [{"name": "intermediate_name", "children": ["child1", "child2"]}]
        Moves existing child folders under new intermediate group directories.
        """
        clean_path = norm_path(path)
        if not self.store.exists(clean_path):
            raise FileNotFoundError(f"Node '{clean_path or '/'}' not found.")

        if not groups:
            raise ValueError("split() requires at least one group")

        validated_groups: List[Tuple[str, List[str]]] = []
        seen_group_names: Set[str] = set()
        all_moved: Set[str] = set()
        for grp in groups:
            raw_name = grp.get("name", "")
            grp_name = validate_segment(raw_name.strip() if isinstance(raw_name, str) else str(raw_name))
            if grp_name in seen_group_names:
                raise ValueError(f"Duplicate group name '{grp_name}'")
            seen_group_names.add(grp_name)
            children: List[str] = []
            for ch in grp.get("children", []):
                ch_name = validate_segment(ch.strip() if isinstance(ch, str) else str(ch))
                if ch_name in all_moved:
                    raise ValueError(f"Child '{ch_name}' is listed in more than one group")
                all_moved.add(ch_name)
                children.append(ch_name)
            validated_groups.append((grp_name, children))

        ndir = self.store.node_dir(clean_path)
        new_children = []

        with self.store.lock_paths([clean_path], timeout=5.0):
            # Re-read fresh inside the lock so we never overwrite concurrent changes.
            fresh_node = self.store.read_node(clean_path)
            if not fresh_node:
                raise FileNotFoundError(f"Node '{clean_path or '/'}' not found.")

            existing_children = set(self.store.list_child_dirs(clean_path))
            existing_teasers = {c.get("label"): c.get("teaser", "") for c in fresh_node.children}
            for grp_name, children in validated_groups:
                for ch in children:
                    if ch not in existing_children:
                        raise ValueError(f"Child '{ch}' does not exist under '{clean_path or '/'}'")
                if grp_name in existing_children and grp_name not in all_moved:
                    raise ValueError(
                        f"Group name '{grp_name}' equals an existing child that is not being moved"
                    )
                dest = ndir / grp_name
                if dest.exists():
                    raise ValueError(f"Destination '{grp_name}' already exists")

            for grp_name, children in validated_groups:
                grp_dir = ndir / grp_name
                grp_dir.mkdir(parents=True, exist_ok=True)

                grp_children = []
                for ch in children:
                    ch_src = ndir / ch
                    ch_dst = grp_dir / ch
                    if ch_src.exists() and ch_src.is_dir():
                        os.rename(ch_src, ch_dst)
                        grp_children.append({"label": ch, "teaser": existing_teasers.get(ch, f"Details on {ch}")})

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

            # Keep non-moved children and their carefully-written teasers.
            retained = [c for c in existing_children if c not in all_moved]
            new_children.extend({"label": ch, "teaser": existing_teasers.get(ch, f"Details on {ch}")} for ch in sorted(retained))
            fresh_node.children = new_children
            fresh_node.dirty = True
            self.store.write_node_atomic(clean_path, fresh_node)

        # Refresh index for affected nodes instead of full rebuild
        # Refresh the parent node
        parent_node = self.store.read_node(clean_path)
        if parent_node:
            self.index.refresh_node(clean_path, {
                "name": parent_node.name,
                "summary": parent_node.summary,
                "aliases": parent_node.aliases,
                "sensitivity": parent_node.sensitivity,
            })
        # Refresh each new group node
        for grp_name, _ in validated_groups:
            grp_path = f"{clean_path}/{grp_name}" if clean_path else grp_name
            grp_node = self.store.read_node(grp_path)
            if grp_node:
                self.index.refresh_node(grp_path, {
                    "name": grp_node.name,
                    "summary": grp_node.summary,
                    "aliases": grp_node.aliases,
                    "sensitivity": grp_node.sensitivity,
                })
        # Rebuild transclusion index (this is fast)
        self.transclusion_mgr.rebuild_index(self.health_checker.get_all_node_paths())
        
        return {"ok": True, "path": clean_path or "/", "new_groups": [g[0] for g in validated_groups]}

    def rebuild(self, path: Optional[str] = None) -> Dict[str, Any]:
        """
        Tool / Command: rebuild(path=None)
        Rebuild tree from append-only log facts.
        """
        all_entries = self.log_writer.read_all_entries()
        rebuilt_count = 0
        errors: List[Dict[str, str]] = []

        # Ensure root exists
        self.init_tree()

        journal = self._placement_records()
        placed = self._placed_entry_ids()
        requested_path = norm_path(path) if path else None
        for bad_key, bad in journal.items():
            if bad_key.startswith("__error__"):
                errors.append(bad)

        for entry in all_entries:
            eid = entry["entry_id"]
            record = journal.get(eid, {})
            try:
                target_path = record.get("path") or norm_path(entry.get("hint", "") or "general") or "general"
            except ValueError as exc:
                errors.append({"entry_id": eid, "error": str(exc)})
                continue
            if requested_path and requested_path != target_path:
                continue
            if eid in placed:
                continue
            try:
                self.place(
                    entry_id=eid, path=target_path,
                    sensitivity=record.get("sensitivity", entry.get("sensitivity", "normal")),
                    volatile=bool(record.get("volatile", False)), record_journal=False,
                )
                rebuilt_count += 1
                placed.add(eid)
            except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
                errors.append({"entry_id": eid, "error": str(exc)})

        self.rebuild_index()
        return {"ok": not errors, "rebuilt_facts": rebuilt_count, "errors": errors}
