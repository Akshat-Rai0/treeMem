"""Storage engine for TreeMem: atomic markdown writes, frontmatter, and file locking."""

import fcntl
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from treemem.tokenizer import count_tokens

FACT_PATTERN = re.compile(r"^-\s+(.*?)\s+\(log:\s*([^)]+)\)\s*$", re.MULTILINE)
CHILD_LINE_PATTERN = re.compile(r"^-\s+\[\[([^\]]+)\]\]\s*(?:-\s*(.*))?$", re.MULTILINE)


class NodeData:
    def __init__(
        self,
        name: str,
        summary: str = "",
        children: Optional[List[Dict[str, str]]] = None,
        facts: Optional[List[Dict[str, str]]] = None,
        aliases: Optional[List[str]] = None,
        dirty: bool = False,
        updated: Optional[str] = None,
        tokens: int = 0,
        sensitivity: str = "normal",
        children_cap: int = 12,
    ):
        self.name = name
        self.summary = summary.strip()
        self.children = children if children is not None else []  # list of {"label": ..., "teaser": ...}
        self.facts = facts if facts is not None else []  # list of {"fact": ..., "entry_id": ...}
        self.aliases = aliases if aliases is not None else []
        self.dirty = dirty
        self.updated = updated or datetime.now(timezone.utc).isoformat()
        self.tokens = tokens
        self.sensitivity = sensitivity
        self.children_cap = children_cap


