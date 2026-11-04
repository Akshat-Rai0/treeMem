"""Storage engine for TreeMem: atomic markdown writes, frontmatter, and file locking."""

try:
    import fcntl
except ImportError:  # pragma: no cover - platform guard
    fcntl = None
import hashlib
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from treemem.tokenizer import count_tokens

FACT_PATTERN = re.compile(r"^-\s+(.*?)\s+\(log:\s*([^)]+)\)\s*(?:\[(volatile)\])?\s*$", re.MULTILINE)
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
        if fcntl is None:
            raise RuntimeError("TreeMem currently supports macOS and Linux only")
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
        """Remove only stale temp files; another process may be writing a fresh one."""
        for tmp_file in self.root_dir.rglob("*.tmp"):
            try:
                if time.time() - tmp_file.stat().st_mtime > 60:
                    tmp_file.unlink()
            except Exception:
                pass

    def node_dir(self, norm_path: str) -> Path:
        """Resolve a normalized relative path (e.g. '', 'identity', 'identity/age') to directory.

        Defense in depth: the resolved path must stay inside root_dir.
        """
        clean = (norm_path or "").strip("/").strip()
        root = self.root_dir.resolve()
        if not clean:
            return root
        candidate = (root / clean).resolve()
        if candidate != root and not candidate.is_relative_to(root):
            raise ValueError(f"Path '{norm_path}' is outside the memory vault")
        return candidate

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

    def find_case_conflict(self, norm_path: str) -> Optional[Tuple[str, str]]:
        """
        Return (requested_path, existing_path) if any segment of norm_path differs only by
        letter case from an existing sibling directory, else None.

        Case-insensitive filesystems (macOS default, Windows) would silently map such names
        onto the same directory while the tree treats them as two nodes.
        """
        prefix = ""
        for seg in [s for s in norm_path.split("/") if s]:
            siblings = self.list_child_dirs(prefix)
            for sib in siblings:
                if sib != seg and sib.casefold() == seg.casefold():
                    requested = f"{prefix}/{seg}" if prefix else seg
                    existing = f"{prefix}/{sib}" if prefix else sib
                    return requested, existing
            if seg not in siblings:
                return None  # everything below is new, no further siblings to compare
            prefix = f"{prefix}/{seg}" if prefix else seg
        return None

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
            is_vol = bool(m.group(3))
            facts.append({"fact": fact_text, "entry_id": entry_id, "volatile": is_vol})

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
            facts_text = "\n".join(
                f"- {f['fact']} (log: {f['entry_id']})" + (" [volatile]" if f.get("volatile") else "")
                for f in node.facts
            )
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
        tmp_file = ndir / f"summary.md.{os.getpid()}.{uuid.uuid4().hex}.tmp"

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
                # Digest avoids the old a/b == a__b collision while keeping names portable.
                lock_name = "root.lock" if not p else hashlib.sha1(p.encode("utf-8")).hexdigest() + ".lock"
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
