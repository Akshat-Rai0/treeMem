"""FastAPI backend for TreeMem X-Ray Dashboard."""

import asyncio
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from treemem.tokenizer import count_tokens
from treemem.tree_manager import TreeManager, norm_path


# ---------------------------------------------------------------------------
# Request bodies for write endpoints
# ---------------------------------------------------------------------------

class CompressRequest(BaseModel):
    path: str


class EditSummaryRequest(BaseModel):
    path: str
    text: str

security = HTTPBearer(auto_error=False)


def create_app(tree_manager: TreeManager, token: str) -> FastAPI:
    app = FastAPI(title="TreeMem Dashboard", docs_url=None, redoc_url=None)
    static_dir = Path(__file__).parent / "static"

    def verify_token(
        req: Request,
        t: Optional[str] = Query(None),
        auth: Optional[HTTPAuthorizationCredentials] = Security(security),
    ):
        provided = t or (auth.credentials if auth else None)
        # Also check Authorization header directly
        if not provided:
            auth_header = req.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                provided = auth_header[7:].strip()
        if not provided or not secrets.compare_digest(provided, token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing dashboard token. Check terminal output for access URL with ?t=<token>.",
            )
        return True

    @app.get("/")
    async def get_index(t: Optional[str] = None):
        index_file = static_dir / "index.html"
        if not index_file.exists():
            return HTMLResponse("<h1>TreeMem Dashboard UI static files not found</h1>", status_code=404)
        return FileResponse(index_file)

    @app.get("/api/tree")
    async def get_tree(
        root: str = "",
        depth: int = 10,
        authorized: bool = Depends(verify_token),
    ):
        clean_root = norm_path(root)
        all_paths = tree_manager.health_checker.get_all_node_paths()

        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []

        for p in all_paths:
            # Filter by root and depth if requested
            if clean_root and p != clean_root and not p.startswith(clean_root + "/"):
                continue
            rel_depth = (p.count("/") - clean_root.count("/")) if clean_root else (0 if not p else p.count("/") + 1)
            if rel_depth > depth:
                continue

            node_data = tree_manager.store.read_node(p)
            if not node_data:
                continue

            child_dirs = tree_manager.store.list_child_dirs(p)
            nodes.append({
                "path": p or "/",
                "id": p or "root",
                "label": node_data.name or "root",
                "summary": node_data.summary,
                "tokens": node_data.tokens or count_tokens(node_data.summary),
                "dirty": node_data.dirty,
                "sensitivity": node_data.sensitivity,
                "child_count": len(child_dirs),
                "depth": rel_depth,
            })

            # Hierarchy edges
            for ch in child_dirs:
                ch_path = f"{p}/{ch}" if p else ch
                edges.append({
                    "id": f"edge_{p or 'root'}_to_{ch_path}",
                    "source": p or "root",
                    "target": ch_path,
                    "type": "hierarchy",
                })

            # Secondary wikilink edges
            for ch in node_data.children:
                lbl = ch["label"]
                # if wikilink points to another node that is not a direct child
                if lbl not in child_dirs and lbl in [x.split("/")[-1] for x in all_paths]:
                    target_p = next((x for x in all_paths if x.split("/")[-1] == lbl), lbl)
                    edges.append({
                        "id": f"link_{p or 'root'}_to_{target_p}",
                        "source": p or "root",
                        "target": target_p,
                        "type": "wikilink",
                    })

        return {"nodes": nodes, "edges": edges}

    @app.get("/api/node")
    async def get_node(
        path: str,
        authorized: bool = Depends(verify_token),
    ):
        clean_path = norm_path(path)
        node = tree_manager.store.read_node(clean_path)
        if not node:
            raise HTTPException(status_code=404, detail=f"Node '{clean_path or '/'}' not found.")

        # Respect privacy: private node bodies withheld
        is_private = (node.sensitivity == "private")
        summary_text = "[Private details withheld]" if is_private else node.summary

        child_list = []
        for ch in node.children:
            ch_label = ch["label"]
            ch_path = f"{clean_path}/{ch_label}" if clean_path else ch_label
            ch_node = tree_manager.store.read_node(ch_path)
            teaser = ch.get("teaser", "")
            if ch_node and ch_node.sensitivity == "private":
                teaser = "contains private details, expand to view"
            child_list.append({"label": ch_label, "teaser": teaser})

        return {
            "path": clean_path or "/",
            "name": node.name,
            "summary": summary_text,
            "tokens": node.tokens or count_tokens(node.summary),
            "dirty": node.dirty,
            "sensitivity": node.sensitivity,
            "aliases": node.aliases,
            "updated": node.updated,
            "children": child_list,
            "fact_count": len(node.facts),
        }

    @app.get("/api/events")
    async def get_events(
        since: Optional[str] = None,
        limit: int = 100,
        authorized: bool = Depends(verify_token),
    ):
        events = tree_manager.event_bus.get_events(since=since, limit=limit)
        return {"events": events}

    @app.get("/api/stream")
    async def get_stream(
        req: Request,
        t: Optional[str] = Query(None),
    ):
        # Verify token for EventSource
        if not t or not secrets.compare_digest(t, token):
            raise HTTPException(status_code=401, detail="Unauthorized")

        queue = tree_manager.event_bus.subscribe()

        async def event_generator():
            try:
                while True:
                    if await req.is_disconnected():
                        break
                    try:
                        event_data = await asyncio.wait_for(queue.get(), timeout=20.0)
                        yield {
                            "event": "treemem_event",
                            "data": event_data,
                        }
                    except asyncio.TimeoutError:
                        # Send heartbeat comment to keep connection alive
                        yield {"event": "ping", "data": "heartbeat"}
            finally:
                tree_manager.event_bus.unsubscribe(queue)

        return EventSourceResponse(event_generator())

    @app.get("/api/health")
    async def get_health(authorized: bool = Depends(verify_token)):
        return tree_manager.health_checker.check_all()

    @app.get("/api/metrics")
    async def get_metrics(authorized: bool = Depends(verify_token)):
        events = tree_manager.event_bus.get_events(limit=500)
        recalls = [e for e in events if e.get("type") == "recall"]

        total_recalls = len(recalls)
        parent_stops = [r for r in recalls if r.get("depth", 0) == 0]
        dirty_hits = [r for r in recalls if r.get("dirty")]

        avg_tokens = (sum(r.get("tokens", 0) for r in recalls) / total_recalls) if total_recalls else 0

        # Calculate baseline flat-dump tokens
        all_paths = tree_manager.health_checker.get_all_node_paths()
        flat_facts_text = ""
        for p in all_paths:
            n = tree_manager.store.read_node(p)
            if n:
                for f in n.facts:
                    flat_facts_text += f["fact"] + "\n"
        baseline_flat_tokens = count_tokens(flat_facts_text)

        return {
            "total_recalls": total_recalls,
            "parent_stops": len(parent_stops),
            "parent_stop_rate": round(len(parent_stops) / total_recalls, 3) if total_recalls else 0.0,
            "dirty_hits": len(dirty_hits),
            "dirty_hit_rate": round(len(dirty_hits) / total_recalls, 3) if total_recalls else 0.0,
            "avg_tokens_per_recall": round(avg_tokens, 1),
            "baseline_flat_dump_tokens": baseline_flat_tokens,
        }

    # ------------------------------------------------------------------
    # Write endpoints (v2): scoped to compress and summary edit
    # ------------------------------------------------------------------

    @app.post("/api/node/compress")
    async def compress_node(
        body: CompressRequest,
        authorized: bool = Depends(verify_token),
    ):
        """Trigger AutoCompressor on a single node by path."""
        clean_path = norm_path(body.path)
        node = tree_manager.store.read_node(clean_path)
        if not node:
            raise HTTPException(status_code=404, detail=f"Node '{clean_path or '/'}' not found.")

        try:
            from treemem.auto_compress import AutoCompressor
            import os as _os

            groq_key = _os.environ.get("GROQ_API_KEY_1") or _os.environ.get("GROQ_API_KEY")
            if not groq_key:
                raise HTTPException(
                    status_code=503,
                    detail="No GROQ_API_KEY_1 or GROQ_API_KEY set. AutoCompressor requires a Groq key.",
                )

            compressor = AutoCompressor(
                tree_manager=tree_manager,
                api_key=groq_key,
            )
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: compressor.compress_node(clean_path),
            )
            return {"ok": True, "path": clean_path, "result": result}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/node/summary")
    async def edit_summary(
        body: EditSummaryRequest,
        authorized: bool = Depends(verify_token),
    ):
        """Manually overwrite a node's summary text."""
        clean_path = norm_path(body.path)
        node = tree_manager.store.read_node(clean_path)
        if not node:
            raise HTTPException(status_code=404, detail=f"Node '{clean_path or '/'}' not found.")

        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Summary text must not be empty.")

        # Hard limit: refuse edits > 4000 chars to protect token budget
        if len(text) > 4000:
            raise HTTPException(
                status_code=422,
                detail=f"Summary too long ({len(text)} chars). Max 4000 chars.",
            )

        try:
            tree_manager.commit_summary(clean_path, text)
            return {"ok": True, "path": clean_path, "tokens": count_tokens(text)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Mount static assets
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
