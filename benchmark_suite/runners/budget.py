"""Budget-constrained retrieval experiment runner.

Each arm retrieves once per query with a large candidate pool; the returned
context is decomposed into ordered units and greedily packed under each token
budget. Episodes are keyed by (arm, query, budget) and appended resumably.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..adapters.base import RetrievalResult
from ..adapters.treemem import TreeMemVault, build_arm
from ..budgeting import PACKER_VERSION, pack_to_budget, units_from_result
from ..common import environment_manifest, json_dump, jsonl_load
from ..metrics.ranking import evaluate_budget_ranking
from .retrieval import load_memories, load_queries

DEFAULT_BUDGETS = (256, 512, 1024, 1465, 2048, 4096)
# Cap on context units considered per query; protects corpus-order arms such
# as flat_all whose retrieve() ignores k and returns every memory.
UNIT_CAP = 1000


def episode_key(arm: str, query_id: str, budget: int, cfg_hash: str) -> str:
    return f"{arm}|{query_id}|budget={budget}|cfg={cfg_hash}"


def run_budget(
    dataset_dir: Path,
    out_dir: Path,
    arms: Sequence[str],
    budgets: Sequence[int] = DEFAULT_BUDGETS,
    split: str = "test",
    candidate_k: int = 200,
    limit: Optional[int] = None,
    repetitions: int = 1,
    config: Optional[Dict[str, Any]] = None,
    rebuild_vault: bool = False,
) -> Dict[str, Any]:
    config = config or {}
    dataset_dir = Path(dataset_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    budgets = sorted({int(b) for b in budgets})
    manifest_path = dataset_dir / "manifest.json"
    dataset_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    memories = load_memories(dataset_dir / dataset_manifest.get("memories_file", "memories.jsonl"))
    queries = load_queries(dataset_dir / dataset_manifest.get("queries_file", "queries.jsonl"), split=split, limit=limit)

    cfg_hash = str(abs(hash(json.dumps({"config": config, "budgets": budgets, "candidate_k": candidate_k, "packer": PACKER_VERSION}, sort_keys=True, default=str))))[:12]
    episodes_path = out_dir / "episodes.jsonl"
    done = {row.get("episode_key") for row in jsonl_load(episodes_path)}

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
        retrievers[arm] = build_arm(arm, memories, vault, k=candidate_k, config=config)
        index_timings[arm] = (time.perf_counter() - t0) * 1000

    manifest = environment_manifest({
        "experiment": "budget",
        "dataset_dir": str(dataset_dir),
        "dataset_manifest": dataset_manifest,
        "arms": list(arms),
        "budgets": budgets,
        "split": split,
        "candidate_k": candidate_k,
        "unit_cap": UNIT_CAP,
        "limit": limit,
        "repetitions": repetitions,
        "config": config,
        "config_hash": cfg_hash,
        "packer_version": PACKER_VERSION,
        "accounting": "final_payload_only",
        "vault_timings": vault_timings,
        "index_build_ms": index_timings,
    })
    json_dump(out_dir / "manifest.json", manifest)

    new_rows: List[Dict[str, Any]] = []
    total = len(arms) * len(queries) * repetitions * len(budgets)
    completed = len(done)
    episodes_file = episodes_path.open("a", encoding="utf-8")
    try:
        for rep in range(repetitions):
            for arm in arms:
                retriever = retrievers[arm]
                for query in queries:
                    rep_suffix = f"|rep={rep}" if repetitions > 1 else ""
                    pending = [
                        b for b in budgets
                        if episode_key(arm, query.query_id, b, cfg_hash) + rep_suffix not in done
                    ]
                    if not pending:
                        continue
                    qdict = query.to_dict()
                    t_ret = time.perf_counter()
                    result: RetrievalResult = retriever.retrieve(query, k=candidate_k, reveal=False)
                    retrieve_ms = (time.perf_counter() - t_ret) * 1000
                    units = units_from_result(result, unit_cap=UNIT_CAP)
                    result_meta = {k: v for k, v in (result.metadata or {}).items() if k != "budget_units"}
                    for budget in pending:
                        key = episode_key(arm, query.query_id, budget, cfg_hash) + rep_suffix
                        t_pack = time.perf_counter()
                        packed = pack_to_budget(units, budget)
                        pack_ms = (time.perf_counter() - t_pack) * 1000
                        packed_ids = list(dict.fromkeys(packed.packed_memory_ids))
                        metrics = evaluate_budget_ranking(packed_ids, qdict)
                        forbidden = [v for v in (query.forbidden_values or []) if v]
                        row = {
                            "episode_key": key,
                            "experiment": "budget",
                            "arm": arm,
                            "query_id": query.query_id,
                            "query_category": query.category,
                            "split": query.split,
                            "repetition": rep,
                            "budget": budget,
                            "candidate_k": candidate_k,
                            "config_hash": cfg_hash,
                            "packed_memory_ids": packed_ids,
                            "scores": [],
                            "context_tokens": packed.tokens_used,
                            "tokens_used": packed.tokens_used,
                            "utilization": packed.tokens_used / budget if budget else 0.0,
                            "units_included": packed.units_included,
                            "units_dropped": packed.units_dropped,
                            "truncated_units": packed.truncated_count,
                            "payload_tokens_final": result_meta.get("payload_tokens_final"),
                            "latency_ms": result.latency_ms,
                            "retrieve_ms": retrieve_ms,
                            "pack_ms": pack_ms,
                            "timings_ms": result.timings_ms,
                            "metadata": result_meta,
                            "error": result.error,
                            "metrics": metrics,
                            "privacy_leak_context": any(v in packed.context_text for v in forbidden),
                        }
                        episodes_file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                        completed += 1
                        if completed % 200 == 0:
                            episodes_file.flush()
                            print(f"progress {completed}/{total}", flush=True)
    finally:
        episodes_file.close()
    return {"episodes": str(episodes_path), "completed": completed, "total": total, "manifest": str(out_dir / "manifest.json")}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run budget-constrained retrieval benchmark")
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--arms", nargs="+", default=["bm25", "hybrid", "treemem_guided", "treemem_search"])
    ap.add_argument("--budgets", nargs="+", type=int, default=list(DEFAULT_BUDGETS))
    ap.add_argument("--split", default="test")
    ap.add_argument("--candidate-k", type=int, default=200)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--repetitions", type=int, default=1)
    ap.add_argument("--rebuild-vault", action="store_true")
    args = ap.parse_args(argv)
    print(json.dumps(run_budget(
        args.dataset, args.out, args.arms, args.budgets, args.split,
        candidate_k=args.candidate_k, limit=args.limit, repetitions=args.repetitions,
        rebuild_vault=args.rebuild_vault,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
