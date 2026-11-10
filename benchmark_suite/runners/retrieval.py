"""Retrieval experiment runner with resumable JSONL episodes."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..adapters.base import RetrievalResult
from ..adapters.treemem import TreeMemVault, build_arm
from ..common import ROOT, environment_manifest, json_dump, jsonl_dump, jsonl_load
from ..metrics.ranking import evaluate_ranking
from ..schemas import MemoryRecord, QueryRecord, jsonl_load as _unused  # noqa: F401
from ..schemas import jsonl_load as load_jsonl


def load_memories(path: Path) -> List[MemoryRecord]:
    return [MemoryRecord.from_dict(json.loads(l)) for l in Path(path).read_text().splitlines() if l.strip()]


def load_queries(path: Path, split: Optional[str] = None, limit: Optional[int] = None) -> List[QueryRecord]:
    rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    if split:
        rows = [r for r in rows if r.get("split") == split]
    queries = [QueryRecord.from_dict(r) for r in rows]
    if limit:
        queries = queries[:limit]
    return queries


def episode_key(arm: str, query_id: str, k: int, config_hash: str) -> str:
    return f"{arm}|{query_id}|k={k}|cfg={config_hash}"


def run_retrieval(
    dataset_dir: Path,
    out_dir: Path,
    arms: Sequence[str],
    split: str = "test",
    k: int = 10,
    limit: Optional[int] = None,
    repetitions: int = 1,
    config: Optional[Dict[str, Any]] = None,
    rebuild_vault: bool = False,
) -> Dict[str, Any]:
    config = config or {}
    dataset_dir = Path(dataset_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = dataset_dir / "manifest.json"
    dataset_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    memories = load_memories(dataset_dir / dataset_manifest.get("memories_file", "memories.jsonl"))
    queries = load_queries(dataset_dir / dataset_manifest.get("queries_file", "queries.jsonl"), split=split, limit=limit)

    cfg_hash = str(abs(hash(json.dumps(config, sort_keys=True, default=str))))[:12]
    episodes_path = out_dir / "episodes.jsonl"
    done = set()
    for row in jsonl_load(episodes_path):
        done.add(row.get("episode_key"))

    vault = None
    needs_vault = any(a.startswith("treemem_") for a in arms)
    vault_timings: Dict[str, Any] = {}
    if needs_vault:
        vault_root = out_dir / "vault"
        t0 = time.perf_counter()
        vault = TreeMemVault(memories, vault_root, rebuild=rebuild_vault)
        vault_timings["vault_build_ms"] = (time.perf_counter() - t0) * 1000
        meta_path = vault_root.parent / "vault_meta.json"
        if meta_path.exists():
            vault_timings.update(json.loads(meta_path.read_text()).get("timings_ms", {}))

    retrievers = {}
    index_timings: Dict[str, float] = {}
    for arm in arms:
        t0 = time.perf_counter()
        retrievers[arm] = build_arm(arm, memories, vault, k=k, config=config)
        index_timings[arm] = (time.perf_counter() - t0) * 1000

    manifest = environment_manifest({
        "experiment": "retrieval",
        "dataset_dir": str(dataset_dir),
        "dataset_manifest": dataset_manifest,
        "arms": list(arms),
        "split": split,
        "k": k,
        "limit": limit,
        "repetitions": repetitions,
        "config": config,
        "config_hash": cfg_hash,
        "vault_timings": vault_timings,
        "index_build_ms": index_timings,
    })
    json_dump(out_dir / "manifest.json", manifest)

    new_rows = []
    total = len(arms) * len(queries) * repetitions
    completed = len(done)
    for rep in range(repetitions):
        for arm in arms:
            retriever = retrievers[arm]
            for qi, query in enumerate(queries):
                key = episode_key(arm, query.query_id, k, cfg_hash) + (f"|rep={rep}" if repetitions > 1 else "")
                if key in done:
                    continue
                result: RetrievalResult = retriever.retrieve(query, k=k, reveal=False)
                qdict = query.to_dict()
                metrics = evaluate_ranking([i.memory_id for i in result.items], qdict, ks=(1, 3, 5, 10))
                row = {
                    "episode_key": key,
                    "experiment": "retrieval",
                    "arm": arm,
                    "query_id": query.query_id,
                    "query_category": query.category,
                    "split": query.split,
                    "repetition": rep,
                    "k": k,
                    "config_hash": cfg_hash,
                    "retrieved_memory_ids": [i.memory_id for i in result.items],
                    "scores": [i.score for i in result.items],
                    "context_tokens": result.context_tokens,
                    "latency_ms": result.latency_ms,
                    "timings_ms": result.timings_ms,
                    "metadata": result.metadata,
                    "error": result.error,
                    "metrics": metrics,
                    "privacy_leak_context": any(v in result.context_text for v in (query.forbidden_values or []) if v),
                }
                new_rows.append(row)
                completed += 1
                if completed % 100 == 0:
                    with episodes_path.open("a", encoding="utf-8") as f:
                        for r in new_rows:
                            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
                    new_rows = []
                    print(f"progress {completed}/{total}", flush=True)
    if new_rows:
        with episodes_path.open("a", encoding="utf-8") as f:
            for r in new_rows:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    return {"episodes": str(episodes_path), "completed": completed, "total": total, "manifest": str(out_dir / "manifest.json")}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run retrieval benchmark")
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--arms", nargs="+", default=["bm25", "treemem_guided", "treemem_search"])
    ap.add_argument("--split", default="test")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--repetitions", type=int, default=1)
    ap.add_argument("--rebuild-vault", action="store_true")
    args = ap.parse_args(argv)
    print(json.dumps(run_retrieval(args.dataset, args.out, args.arms, args.split, args.k, args.limit, args.repetitions, rebuild_vault=args.rebuild_vault), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
