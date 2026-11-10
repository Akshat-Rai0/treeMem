"""Staged full-scale benchmark orchestrator.

Runs the benchmark suite in resumable steps and records per-step status in
``benchmark_suite/results/full_suite/status.json``.  Steps that already have
``status=completed`` are skipped, so the same command can be re-run to continue.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common import ROOT, json_dump

RESULTS = ROOT / "benchmark_suite" / "results" / "full_suite"
DATASETS = ROOT / "benchmark_suite" / "datasets"
SCALES = [100, 1000, 10000, 50000]
QUERIES = 2000
PY = sys.executable


def _status_path() -> Path:
    return RESULTS / "status.json"


def _load_status() -> Dict[str, Any]:
    p = _status_path()
    if p.exists():
        return json.loads(p.read_text())
    return {"steps": {}, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _save_status(status: Dict[str, Any]) -> None:
    status["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json_dump(_status_path(), status)


def _done(status: Dict[str, Any], step: str) -> bool:
    return status.get("steps", {}).get(step, {}).get("status") == "completed"


def _mark(status: Dict[str, Any], step: str, state: str, **extra: Any) -> None:
    status.setdefault("steps", {})[step] = {"status": state, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **extra}
    _save_status(status)


def _run_cli(args: List[str], timeout: int, step: str, status: Dict[str, Any]) -> Dict[str, Any]:
    log_dir = RESULTS / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{step}.log"
    t0 = time.time()
    _mark(status, step, "running", command=args, timeout_s=timeout, log=str(log_path.relative_to(ROOT)))
    try:
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.run([PY, "-m", "benchmark_suite.cli", *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, text=True)
        elapsed = time.time() - t0
        if proc.returncode == 0:
            _mark(status, step, "completed", returncode=0, elapsed_s=round(elapsed, 3), log=str(log_path.relative_to(ROOT)))
            return {"ok": True, "elapsed_s": elapsed}
        _mark(status, step, "failed", returncode=proc.returncode, elapsed_s=round(elapsed, 3), log=str(log_path.relative_to(ROOT)))
        return {"ok": False, "returncode": proc.returncode, "elapsed_s": elapsed}
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        _mark(status, step, "timeout", elapsed_s=round(elapsed, 3), log=str(log_path.relative_to(ROOT)))
        return {"ok": False, "timeout": True, "elapsed_s": elapsed}
    except Exception as exc:
        elapsed = time.time() - t0
        _mark(status, step, "error", error=str(exc), elapsed_s=round(elapsed, 3), log=str(log_path.relative_to(ROOT)))
        return {"ok": False, "error": str(exc), "elapsed_s": elapsed}


def run_full(include_neural: bool = True, include_50k: bool = True, quick: bool = False) -> Dict[str, Any]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    DATASETS.mkdir(parents=True, exist_ok=True)
    status = _load_status()
    scales = [100] if quick else SCALES
    if not include_50k:
        scales = [s for s in scales if s != 50000]
    queries = 200 if quick else QUERIES

    # Dataset generation + validation.
    for scale in scales:
        step = f"generate_scale_{scale}"
        if not _done(status, step):
            _run_cli(["generate", "--scale", str(scale), "--seed", "7", "--queries", str(queries), "--out", str(DATASETS / f"scale_{scale}"), "--validate"], timeout=1800, step=step, status=status)

    core_arms = ["bm25", "treemem_manual", "treemem_guided", "treemem_guided_no_fallback", "treemem_search"]
    neural_arms = ["dense", "hybrid", "hybrid_rerank"]
    for scale in scales:
        ds = DATASETS / f"scale_{scale}"
        if not (ds / "manifest.json").exists():
            continue
        step = f"retrieval_core_scale_{scale}"
        if not _done(status, step):
            _run_cli(["run", "retrieval", "--dataset", str(ds), "--out", str(RESULTS / f"scale_{scale}" / "retrieval_core"), "--arms", *core_arms, "--split", "test", "--k", "10", "--repetitions", "1"], timeout=7200, step=step, status=status)
        if include_neural:
            step = f"retrieval_neural_scale_{scale}"
            if not _done(status, step):
                _run_cli(["run", "retrieval", "--dataset", str(ds), "--out", str(RESULTS / f"scale_{scale}" / "retrieval_neural"), "--arms", *neural_arms, "--split", "test", "--k", "10", "--repetitions", "1"], timeout=7200, step=step, status=status)
            step = f"context_flat_scale_{scale}"
            if not _done(status, step):
                _run_cli(["run", "retrieval", "--dataset", str(ds), "--out", str(RESULTS / f"scale_{scale}" / "context_flat"), "--arms", "flat_all", "--split", "test", "--k", "1", "--limit", "1", "--repetitions", "1"], timeout=3600, step=step, status=status)
        step = f"scaling_scale_{scale}"
        if not _done(status, step):
            _run_cli(["run", "scaling", "--dataset", str(ds), "--out", str(RESULTS / f"scale_{scale}" / "scaling"), "--arms", "bm25", "treemem_guided", "treemem_search", "--limit", "100", "--k", "10"], timeout=7200, step=step, status=status)
        step = f"privacy_scale_{scale}"
        if not _done(status, step):
            _run_cli(["run", "privacy", "--dataset", str(ds), "--out", str(RESULTS / f"scale_{scale}" / "privacy"), "--limit", "200"], timeout=3600, step=step, status=status)

    # Lifecycle/reliability/ablation/offline E2E on the smallest dataset.
    small = DATASETS / "scale_100"
    if (small / "manifest.json").exists():
        for exp, args, timeout in [
            ("lifecycle", ["run", "lifecycle", "--dataset", str(small), "--out", str(RESULTS / "lifecycle")], 1800),
            ("reliability", ["run", "reliability", "--dataset", str(small), "--out", str(RESULTS / "reliability"), "--repetitions", "5"], 1800),
            ("ablation", ["run", "ablation", "--dataset", str(small), "--out", str(RESULTS / "ablation"), "--limit", "200"], 3600),
            ("e2e", ["run", "e2e", "--dataset", str(small), "--out", str(RESULTS / "e2e"), "--arms", "bm25", "treemem_guided", "treemem_search", "--split", "test", "--limit", "400", "--k", "5"], 3600),
        ]:
            step = f"{exp}_scale_100"
            if not _done(status, step):
                _run_cli(args, timeout=timeout, step=step, status=status)

    # Aggregate whatever completed.
    for summary in RESULTS.rglob("summary.json"):
        exp_dir = summary.parent
        try:
            subprocess.run([PY, "-m", "benchmark_suite.cli", "analyze", "--experiment-dir", str(exp_dir)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        except Exception:
            pass
    status["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    status["complete"] = all(v.get("status") == "completed" for v in status.get("steps", {}).values())
    _save_status(status)
    return status


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run staged full-scale TreeMem benchmark")
    ap.add_argument("--no-neural", action="store_true", help="Skip dense/hybrid/rerank arms")
    ap.add_argument("--no-50k", action="store_true", help="Skip the 50,000-memory scale")
    ap.add_argument("--quick", action="store_true", help="Smoke-scale run: scale=100 only, 200 queries")
    args = ap.parse_args(argv)
    status = run_full(include_neural=not args.no_neural, include_50k=not args.no_50k, quick=args.quick)
    print(json.dumps({"results": str(RESULTS), "status": str(_status_path()), "complete": status.get("complete"), "steps": {k: v.get("status") for k, v in status.get("steps", {}).items()}}, indent=2))
    return 0 if status.get("complete") else 2


if __name__ == "__main__":
    raise SystemExit(main())
