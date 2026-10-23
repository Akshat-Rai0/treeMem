"""Health and invariant verification for TreeMem."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from treemem.log_writer import LogWriter
from treemem.store import Store


class HealthChecker:
    """Verifies all system invariants and reports health status."""

    def __init__(self, store: Store, log_writer: LogWriter):
        self.store = store
        self.log_writer = log_writer

    def get_all_node_paths(self) -> List[str]:
        """Return all relative node paths in the tree ('' for root)."""
        paths = [""]
        for p in self.store.root_dir.rglob("summary.md"):
            rel_dir = p.parent.relative_to(self.store.root_dir)
            rel_str = str(rel_dir).strip(".")
            if rel_str and not rel_str.startswith(".") and rel_str != "log":
                paths.append(rel_str)
        return sorted(list(set(paths)))

    def check_all(self) -> Dict[str, Any]:
        """Run all invariant checks and return health summary."""
        violations: List[Dict[str, Any]] = []

        # Invariant 7: Stray .tmp files
        tmp_files = list(self.store.root_dir.rglob("*.tmp"))
        if tmp_files:
            for tf in tmp_files:
                violations.append({
                    "invariant": 7,
                    "path": str(tf.relative_to(self.store.root_dir)),
                    "message": f"Found stray temporary file {tf.name}",
                })

        # Invariant 8: Log integrity
        all_entries = self.log_writer.read_all_entries()
        entry_ids = {e["entry_id"] for e in all_entries}
        for log_file in sorted(self.log_writer.log_dir.glob("*.md")):
            date_str = log_file.stem
            expected_line = 1
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    parsed = self.log_writer._parse_line(date_str, line)
                    if not parsed or parsed["line"] != expected_line:
                        violations.append({
                            "invariant": 8,
                            "path": f"log/{log_file.name}",
                            "message": f"Log line number gap or mismatch: expected {expected_line}, got {parsed.get('line') if parsed else 'invalid'}",
                        })
                    expected_line += 1

        # Scan all directories in the tree (excluding .events, .locks, log)
        total_nodes = 0
        total_facts = 0
        dirty_paths: List[str] = []

        all_dirs: List[Path] = [self.store.root_dir]
        for d in self.store.root_dir.rglob("*"):
            if d.is_dir():
                rel = d.relative_to(self.store.root_dir)
                parts = rel.parts
                if not any(p.startswith(".") or p == "log" for p in parts):
                    all_dirs.append(d)

        # Invariant 1: Every node directory has summary.md
        for d in all_dirs:
            norm_path = str(d.relative_to(self.store.root_dir)).strip(".")
            summary_path = d / "summary.md"
            if not summary_path.exists():
                violations.append({
                    "invariant": 1,
                    "path": norm_path,
                    "message": f"Directory '{norm_path or '/'}' is missing summary.md",
                })
            else:
                total_nodes += 1

        # Check nodes
        node_paths = self.get_all_node_paths()
        nodes_data: Dict[str, Any] = {}
        for p in node_paths:
            node = self.store.read_node(p)
            if node:
                nodes_data[p] = node
                if node.dirty:
                    dirty_paths.append(p)
                total_facts += len(node.facts)

        # Invariant 2: Every fact in a leaf references an existing log entry
        for p, node in nodes_data.items():
            for f in node.facts:
                eid = f.get("entry_id")
                if not eid or eid not in entry_ids:
                    violations.append({
                        "invariant": 2,
                        "path": p,
                        "message": f"Fact '{f.get('fact')}' references non-existent log entry '{eid}'",
                    })

        # Invariant 3: ## Children in summary equals set of child directories
        for p, node in nodes_data.items():
            child_dirs = set(self.store.list_child_dirs(p))
            child_labels = {c.get("label", "").strip() for c in node.children}
            if child_dirs != child_labels:
                missing = child_dirs - child_labels
                extra = child_labels - child_dirs
                msg_parts = []
                if missing:
                    msg_parts.append(f"missing children in summary: {list(missing)}")
                if extra:
                    msg_parts.append(f"extra children not on disk: {list(extra)}")
                violations.append({
                    "invariant": 3,
                    "path": p,
                    "message": f"Children mismatch for '{p or '/'}': {', '.join(msg_parts)}",
                })

        # Invariant 5: No private child text in any ancestor summary
        for p, node in nodes_data.items():
            if node.sensitivity == "private":
                # Check all ancestors
                parts = p.split("/")
                ancestor_paths = []
                for i in range(len(parts)):
                    anc = "/".join(parts[:i])
                    ancestor_paths.append(anc)

                private_tokens = set(re.findall(r"\b\w{4,}\b", (node.summary + " " + " ".join(f["fact"] for f in node.facts)).lower()))

                for anc in ancestor_paths:
                    anc_node = nodes_data.get(anc)
                    if anc_node:
                        # Check substring leakage
                        if node.summary and len(node.summary) > 10 and node.summary.lower() in anc_node.summary.lower():
                            violations.append({
                                "invariant": 5,
                                "path": anc,
                                "message": f"Ancestor '{anc or '/'}' contains exact summary of private node '{p}'",
                            })
                        # Check high token overlap of distinctive words (>= 4 words)
                        anc_words = set(re.findall(r"\b\w{4,}\b", anc_node.summary.lower()))
                        overlap = private_tokens.intersection(anc_words)
                        if len(overlap) >= 5:
                            violations.append({
                                "invariant": 5,
                                "path": anc,
                                "message": f"Ancestor '{anc or '/'}' leaks private content from '{p}' (overlap: {list(overlap)[:5]})",
                            })

        # Invariant 6: Dirty propagation consistency (clean node cannot have dirty descendant)
        for p, node in nodes_data.items():
            if not node.dirty:
                # Check all descendants
                prefix = p + "/" if p else ""
                dirty_descendants = [
                    d for d in dirty_paths
                    if d.startswith(prefix) and d != p
                ]
                if dirty_descendants:
                    violations.append({
                        "invariant": 6,
                        "path": p,
                        "message": f"Clean node '{p or '/'}' has dirty descendants: {dirty_descendants}",
                    })

        return {
            "ok": len(violations) == 0,
            "violations": violations,
            "dirty_count": len(dirty_paths),
            "dirty_paths": dirty_paths,
            "total_nodes": total_nodes,
            "total_facts": total_facts,
        }