class Store:
    """Manages the disk store of node markdown files, locks, and atomic operations."""

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.root_dir.chmod(0o700)
        except Exception:
            pass
        self.lock_dir = self.root_dir / ".locks"
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup_temp_files()

    def cleanup_temp_files(self) -> None:
        """Clean up any stray .tmp files from previous killed processes."""
        for tmp_file in self.root_dir.rglob("*.tmp"):
            try:
                tmp_file.unlink()
            except Exception:
                pass

    def node_dir(self, norm_path: str) -> Path:
        """Resolve a normalized relative path (e.g. '', 'identity', 'identity/age') to directory."""
        clean = norm_path.strip("/").strip()
        if not clean:
            return self.root_dir
        return self.root_dir / clean

    def summary_file(self, norm_path: str) -> Path:
        return self.node_dir(norm_path) / "summary.md"

    def exists(self, norm_path: str) -> bool:
        return self.summary_file(norm_path).exists()

    def is_leaf(self, norm_path: str) -> bool:
        """A leaf node has no child directories containing summary.md."""
        ndir = self.node_dir(norm_path)
        if not ndir.exists() or not ndir.is_dir():
            return True
        subdirs = [
            d for d in ndir.iterdir()
            if d.is_dir() and not d.name.startswith(".") and d.name != "log" and (d / "summary.md").exists()
        ]
        return len(subdirs) == 0

    def list_child_dirs(self, norm_path: str) -> List[str]:
        """List subdirectories under norm_path that are child nodes (ignoring hidden & log)."""
        ndir = self.node_dir(norm_path)
        if not ndir.exists() or not ndir.is_dir():
            return []
        children = []
        for d in sorted(ndir.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name != "log":
                if (d / "summary.md").exists():
                    children.append(d.name)
        return children

    def parse_summary_md(self, text: str) -> Tuple[Dict[str, Any], str, List[Dict[str, str]], List[Dict[str, str]]]:
        """Parse summary.md text into (frontmatter, summary_body, children_list, facts_list)."""
        frontmatter: Dict[str, Any] = {}
        body = text

        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    loaded = yaml.safe_load(parts[1])
                    if isinstance(loaded, dict):
                        frontmatter = loaded
                except Exception:
                    frontmatter = {}
                body = parts[2]

        # Extract ## Children section
        children: List[Dict[str, str]] = []
        facts: List[Dict[str, str]] = []

        children_split = re.split(r"^##\s+Children\s*$", body, flags=re.MULTILINE)
        main_body = children_split[0]
        children_body = children_split[1] if len(children_split) > 1 else ""

        # Parse children from ## Children section
        if children_body:
            for line in children_body.splitlines():
                line = line.strip()
                m = CHILD_LINE_PATTERN.match(line)
                if m:
                    label = m.group(1).strip()
                    teaser = (m.group(2) or "").strip()
                    children.append({"label": label, "teaser": teaser})

        # Parse leaf facts from main_body (or anywhere)
        for m in FACT_PATTERN.finditer(main_body):
            fact_text = m.group(1).strip()
            entry_id = m.group(2).strip()
            facts.append({"fact": fact_text, "entry_id": entry_id})

        # Clean summary body: remove leaf fact lines
        summary_lines = []
        for line in main_body.splitlines():
            if not FACT_PATTERN.match(line.strip()):
                summary_lines.append(line)
        clean_summary = "\n".join(summary_lines).strip()

        return frontmatter, clean_summary, children, facts

    def read_node(self, norm_path: str) -> Optional[NodeData]:
        """Read and parse summary.md for a given path."""
        sfile = self.summary_file(norm_path)
        if not sfile.exists():
            return None

        try:
            with open(sfile, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return None

        fm, summary, children, facts = self.parse_summary_md(content)

        name = fm.get("name") or (norm_path.split("/")[-1] if norm_path else "root")
        aliases = fm.get("aliases") or []
        dirty = bool(fm.get("dirty", False))
        updated = fm.get("updated")
        tokens = fm.get("tokens", 0)
        sensitivity = fm.get("sensitivity", "normal")
        children_cap = fm.get("children_cap", 12)

        return NodeData(
            name=name,
            summary=summary,
            children=children,
            facts=facts,
            aliases=aliases,
            dirty=dirty,
            updated=updated,
            tokens=tokens,
            sensitivity=sensitivity,
            children_cap=children_cap,
        )

    def serialize_node(self, node: NodeData) -> str:
        """Format NodeData into canonical markdown with frontmatter and ## Children."""
        frontmatter = {
            "name": node.name,
            "aliases": node.aliases,
            "dirty": bool(node.dirty),
            "updated": node.updated or datetime.now(timezone.utc).isoformat(),
            "tokens": int(node.tokens),
            "sensitivity": str(node.sensitivity),
            "children_cap": int(node.children_cap),
        }

        fm_yaml = yaml.dump(frontmatter, sort_keys=False, default_flow_style=None).strip()

        parts = [f"---\n{fm_yaml}\n---"]

        if node.summary:
            parts.append(node.summary)

        if node.facts:
            facts_text = "\n".join(f"- {f['fact']} (log: {f['entry_id']})" for f in node.facts)
            parts.append(facts_text)

        if node.children:
            child_lines = ["## Children"]
            for ch in node.children:
                teaser = ch.get("teaser", "").strip()
                label = ch.get("label", "").strip()
                if teaser:
                    child_lines.append(f"- [[{label}]] - {teaser}")
                else:
                    child_lines.append(f"- [[{label}]]")
            parts.append("\n".join(child_lines))

        return "\n\n".join(p for p in parts if p) + "\n"

    def write_node_atomic(self, norm_path: str, node: NodeData) -> None:
        """Write node to summary.md atomically using temp-file and replace."""
        ndir = self.node_dir(norm_path)
        ndir.mkdir(parents=True, exist_ok=True)
        try:
            ndir.chmod(0o700)
        except Exception:
            pass

        # Calculate token count if not preset or zero
        rendered_content = self.serialize_node(node)
        node.tokens = count_tokens(node.summary)
        # re-serialize with updated token count
        final_content = self.serialize_node(node)

        sfile = self.summary_file(norm_path)
        tmp_file = ndir / "summary.md.tmp"

        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(final_content)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_file, sfile)

    @contextmanager
    def lock_paths(self, paths: List[str], timeout: float = 5.0):
        """
        Acquire file locks in strict root-to-leaf top-down order to prevent deadlock.
        Throws TimeoutError / RuntimeError if busy after timeout.
        """
        # Normalize and sort paths top-down (shorter paths first, then lexicographically)
        clean_paths = sorted(
            list({p.strip("/").strip() for p in paths}),
            key=lambda p: (p.count("/"), len(p), p)
        )

        lock_fds: List[int] = []
        start_time = time.time()

        try:
            for p in clean_paths:
                lock_name = "root.lock" if not p else p.replace("/", "__") + ".lock"
                lock_path = self.lock_dir / lock_name

                # Open or create lock file
                fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
                lock_fds.append(fd)

                # Attempt non-blocking lock with retry until timeout
                locked = False
                while time.time() - start_time < timeout:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except (BlockingIOError, OSError):
                        time.sleep(0.02)

                if not locked:
                    raise TimeoutError(f"Could not acquire lock for path '{p}' within {timeout}s (server busy)")

            yield
        finally:
            for fd in reversed(lock_fds):
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except Exception:
                    pass
                try:
                    os.close(fd)
                except Exception:
                    pass
