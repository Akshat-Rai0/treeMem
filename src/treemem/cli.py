"""TreeMem Command Line Interface."""

import argparse
import asyncio
import os
import secrets
import shutil
import sys
import threading
import time
from pathlib import Path

import uvicorn

from treemem.dashboard.server import create_app
from treemem.health import HealthChecker
from treemem.mcp_layer import run_mcp_server
from treemem.tree_manager import TreeManager


def cmd_init(args):
    target = Path(args.path or "memory").resolve()
    mgr = TreeManager(target)
    print(f"TreeMem initialized memory vault at: {target}")
    health = mgr.health_checker.check_all()
    print(f"Status: Healthy={health['ok']} | Nodes={health['total_nodes']}")


def cmd_check(args):
    target = Path(args.path or "memory").resolve()
    mgr = TreeManager(target)
    health = mgr.health_checker.check_all()

    print(f"Checking TreeMem vault at: {target}")
    print(f"Total Nodes: {health['total_nodes']} | Total Facts: {health['total_facts']} | Dirty: {health['dirty_count']}")

    if health["dirty_paths"]:
        print("\nDirty Nodes needing compression:")
        for p in health["dirty_paths"]:
            print(f"  - {p or '/'}")

    if not health["ok"]:
        print(f"\n[FAIL] Found {len(health['violations'])} invariant violations:")
        for v in health["violations"]:
            print(f"  [Invariant {v['invariant']}] {v['path']}: {v['message']}")
        sys.exit(1)
    else:
        print("\n[PASS] All 8 system invariants satisfied. Tree is completely healthy.")
        sys.exit(0)


def cmd_rebuild(args):
    target = Path(args.path or "memory").resolve()
    mgr = TreeManager(target)
    print(f"Rebuilding tree from append-only log at {target}...")
    res = mgr.rebuild()
    print(f"Rebuilt successfully! Facts restored: {res['rebuilt_facts']}")


def cmd_compress(args):
    from treemem.auto_compress import AutoCompressor
    target = Path(args.path or "memory").resolve()
    mgr = TreeManager(target)
    compressor = AutoCompressor(mgr)

    if args.node:
        print(f"Auto-compressing node: '{args.node}' at {target}...")
        res = compressor.compress_node(args.node)
        if res.get("ok"):
            print(f"[SUCCESS] Node '{res['path']}' compressed ({res['tokens']} tokens) in {res['attempts']} attempt(s).")
        else:
            print(f"[FAIL] Failed to compress '{args.node}': {res.get('error')}")
            sys.exit(1)
    else:
        print(f"Finding and auto-compressing all dirty nodes at {target}...")
        res = compressor.compress_all_dirty()
        print(f"Result: Cleaned={res['cleaned_count']} | Errors={res['error_count']}")
        for c in res["cleaned_nodes"]:
            print(f"  - Cleaned: {c['path']} ({c['tokens']} tokens)")
        for e in res["errors"]:
            print(f"  - Error in {e['path']}: {e['error']}")
        if not res["ok"]:
            sys.exit(1)


def run_demo_script(mgr: TreeManager):
    """Run scripted demo sequence for the dashboard demo mode."""
    time.sleep(1.5)
    # Scripted call 1: "What's my name?" -> parent-stop at depth 0
    mgr.recall(path="/", query_id="demo-q1")
    time.sleep(2.0)

    # Scripted call 2: "What is my age?" -> root -> identity -> age (depth 2)
    mgr.recall(path="identity", query_id="demo-q2")
    time.sleep(1.0)
    mgr.expand(path="identity/age", query_id="demo-q2")
    time.sleep(2.0)

    # Scripted call 3: Write a new fact to make college stale
    rem = mgr.remember("User enrolled in Advanced Algorithms", hint="college")
    mgr.place(rem["entry_id"], "college/courses")
    time.sleep(2.5)

    # Scripted call 4: Compress dirty node
    comp = mgr.compress("college")
    mgr.commit_summary(
        "college",
        "---\nname: college\ndirty: false\n---\nAcademic studies and course enrollments.\n\n## Children\n- [[courses]] - current course enrollments\n",
    )


def cmd_serve(args):
    if args.mcp:
        run_mcp_server(args.path or "memory")
        return

    target = Path(args.path or "memory").resolve()

    if args.demo:
        # Load sample demo memory
        sample_src = Path(__file__).parent.parent.parent / "examples" / "sample_memory"
        demo_dir = Path("/tmp/treemem_demo")
        if demo_dir.exists():
            shutil.rmtree(demo_dir)
        if sample_src.exists():
            shutil.copytree(sample_src, demo_dir)
        else:
            demo_dir.mkdir(parents=True, exist_ok=True)
        target = demo_dir

    mgr = TreeManager(target)
    token = secrets.token_urlsafe(16)
    port = args.port or 8765
    host = "127.0.0.1"

    app = create_app(mgr, token)

    url = f"http://{host}:{port}/?t={token}"
    print("=" * 60)
    print(" TreeMem Memory X-Ray Dashboard")
    print(f" Vault path: {target}")
    print(f" Access URL: {url}")
    print("=" * 60)

    if getattr(args, "auto_compress", False):
        from treemem.auto_compress import AutoCompressor
        compressor = AutoCompressor(mgr)
        compressor.start_background_worker(interval_seconds=30.0)
        print("[Auto-Compressor] Background worker active (30s interval)")

    if args.demo:
        print("[Demo Mode] Scripted recall sequence starting in 1.5s...")
        t = threading.Thread(target=run_demo_script, args=(mgr,), daemon=True)
        t.start()

    uvicorn.run(app, host=host, port=port, log_level="warning")


def main():
    parser = argparse.ArgumentParser(description="TreeMem: Hierarchical Agent Memory CLI")
    subparsers = parser.add_subparsers(dest="command")

    # init
    p_init = subparsers.add_parser("init", help="Initialize a new memory vault")
    p_init.add_argument("path", nargs="?", default="memory", help="Path to memory vault directory")

    # check
    p_check = subparsers.add_parser("check", help="Run health check and invariant validations")
    p_check.add_argument("path", nargs="?", default="memory", help="Path to memory vault directory")

    # rebuild
    p_reb = subparsers.add_parser("rebuild", help="Rebuild the tree from append-only log")
    p_reb.add_argument("path", nargs="?", default="memory", help="Path to memory vault directory")

    # compress
    p_cmp = subparsers.add_parser("compress", help="Auto-compress dirty nodes using server-side LLM (Option B)")
    p_cmp.add_argument("path", nargs="?", default="memory", help="Path to memory vault directory")
    p_cmp.add_argument("--node", help="Specific node path to compress (default: all dirty nodes bottom-up)")

    # serve
    p_srv = subparsers.add_parser("serve", help="Serve the dashboard or stdio MCP server")
    p_srv.add_argument("path", nargs="?", default="memory", help="Path to memory vault directory")
    p_srv.add_argument("--port", type=int, default=8765, help="Port for web dashboard")
    p_srv.add_argument("--demo", action="store_true", help="Launch demo mode with sample memory & sequence")
    p_srv.add_argument("--mcp", action="store_true", help="Run as stdio MCP server instead of HTTP dashboard")
    p_srv.add_argument("--auto-compress", action="store_true", help="Run background worker to automatically compress dirty nodes")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "rebuild":
        cmd_rebuild(args)
    elif args.command == "compress":
        cmd_compress(args)
    elif args.command == "serve":
        cmd_serve(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
