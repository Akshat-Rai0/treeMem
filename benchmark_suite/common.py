"""Environment and manifest helpers."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

from .schemas import GENERATOR_VERSION, SCHEMA_VERSION, sha256_file, json_dump, jsonl_dump, jsonl_load, json_load

ROOT = Path(__file__).resolve().parents[1]


def git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def dependency_versions() -> Dict[str, str]:
    names = [
        "rank-bm25", "tiktoken", "scikit-learn", "sentence-transformers", "torch",
        "transformers", "numpy", "matplotlib", "scipy", "pandas", "pytest", "mcp",
        "fastapi", "uvicorn", "httpx", "treemem",
    ]
    out = {}
    try:
        import importlib.metadata as md
        for name in names:
            try:
                out[name] = md.version(name)
            except Exception:
                out[name] = None
    except Exception:
        pass
    return out


def environment_manifest(extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    manifest = {
        "suite": "treemem-comprehensive-benchmark",
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "git_revision": git_revision(),
        "dependencies": dependency_versions(),
        "env": {
            "python": sys.executable,
            "treemem_embedding_provider": os.environ.get("TREEMEM_EMBEDDING_PROVIDER"),
            "treemem_allow_reveal": os.environ.get("TREEMEM_ALLOW_REVEAL"),
            "benchmark_llm_base_url_set": bool(os.environ.get("BENCHMARK_LLM_BASE_URL")),
            "benchmark_llm_api_key_set": bool(os.environ.get("BENCHMARK_LLM_API_KEY")),
        },
    }
    if extra:
        manifest.update(extra)
    return manifest


def file_manifest(path: Path) -> Dict[str, Any]:
    path = Path(path)
    files = []
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return {
        "path": str(path),
        "sha256": hashlib.sha256("".join(sha256_file(p) for p in files).encode()).hexdigest(),
        "file_count": len(files),
        "files": [{"path": str(p.relative_to(path if path.is_dir() else p.parent)), "sha256": sha256_file(p), "bytes": p.stat().st_size} for p in files],
    }


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
