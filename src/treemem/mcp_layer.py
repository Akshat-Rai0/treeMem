"""MCP Server layer for TreeMem using Model Context Protocol stdio transport."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from treemem.tree_manager import TreeManager

_MANAGER: Optional[TreeManager] = None


def get_manager(root_dir: Optional[str] = None) -> TreeManager:
    global _MANAGER
    if _MANAGER is None:
        target = root_dir or os.environ.get("TREEMEM_DIR", "memory")
        _MANAGER = TreeManager(Path(target))
    return _MANAGER


mcp = MCPServer("treemem")


@mcp.tool()
def remember(fact: str, hint: str = "") -> str:
    """
    Store a new fact in the append-only ground-truth log and receive placement candidates.

    Args:
        fact: The factual statement to remember.
        hint: Optional path hint where this fact might belong (e.g., 'identity/age').
    """
    mgr = get_manager()
    res = mgr.remember(fact=fact, hint=hint)
    return json.dumps(res, indent=2)


@mcp.tool()
def place(entry_id: str, path: str, sensitivity: str = "normal", volatile: bool = False) -> str:
    """
    Place a logged fact into a specific leaf node topic, dirtying ancestors (unless transcluded).

    Args:
        entry_id: The date#line ID returned by `remember`.
        path: Relative folder path (e.g. 'identity/age').
        sensitivity: 'normal' or 'private'.
        volatile: If True, indicates a volatile scalar fact that can be transcluded without dirtying embedding parents.
    """
    mgr = get_manager()
    res = mgr.place(entry_id=entry_id, path=path, sensitivity=sensitivity, volatile=volatile)
    return json.dumps(res, indent=2)


@mcp.tool()
def recall(path: str = "/") -> str:
    """
    Read a concise parent topic summary and one-line teasers for child topics.

    MUST NOT return child bodies. If the parent summary answers the query, stop here (parent-stop).

    Args:
        path: Path of the node to inspect ('/' for root).
    """
    mgr = get_manager()
    res = mgr.recall(path=path)
    return json.dumps(res, indent=2)


@mcp.tool()
def expand(path: str, reveal: bool = False) -> str:
    """
    Expand a node to inspect all its child summaries or leaf facts.

    Args:
        path: Path of the node to expand.
        reveal: If true, reveals facts/summaries of private nodes.
    """
    mgr = get_manager()
    res = mgr.expand(path=path, reveal=reveal)
    return json.dumps(res, indent=2)


@mcp.tool()
def compress(path: str) -> str:
    """
    Request a compression prompt and input summaries to re-summarize a dirty node.

    Args:
        path: Path of the node to compress.
    """
    mgr = get_manager()
    res = mgr.compress(path=path)
    return json.dumps(res, indent=2)


@mcp.tool()
def commit_summary(path: str, text: str) -> str:
    """
    Submit a rewritten summary for validation and atomic write to clear dirty status.

    Args:
        path: Path of the node.
        text: The complete markdown summary including frontmatter and '## Children' list.
    """
    mgr = get_manager()
    res = mgr.commit_summary(path=path, text=text)
    return json.dumps(res, indent=2)


@mcp.tool()
def auto_compress(path: Optional[str] = None) -> str:
    """
    Option B Auto-Summarizer: Automatically compress dirty nodes in the vault using server-side LLM.
    Compresses nodes in bottom-up topological order (deepest nodes first).

    Args:
        path: Optional specific path to compress. If omitted, compresses all dirty nodes in the vault.
    """
    from treemem.auto_compress import AutoCompressor
    mgr = get_manager()
    compressor = AutoCompressor(mgr)
    if path:
        res = compressor.compress_node(path)
    else:
        res = compressor.compress_all_dirty()
    return json.dumps(res, indent=2)


@mcp.tool()
def search(query: str, limit: int = 10) -> str:
    """
    Lexical BM25 search over all log entries and leaf notes (fallback when descent fails).

    Args:
        query: Search keywords.
        limit: Maximum results to return.
    """
    mgr = get_manager()
    res = mgr.search(query=query, limit=limit)
    return json.dumps(res, indent=2)


@mcp.tool()
def split(path: str, groups: List[Dict[str, Any]]) -> str:
    """
    Split an overflowing node into intermediate subtopics.

    Args:
        path: Path of the node exceeding children cap.
        groups: List of groups, e.g. [{"name": "group_a", "children": ["child1", "child2"]}]
    """
    mgr = get_manager()
    res = mgr.split(path=path, groups=groups)
    return json.dumps(res, indent=2)


@mcp.tool()
def rebuild(path: str = "") -> str:
    """
    Rebuild the tree (or a specific path) from the append-only log.

    Args:
        path: Optional path to rebuild. Empty string rebuilds the entire vault.
    """
    mgr = get_manager()
    res = mgr.rebuild(path=path or None)
    return json.dumps(res, indent=2)


@mcp.tool()
def status() -> str:
    """
    Get session-start memory status: count and paths of dirty nodes needing compression, and health.
    """
    mgr = get_manager()
    health = mgr.health_checker.check_all()
    dirty_nodes = mgr.get_dirty_nodes()
    return json.dumps({
        "status": "ready",
        "total_nodes": health["total_nodes"],
        "total_facts": health["total_facts"],
        "dirty_count": len(dirty_nodes),
        "dirty_nodes": dirty_nodes,
        "health_ok": health["ok"],
        "violations": health["violations"],
    }, indent=2)


def run_mcp_server(memory_dir: Optional[str] = None):
    """Run the MCP server over stdio."""
    if memory_dir:
        os.environ["TREEMEM_DIR"] = str(Path(memory_dir).resolve())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    dir_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_mcp_server(dir_arg)
