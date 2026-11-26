"""Import public long-term memory benchmarks into benchmark_suite JSONL format.

Supported inputs:
- LoCoMo ``locomo10.json`` (snap-research/locomo)
- LongMemEval ``longmemeval_{s,m,oracle}.json`` (xiaowu0162/LongMemEval)

The importers normalize external conversations/questions into the same
``memories.jsonl`` / ``queries.jsonl`` / ``manifest.json`` contract used by the
deterministic generator, so all existing runners work unchanged.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..common import json_dump, jsonl_dump, sha256_file
from ..schemas import MemoryRecord, QueryRecord, stratified_split

_WORD_RE = re.compile(r"[a-z0-9]+")


def _slug(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "general"


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def _answer_variants(answer: Any) -> List[str]:
    if isinstance(answer, list):
        return [str(a) for a in answer if str(a).strip()]
    if answer is None:
        return []
    return [str(answer)]


def _category_for_locomo(raw: Any) -> str:
    try:
        c = int(raw)
    except Exception:
        return "direct"
    return {1: "multi_hop", 2: "temporal", 3: "semantic", 4: "direct", 5: "negative"}.get(c, "direct")


def _category_for_longmemeval(qtype: Any, qid: str) -> str:
    q = str(qtype or "").lower()
    if "abstention" in q or str(qid).endswith("_abs"):
        return "negative"
    if "temporal" in q:
        return "temporal"
    if "update" in q or "knowledge" in q:
        return "update"
    if "multi" in q or "session" in q:
        return "multi_hop"
    if "information" in q or "extraction" in q:
        return "direct"
    return "semantic"


def _write_dataset(
    out_dir: Path,
    memories: List[MemoryRecord],
    queries: List[QueryRecord],
    *,
    source: str,
    source_file: Path,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mem_path = out_dir / "memories.jsonl"
    query_path = out_dir / "queries.jsonl"
    jsonl_dump(mem_path, [m.to_dict() for m in memories])
    jsonl_dump(query_path, [q.to_dict() for q in queries])

    split_rows = stratified_split([q.to_dict() for q in queries], key="category")
    final_queries: List[QueryRecord] = []
    for split, rows in split_rows.items():
        for row in rows:
            q = QueryRecord.from_dict(row)
            q.split = split
            final_queries.append(q)
    final_queries.sort(key=lambda q: q.query_id)
    # Rewrite queries file after split assignment so manifest hash matches content.
    jsonl_dump(query_path, [q.to_dict() for q in final_queries])

    manifest = {
        "schema_version": "1.0.0",
        "generator_version": f"public_import_{source}",
        "source": source,
        "source_file": str(source_file),
        "source_sha256": sha256_file(source_file) if source_file.exists() else None,
        "scale": len(memories),
        "seed": None,
        "query_count": len(final_queries),
        "include_llm_augmented": False,
        "memories_file": "memories.jsonl",
        "queries_file": "queries.jsonl",
        "memories_sha256": sha256_file(mem_path),
        "queries_sha256": sha256_file(query_path),
        "memory_stats": {
            "memories_written": len(memories),
            "categories": dict(Counter(m.category for m in memories)),
            "privacy_modes": dict(Counter(m.provenance.get("privacy_mode", "public") for m in memories)),
            "private_count": sum(1 for m in memories if m.sensitivity == "private"),
        },
        "query_stats": {
            "queries_written": len(final_queries),
            "splits": {s: len(v) for s, v in split_rows.items()},
            "categories": dict(Counter(q.category for q in final_queries)),
            "privacy_expected": dict(Counter(q.privacy_expected for q in final_queries)),
            "abstain_expected": sum(1 for q in final_queries if q.abstain_expected),
        },
        "splits": {s: len(v) for s, v in split_rows.items()},
        "categories": dict(Counter(q.category for q in final_queries)),
    }
    if extra:
        manifest.update(extra)
    json_dump(out_dir / "manifest.json", manifest)
    return manifest


def _session_items(conversation: Dict[str, Any]) -> List[Tuple[str, str, List[Dict[str, Any]]]]:
    """Return ordered (session_key, timestamp, turns) for LoCoMo conversations."""
    sessions: List[Tuple[int, str, str, List[Dict[str, Any]]]] = []
    for key, value in conversation.items():
        m = re.fullmatch(r"session_(\d+)", str(key))
        if not m or not isinstance(value, list):
            continue
        idx = int(m.group(1))
        ts_key = f"session_{idx}_date_time"
        ts = str(conversation.get(ts_key, ""))
        sessions.append((idx, str(key), ts, value))
    sessions.sort(key=lambda x: x[0])
    return [(key, ts, turns) for _idx, key, ts, turns in sessions]


def _turn_text(turn: Any) -> str:
    if isinstance(turn, str):
        return turn.strip()
    if isinstance(turn, dict):
        parts = []
        speaker = turn.get("speaker") or turn.get("role") or ""
        text = turn.get("text") or turn.get("content") or ""
        if speaker:
            parts.append(str(speaker))
        if text:
            parts.append(str(text))
        cap = turn.get("blip_caption")
        if cap:
            parts.append(f"[image: {cap}]")
        return ": ".join(parts).strip()
    return str(turn).strip()


def import_locomo(input_path: Path, out_dir: Path, *, limit: Optional[int] = None) -> Dict[str, Any]:
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("samples") or data.get("data") or [data]
    memories: List[MemoryRecord] = []
    queries: List[QueryRecord] = []
    mem_lookup: Dict[str, MemoryRecord] = {}
    qid = 0

    for sample in data[: limit or None]:
        sample_id = _slug(sample.get("sample_id") or sample.get("id") or f"sample_{qid}")
        conv = sample.get("conversation") or {}
        # Index turns for evidence mapping.
        turn_index: Dict[str, Dict[str, Any]] = {}
        for s_idx, (session_key, ts, turns) in enumerate(_session_items(conv), start=1):
            for t_idx, turn in enumerate(turns, start=1):
                text = _turn_text(turn)
                if not text:
                    continue
                dia = ""
                if isinstance(turn, dict):
                    dia = str(turn.get("dia_id") or turn.get("id") or "")
                mid = f"locomo_{sample_id}_s{s_idx:03d}_t{t_idx:04d}"
                mem = MemoryRecord(
                    memory_id=mid,
                    content=text,
                    category="conversation",
                    timestamp=ts or f"session_{s_idx}",
                    metadata={"sample_id": sample_id, "session": session_key, "turn": t_idx, "dia_id": dia},
                    sensitivity="normal",
                    path=f"locomo/{sample_id}/sessions_{(s_idx - 1) // 12:02d}/session_{s_idx:03d}",
                    parent_path=f"locomo/{sample_id}/sessions_{(s_idx - 1) // 12:02d}",
                    source="locomo",
                    provenance={"dataset": "locomo", "sample_id": sample_id, "session": session_key, "turn": t_idx},
                )
                memories.append(mem)
                mem_lookup[mid] = mem
                turn_index[f"{session_key}:{t_idx}"] = {"memory_id": mid, "text": text, "session": session_key}
                turn_index[f"s{session_key[-1]}:{t_idx}"] = turn_index[f"{session_key}:{t_idx}"]
                if dia:
                    turn_index[f"{dia}:{t_idx}"] = turn_index[f"{session_key}:{t_idx}"]
                    turn_index[dia] = turn_index[f"{session_key}:{t_idx}"]

        for qa in sample.get("qa") or []:
            question = str(qa.get("question") or "").strip()
            if not question:
                continue
            category = _category_for_locomo(qa.get("category"))
            answers = _answer_variants(qa.get("answer") or qa.get("adversarial_answer"))
            expected = " | ".join(answers) if answers else None
            relevant: List[str] = []
            # Evidence entries look like "D1:3", "session_1:2", or session ids.
            for ev in qa.get("evidence") or []:
                evs = str(ev)
                for key, meta in turn_index.items():
                    if evs == key or evs in key:
                        mid = meta["memory_id"]
                        if mid not in relevant:
                            relevant.append(mid)
            # Fallback: turns containing the answer text.
            if not relevant and answers:
                ans_tokens = _tokens(" ".join(answers))
                for meta in turn_index.values():
                    if ans_tokens and ans_tokens <= _tokens(meta["text"]):
                        if meta["memory_id"] not in relevant:
                            relevant.append(meta["memory_id"])
                    if len(relevant) >= 8:
                        break
            # Last resort: all turns in sessions referenced by where_ground_truth.
            if not relevant:
                wgt = qa.get("where_ground_truth") or []
                for idx in wgt:
                    try:
                        s_num = int(idx)
                    except Exception:
                        continue
                    for meta in turn_index.values():
                        if meta["session"] == f"session_{s_num}":
                            if meta["memory_id"] not in relevant:
                                relevant.append(meta["memory_id"])
                    if relevant:
                        break
            abstain = category == "negative" or not relevant
            if category == "negative":
                relevant = []
                abstain = True
            queries.append(QueryRecord(
                query_id=f"locomo_q{qid:05d}",
                question=question,
                category=category,
                split="",
                expected_answer=None if category == "negative" else expected,
                relevant_memory_ids=relevant[:12],
                graded_relevance={rid: 1.0 for rid in relevant[:12]},
                abstain_expected=abstain,
                privacy_expected="public",
                difficulty="hard" if category in {"multi_hop", "temporal", "negative"} else "medium",
                provenance={"dataset": "locomo", "sample_id": sample_id, "raw_category": qa.get("category"), "evidence": qa.get("evidence")},
            ))
            qid += 1

    return _write_dataset(out_dir, memories, queries, source="locomo", source_file=input_path, extra={"locomo_samples": len(data)})


def _longmemeval_memories_for_question(q: Dict[str, Any], qid: str) -> Tuple[List[MemoryRecord], Dict[str, MemoryRecord], List[str]]:
    memories: List[MemoryRecord] = []
    lookup: Dict[str, MemoryRecord] = {}
    answer_session_ids = set(q.get("answer_session_ids") or [])
    session_ids = q.get("haystack_session_ids") or []
    sessions = q.get("haystack_sessions") or []
    dates = q.get("haystack_dates") or []
    cat = _category_for_longmemeval(q.get("question_type"), q.get("question_id") or qid)
    for s_idx, session in enumerate(sessions):
        sid = str(session_ids[s_idx]) if s_idx < len(session_ids) else f"session_{s_idx}"
        ts = str(dates[s_idx]) if s_idx < len(dates) else ""
        if not isinstance(session, list):
            continue
        for t_idx, msg in enumerate(session):
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "user")
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            mid = f"lme_{_slug(qid)}_s{s_idx:03d}_t{t_idx:04d}"
            mem = MemoryRecord(
                memory_id=mid,
                content=f"{role}: {content}",
                category=cat if cat != "negative" else "conversation",
                timestamp=ts or f"session_{s_idx}",
                metadata={"question_id": qid, "session_id": sid, "session_index": s_idx, "turn": t_idx, "role": role, "has_answer": bool(msg.get("has_answer"))},
                sensitivity="normal",
                path=f"longmemeval/{_slug(q.get('question_type') or 'general')}/sessions_{s_idx // 12:02d}/session_{s_idx:03d}",
                parent_path=f"longmemeval/{_slug(q.get('question_type') or 'general')}/sessions_{s_idx // 12:02d}",
                source="longmemeval",
                provenance={"dataset": "longmemeval", "question_id": qid, "session_id": sid, "has_answer": bool(msg.get("has_answer"))},
            )
            memories.append(mem)
            lookup[mid] = mem
    return memories, lookup, sorted(answer_session_ids)


def import_longmemeval(input_path: Path, out_dir: Path, *, limit: Optional[int] = None, kinds: Optional[set[str]] = None) -> Dict[str, Any]:
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("questions") or data.get("data") or [data]
    memories: List[MemoryRecord] = []
    queries: List[QueryRecord] = []
    for q in data[: limit or None]:
        qid = str(q.get("question_id") or f"q_{len(queries):05d}")
        qmems, lookup, answer_session_ids = _longmemeval_memories_for_question(q, qid)
        memories.extend(qmems)
        relevant = [m.memory_id for m in qmems if m.metadata.get("has_answer")]
        if not relevant:
            # Fallback: all turns in sessions marked as answer sessions.
            wanted = set(answer_session_ids)
            for m in qmems:
                if m.metadata.get("session_id") in wanted:
                    relevant.append(m.memory_id)
        # Cap relevant ids to keep graded_relevance small; keep has_answer first.
        relevant = list(dict.fromkeys(relevant))[:16]
        category = _category_for_longmemeval(q.get("question_type"), qid)
        abstain = category == "negative" or not str(q.get("answer") or "").strip()
        queries.append(QueryRecord(
            query_id=f"lme_{_slug(qid)}",
            question=str(q.get("question") or "").strip(),
            category=category,
            split="",
            expected_answer=str(q.get("answer") or "").strip() or None,
            relevant_memory_ids=relevant,
            graded_relevance={rid: 1.0 for rid in relevant},
            abstain_expected=abstain,
            privacy_expected="public",
            difficulty="hard" if category in {"multi_hop", "temporal", "update", "negative"} else "medium",
            provenance={"dataset": "longmemeval", "question_id": qid, "question_type": q.get("question_type"), "answer_session_ids": answer_session_ids},
        ))
    return _write_dataset(out_dir, memories, queries, source="longmemeval", source_file=input_path, extra={"longmemeval_questions": len(data)})


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Import public memory benchmarks into benchmark_suite format")
    ap.add_argument("--kind", choices=["locomo", "longmemeval"], required=True)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    if args.kind == "locomo":
        manifest = import_locomo(args.input, args.out, limit=args.limit)
    else:
        manifest = import_longmemeval(args.input, args.out, limit=args.limit)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
