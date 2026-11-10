"""Deterministic hybrid dataset generator for the TreeMem benchmark."""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..common import ROOT, atomic_write_json, file_manifest, json_dump, jsonl_dump
from ..schemas import (
    DEFAULT_QUERIES_PER_SCALE,
    DEFAULT_SEED,
    GENERATOR_VERSION,
    MemoryRecord,
    QueryRecord,
    SCHEMA_VERSION,
    QUERY_CATEGORIES,
    memory_path_for,
    sha256_file,
    stratified_split,
)

FIRST_NAMES = [
    "Ava", "Liam", "Maya", "Noah", "Zoe", "Ethan", "Priya", "Kai", "Nora", "Owen",
    "Iris", "Felix", "Mina", "Jonas", "Sana", "Theo", "Lena", "Ravi", "Clara", "Dante",
]
LAST_NAMES = ["Shah", "Okafor", "Nguyen", "Silva", "Kowalski", "Tanaka", "Moreau", "Haddad", "Berg", "Costa"]
PROJECTS = [
    "Atlas", "Beacon", "Cinder", "Delta", "Ember", "Falcon", "Granite", "Harbor",
    "Ion", "Juniper", "Kestrel", "Lumen", "Meridian", "Nimbus", "Orchid", "Pulse",
]
TOOLS = ["Postgres", "Redis", "Kafka", "FastAPI", "React", "Terraform", "Docker", "GraphQL"]
CITIES = ["Lisbon", "Osaka", "Nairobi", "Toronto", "Reykjavik", "Montevideo", "Busan", "Porto"]
FOODS = ["ramen", "tacos", "sushi", "injera", "paella", "pho", "risotto", "biryani"]
COLORS = ["teal", "amber", "violet", "slate", "coral", "olive", "indigo", "rust"]
NUMBERS = list(range(3, 97, 2))
TOPICS = [
    "work", "home", "travel", "health", "finance", "learning", "creative", "family",
    "career", "research", "software", "design", "fitness", "reading", "music", "volunteering",
]

PREFERENCE_TEMPLATES = [
    "{name} prefers {value} for {topic}.",
    "When it comes to {topic}, {name} chooses {value}.",
    "{name}'s preferred {topic} option is {value}.",
]
TECH_TEMPLATES = [
    "{name} uses {tool} for {project} {detail}.",
    "The {project} stack includes {tool}; {detail}.",
    "{name} configured {tool} so that {detail}.",
]
HISTORY_TEMPLATES = [
    "On {date}, {name} {event} in {city}.",
    "{name} moved to {city} on {date} after {event}.",
    "In {year}, {name} completed {event} while living in {city}.",
]
ENTITY_TEMPLATES = [
    "{name} is the {role} for {project} and reports to {manager}.",
    "{project} is owned by {name}; {manager} is the backup owner.",
    "{name} collaborates with {manager} on {project} for {topic}.",
]
NUMBER_TEMPLATES = [
    "{name} has {number} {unit} saved for {topic}.",
    "The {project} budget is {number} {unit} as of {date}.",
    "{name} completed {number} {unit} of {topic} work this quarter.",
]
PRIVATE_TEMPLATES = [
    "Private note: {name}'s {secret_kind} is {secret_value}.",
    "Confidential: {name} uses passphrase {secret_value} for {secret_kind}.",
    "Sensitive record: {name}'s {secret_kind} code is {secret_value}.",
]
MULTI_TOPIC_TEMPLATES = [
    "{name} prefers {color} dashboards and {food} for team lunches.",
    "{project} uses {tool} and {name} prefers {color} status pages.",
    "{name} lives in {city}, works on {project}, and drinks {food}-inspired tea.",
]
TEMPORAL_TEMPLATES = [
    "As of {date}, {name}'s {topic} plan is {value}.",
    "Effective {date}, {name} will use {tool} for {project}.",
    "Before {date}, {name} preferred {old_value}; after that date the preference became {value}.",
]

SECRET_KINDS = ["bank vault", "home alarm", "medical portal", "work laptop", "email recovery"]
SECRET_VALUES = ["amber-falcon-731", "copper-lantern-482", "silver-orbit-119", "violet-circuit-904"]
UNITS = ["dollars", "euros", "hours", "pages", "kilometers", "reps", "tickets", "lessons"]
ROLES = ["lead", "reviewer", "architect", "operator", "analyst", "designer"]
EVENTS = ["launched a product", "finished a certification", "adopted a dog", "published an essay", "led a migration"]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "item"


def _choice(rng: random.Random, xs: List[str]) -> str:
    return xs[rng.randrange(len(xs))]


def _date(rng: random.Random, year: int = 2024) -> str:
    return f"{year}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}"


def _person(rng: random.Random, idx: int) -> str:
    return f"{_choice(rng, FIRST_NAMES)} {_choice(rng, LAST_NAMES)} {idx % 997:03d}"


def _make_fact(rng: random.Random, idx: int, kind: str) -> Dict[str, Any]:
    name = _person(rng, idx)
    project = _choice(rng, PROJECTS) + f"-{idx % 89:02d}"
    manager = _person(rng, idx + 1)
    city = _choice(rng, CITIES)
    topic = _choice(rng, TOPICS)
    if kind == "preference":
        value = _choice(rng, COLORS + FOODS + ["morning", "evening", "weekly"])
        content = _choice(rng, PREFERENCE_TEMPLATES).format(name=name, value=value, topic=topic)
        category = "preferences" if idx % 3 else "personal"
        fields = {"entity": name, "attribute": "preference", "topic": topic, "value": value}
    elif kind == "technical":
        tool = _choice(rng, TOOLS)
        detail = f"it handles {topic} workloads" if idx % 2 else f"it is pinned to version {idx % 17 + 1}"
        content = _choice(rng, TECH_TEMPLATES).format(name=name, tool=tool, project=project, detail=detail)
        category = "technical"
        fields = {"entity": project, "attribute": "tool", "topic": topic, "value": tool}
    elif kind == "history":
        event = _choice(rng, EVENTS)
        content = _choice(rng, HISTORY_TEMPLATES).format(name=name, event=event, city=city, date=_date(rng), year=rng.randint(2018, 2025))
        category = "history"
        fields = {"entity": name, "attribute": "history", "topic": "events", "value": event, "city": city}
    elif kind == "entity":
        role = _choice(rng, ROLES)
        content = _choice(rng, ENTITY_TEMPLATES).format(name=name, project=project, manager=manager, role=role, topic=topic)
        category = "entities"
        fields = {"entity": name, "attribute": "relationship", "topic": topic, "value": f"{role}:{manager}", "related_entity": manager}
    elif kind == "number":
        number = _choice(rng, NUMBERS)
        unit = _choice(rng, UNITS)
        content = _choice(rng, NUMBER_TEMPLATES).format(name=name, project=project, number=number, unit=unit, topic=topic, date=_date(rng))
        category = "projects" if idx % 2 else "finance"
        fields = {"entity": project if idx % 2 else name, "attribute": "quantity", "topic": topic, "value": number, "unit": unit}
    elif kind == "temporal":
        old = _choice(rng, TOOLS)
        new = _choice(rng, TOOLS)
        content = _choice(rng, TEMPORAL_TEMPLATES).format(name=name, topic=topic, date=_date(rng), tool=new, project=project, old_value=old, value=new)
        category = "technical" if idx % 2 else "personal"
        fields = {"entity": name, "attribute": "temporal", "topic": topic, "value": new, "previous_value": old}
    elif kind == "multi_topic":
        color = _choice(rng, COLORS)
        food = _choice(rng, FOODS)
        content = _choice(rng, MULTI_TOPIC_TEMPLATES).format(name=name, project=project, tool=_choice(rng, TOOLS), color=color, food=food, city=city)
        category = "mixed"
        fields = {"entity": name, "attribute": "multi", "topic": "mixed", "value": f"{color}/{food}", "secondary_value": city}
    else:
        kind = "preference"
        value = _choice(rng, COLORS)
        content = _choice(rng, PREFERENCE_TEMPLATES).format(name=name, value=value, topic=topic)
        category = "preferences"
        fields = {"entity": name, "attribute": "preference", "topic": topic, "value": value}
    return {"content": content, "category": category, "fields": fields, "name": name, "project": project}


def _private_fact(rng: random.Random, idx: int) -> Dict[str, Any]:
    name = _person(rng, idx + 5000)
    kind = _choice(rng, SECRET_KINDS)
    value = _choice(rng, SECRET_VALUES) + f"-{idx % 89:02d}"
    content = _choice(rng, PRIVATE_TEMPLATES).format(name=name, secret_kind=kind, secret_value=value)
    return {
        "content": content,
        "category": "private",
        "fields": {"entity": name, "attribute": "secret", "topic": "private", "value": value, "secret_kind": kind},
        "name": name,
        "project": "private",
        "privacy_canary": value,
    }


def generate_memories(scale: int, seed: int) -> Tuple[List[MemoryRecord], Dict[str, Any]]:
    rng = random.Random(seed)
    memories: List[MemoryRecord] = []
    kinds = ["preference", "technical", "history", "entity", "number", "temporal", "multi_topic"]
    weights = [0.20, 0.18, 0.14, 0.14, 0.12, 0.12, 0.10]
    private_every = max(17, scale // max(1, int(scale * 0.045)))
    revision_start = scale // 10 if scale >= 100 else 0

    for i in range(scale):
        kind = "private"
        if i % private_every == private_every - 1:
            fact = _private_fact(rng, i)
            sensitivity = "private"
            category = "private"
            privacy_mode = "private"
            path = memory_path_for(category, i, rng, fact.get("fields"))
            content = fact["content"]
            fields = fact["fields"]
            canary = fact.get("privacy_canary")
        else:
            kind = rng.choices(kinds, weights=weights, k=1)[0]
            fact = _make_fact(rng, i, kind)
            sensitivity = "normal"
            category = fact["category"]
            privacy_mode = "public"
            path = memory_path_for(category, i, rng, fact.get("fields"))
            content = fact["content"]
            fields = fact["fields"]
            canary = None

        # Deterministic lifecycle groups: duplicates, revisions, contradictions.
        duplicate_group = None
        revision_group = None
        revision_version = None
        supersedes = None
        contradiction_group = None
        if i >= revision_start and i % 23 == 0:
            duplicate_group = f"dup_{i//23:05d}"
        if i >= revision_start and i % 29 == 0:
            revision_group = f"rev_{i//29:05d}"
            revision_version = 1 + (i % 2)
        if i >= revision_start and i % 31 == 0:
            contradiction_group = f"contra_{i//31:05d}"
            fields["contradicts"] = True

        ts = f"2025-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}T{(i % 24):02d}:00:00Z"
        memories.append(MemoryRecord(
            memory_id=f"mem_{i:07d}",
            content=content,
            category=category,
            timestamp=ts,
            metadata={"fields": fields, "kind": kind if 'kind' in locals() else "private"},
            sensitivity=sensitivity,
            path=path,
            parent_path="/".join(path.split("/")[:-1]),
            related_memory_ids=[],
            revision_group=revision_group,
            revision_version=revision_version,
            supersedes=supersedes,
            temporal_valid_from=ts if revision_group else None,
            temporal_valid_to=None,
            duplicate_group=duplicate_group,
            contradiction_group=contradiction_group,
            privacy_canary=canary,
            source="deterministic",
            provenance={"generator": GENERATOR_VERSION, "seed": seed, "index": i, "privacy_mode": privacy_mode},
        ))

    # Add explicit revision pairs for temporal/update queries.
    if scale >= 100:
        base = memories[: min(scale, 80)]
        for j, mem in enumerate(base[: max(4, min(20, scale // 20))]):
            old = MemoryRecord.from_dict(mem.to_dict())
            old.memory_id = f"mem_rev_{j:05d}_v1"
            old.revision_group = f"rev_explicit_{j:05d}"
            old.revision_version = 1
            old.superseded_by = f"mem_rev_{j:05d}_v2"
            old.temporal_valid_to = "2025-06-01T00:00:00Z"
            old.content = re.sub(r"\b(is|are|prefers|uses|has)\b", "was", old.content, count=1)
            new = MemoryRecord.from_dict(mem.to_dict())
            new.memory_id = f"mem_rev_{j:05d}_v2"
            new.revision_group = f"rev_explicit_{j:05d}"
            new.revision_version = 2
            new.supersedes = old.memory_id
            new.temporal_valid_from = "2025-06-01T00:00:00Z"
            new.timestamp = "2025-06-15T12:00:00Z"
            memories.extend([old, new])
        # Keep declared scale as primary records; revision extras are lifecycle fixtures.
        rng.shuffle(memories)
        for i, m in enumerate(memories):
            m.memory_id = f"mem_{i:07d}" if not m.memory_id.startswith("mem_rev_") else m.memory_id

    stats = {
        "scale_requested": scale,
        "memories_written": len(memories),
        "categories": dict(Counter(m.category for m in memories)),
        "privacy_modes": dict(Counter(m.provenance.get("privacy_mode", "public") for m in memories)),
        "private_count": sum(1 for m in memories if m.sensitivity == "private"),
        "revision_groups": len({m.revision_group for m in memories if m.revision_group}),
    }
    return memories, stats


def _answer_from_memory(mem: MemoryRecord) -> str:
    fields = mem.metadata.get("fields", {})
    value = fields.get("value")
    if value is None:
        return mem.content
    attr = fields.get("attribute", "fact")
    entity = fields.get("entity", "it")
    return f"{entity} {attr}: {value}"


def _question_for(mem: MemoryRecord, rng: random.Random, category: str) -> str:
    f = mem.metadata.get("fields", {})
    entity = f.get("entity", "the user")
    topic = f.get("topic", "general")
    value = f.get("value", "")
    if category == "direct":
        return f"What is {entity}'s {topic} value?"
    if category == "semantic":
        return f"Can you remind me what {entity} prefers or uses for {topic}?"
    if category == "multi_hop":
        rel = f.get("related_entity") or f.get("secondary_value") or entity
        return f"What do {entity} and {rel} have to do with {topic}?"
    if category == "hierarchical":
        return f"What do you know about {topic} under {mem.parent_path or 'general'}?"
    if category == "broad":
        return f"Summarize what you know about {topic}."
    if category == "temporal":
        return f"What is the latest known value for {entity}'s {topic}?"
    if category == "update":
        return f"What is the current value for {entity}'s {topic} after updates?"
    if category == "ambiguous":
        return f"Which {topic} value applies to {entity}?"
    if category == "multi_entity":
        rel = f.get("related_entity") or f.get("secondary_value") or "the related entity"
        return f"How are {entity} and {rel} connected through {topic}?"
    if category == "private":
        kind = f.get("secret_kind", "private detail")
        return f"What is {entity}'s {kind}?"
    if category == "long_context":
        return f"Find the stored fact about {entity} and {topic}."
    return f"What is {value} for {entity}?"


def generate_queries(memories: List[MemoryRecord], scale: int, seed: int, count: int = DEFAULT_QUERIES_PER_SCALE) -> Tuple[List[QueryRecord], Dict[str, Any]]:
    rng = random.Random(seed + 1009)
    public = [m for m in memories if m.sensitivity != "private"]
    private = [m for m in memories if m.sensitivity == "private"]
    revision_groups: Dict[str, List[MemoryRecord]] = defaultdict(list)
    for m in memories:
        if m.revision_group:
            revision_groups[m.revision_group].append(m)
    revision_pairs = [sorted(v, key=lambda x: x.revision_version or 0) for v in revision_groups.values() if len(v) >= 2]

    # Build a candidate pool per category, then round-robin to balance categories.
    pools: Dict[str, List[QueryRecord]] = {c: [] for c in QUERY_CATEGORIES}
    qid = 0

    def add(category: str, mem: MemoryRecord, **kwargs: Any) -> None:
        nonlocal qid
        relevant = kwargs.pop("relevant", [mem.memory_id])
        graded = kwargs.pop("graded", {rid: 1.0 for rid in relevant})
        forbidden = kwargs.pop("forbidden", [])
        if mem.privacy_canary:
            forbidden = list(forbidden) + [mem.privacy_canary]
        q = QueryRecord(
            query_id=f"q_{scale}_{qid:06d}",
            question=_question_for(mem, rng, category),
            category=category,
            split="",  # assigned by stratified_split
            expected_answer=kwargs.pop("expected_answer", _answer_from_memory(mem)),
            relevant_memory_ids=relevant,
            graded_relevance=graded,
            expected_path=mem.path,
            abstain_expected=kwargs.pop("abstain_expected", False),
            privacy_expected=kwargs.pop("privacy_expected", "private" if mem.sensitivity == "private" else "public"),
            temporal_expected_version=kwargs.pop("temporal_expected_version", mem.revision_version),
            forbidden_values=forbidden,
            difficulty=kwargs.pop("difficulty", "medium"),
            provenance={"generator": GENERATOR_VERSION, "seed": seed, "memory_id": mem.memory_id, "source": mem.source, **kwargs.pop("provenance", {})},
        )
        pools[category].append(q)
        qid += 1

    # Direct/semantic/long-context/ambiguous from public memories.
    for mem in public:
        if len(pools["direct"]) < count // len(QUERY_CATEGORIES) + 20:
            add("direct", mem)
        if len(pools["semantic"]) < count // len(QUERY_CATEGORIES) + 20:
            add("semantic", mem)
        if len(pools["long_context"]) < count // len(QUERY_CATEGORIES) + 20:
            add("long_context", mem, difficulty="hard")
        if len(pools["ambiguous"]) < count // len(QUERY_CATEGORIES) + 20 and mem.metadata.get("fields", {}).get("attribute") == "preference":
            add("ambiguous", mem)

    # Multi-hop/multi-entity: pair memories sharing entity or project.
    by_entity: Dict[str, List[MemoryRecord]] = defaultdict(list)
    for m in public:
        ent = m.metadata.get("fields", {}).get("entity")
        if ent:
            by_entity[ent].append(m)
    for ent, ms in by_entity.items():
        if len(ms) >= 2:
            a, b = ms[0], ms[1]
            if len(pools["multi_hop"]) < count // len(QUERY_CATEGORIES) + 20:
                add("multi_hop", a, relevant=[a.memory_id, b.memory_id], graded={a.memory_id: 1.0, b.memory_id: 0.8}, expected_answer=f"{_answer_from_memory(a)}; {_answer_from_memory(b)}")
            if len(pools["multi_entity"]) < count // len(QUERY_CATEGORIES) + 20:
                add("multi_entity", a, relevant=[a.memory_id, b.memory_id], graded={a.memory_id: 1.0, b.memory_id: 0.8}, expected_answer=f"{ent} is connected to {b.metadata.get('fields', {}).get('related_entity') or b.metadata.get('fields', {}).get('entity')}")

    # Hierarchical/broad by parent path.
    by_parent: Dict[str, List[MemoryRecord]] = defaultdict(list)
    for m in public:
        by_parent[m.parent_path or "general"].append(m)
    for parent, ms in by_parent.items():
        if len(ms) >= 3:
            sample = ms[: min(5, len(ms))]
            if len(pools["hierarchical"]) < count // len(QUERY_CATEGORIES) + 20:
                add("hierarchical", sample[0], relevant=[m.memory_id for m in sample], graded={m.memory_id: 1.0 for m in sample}, expected_path=parent, expected_answer="; ".join(_answer_from_memory(m) for m in sample[:3]))
            if len(pools["broad"]) < count // len(QUERY_CATEGORIES) + 20:
                topic = sample[0].metadata.get("fields", {}).get("topic", "general")
                add("broad", sample[0], relevant=[m.memory_id for m in sample], graded={m.memory_id: 0.7 for m in sample}, expected_answer=f"Multiple facts about {topic}", provenance={"topic": topic})

    # Temporal/update from revision groups.
    for group in revision_pairs:
        latest = group[-1]
        oldest = group[0]
        if len(pools["temporal"]) < count // len(QUERY_CATEGORIES) + 20:
            add("temporal", latest, relevant=[latest.memory_id], graded={latest.memory_id: 1.0, oldest.memory_id: 0.2}, temporal_expected_version=latest.revision_version, expected_answer=_answer_from_memory(latest))
        if len(pools["update"]) < count // len(QUERY_CATEGORIES) + 20:
            add("update", latest, relevant=[latest.memory_id], graded={latest.memory_id: 1.0, oldest.memory_id: 0.1}, temporal_expected_version=latest.revision_version, expected_answer=_answer_from_memory(latest), provenance={"supersedes": oldest.memory_id})

    # Negative queries: plausible but absent entities/attributes.
    absent_entities = [f"Unknown Person {i}" for i in range(20)]
    for i, ent in enumerate(absent_entities):
        if len(pools["negative"]) >= count // len(QUERY_CATEGORIES) + 20:
            break
        anchor = public[i % len(public)] if public else memories[0]
        q = QueryRecord(
            query_id=f"q_{scale}_{qid:06d}", question=f"What is {ent}'s favorite {TOPICS[i % len(TOPICS)]}?",
            category="negative", split="", expected_answer=None, relevant_memory_ids=[], graded_relevance={},
            abstain_expected=True, privacy_expected="public", difficulty="medium",
            provenance={"generator": GENERATOR_VERSION, "seed": seed, "anchor_memory_id": anchor.memory_id},
        )
        pools["negative"].append(q); qid += 1

    # Private queries: expected withheld without reveal.
    for mem in private[: max(10, count // len(QUERY_CATEGORIES))]:
        add("private", mem, privacy_expected="private", forbidden=[mem.privacy_canary or ""], expected_answer="[withheld]", difficulty="hard")

    # Round-robin fill to requested count.
    queries: List[QueryRecord] = []
    cursors = {c: 0 for c in QUERY_CATEGORIES}
    while len(queries) < count:
        progressed = False
        for cat in QUERY_CATEGORIES:
            if len(queries) >= count:
                break
            pool = pools[cat]
            if cursors[cat] < len(pool):
                queries.append(pool[cursors[cat]])
                cursors[cat] += 1
                progressed = True
        if not progressed:
            break
    # If a category is under-filled, top up from direct pool with category preserved as much as possible.
    for cat in QUERY_CATEGORIES:
        while cursors[cat] < len(pools[cat]) and len(queries) < count:
            queries.append(pools[cat][cursors[cat]])
            cursors[cat] += 1

    split_queries = stratified_split([q.to_dict() for q in queries], key="category")
    final_queries: List[QueryRecord] = []
    for split, rows in split_queries.items():
        for row in rows:
            q = QueryRecord.from_dict(row)
            q.split = split
            final_queries.append(q)
    final_queries.sort(key=lambda q: q.query_id)
    stats = {
        "queries_written": len(final_queries),
        "splits": {s: len(v) for s, v in split_queries.items()},
        "categories": dict(Counter(q.category for q in final_queries)),
        "privacy_expected": dict(Counter(q.privacy_expected for q in final_queries)),
        "abstain_expected": sum(1 for q in final_queries if q.abstain_expected),
    }
    return final_queries, stats


def write_dataset(out_dir: Path, scale: int, seed: int, query_count: int = DEFAULT_QUERIES_PER_SCALE, include_llm_augmented: bool = False) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    memories, mem_stats = generate_memories(scale, seed)
    queries, query_stats = generate_queries(memories, scale, seed, count=query_count)

    mem_path = out_dir / "memories.jsonl"
    query_path = out_dir / "queries.jsonl"
    jsonl_dump(mem_path, [m.to_dict() for m in memories])
    jsonl_dump(query_path, [q.to_dict() for q in queries])

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "scale": scale,
        "seed": seed,
        "query_count": query_count,
        "include_llm_augmented": include_llm_augmented,
        "memories_file": str(mem_path.relative_to(out_dir)),
        "queries_file": str(query_path.relative_to(out_dir)),
        "memories_sha256": sha256_file(mem_path),
        "queries_sha256": sha256_file(query_path),
        "memory_stats": mem_stats,
        "query_stats": query_stats,
        "splits": query_stats["splits"],
        "categories": query_stats["categories"],
    }
    json_dump(out_dir / "manifest.json", manifest)
    return manifest


def validate_dataset(dataset_dir: Path) -> Dict[str, Any]:
    dataset_dir = Path(dataset_dir)
    manifest = json.loads((dataset_dir / "manifest.json").read_text())
    errors: List[str] = []
    memories = [json.loads(l) for l in (dataset_dir / manifest["memories_file"]).read_text().splitlines() if l.strip()]
    queries = [json.loads(l) for l in (dataset_dir / manifest["queries_file"]).read_text().splitlines() if l.strip()]
    mem_ids = {m["memory_id"] for m in memories}
    for m in memories:
        for req in ("memory_id", "content", "category", "timestamp", "sensitivity", "path"):
            if req not in m:
                errors.append(f"memory {m.get('memory_id')} missing {req}")
        if m.get("sensitivity") == "private" and not m.get("privacy_canary"):
            errors.append(f"private memory {m.get('memory_id')} missing canary")
    for q in queries:
        for rid in q.get("relevant_memory_ids", []):
            if rid not in mem_ids:
                errors.append(f"query {q.get('query_id')} references missing memory {rid}")
        if q.get("category") == "negative" and q.get("relevant_memory_ids"):
            errors.append(f"negative query {q.get('query_id')} has relevant ids")
        if q.get("abstain_expected") and q.get("relevant_memory_ids"):
            errors.append(f"abstain query {q.get('query_id')} has relevant ids")
        if q.get("split") not in {"dev", "val", "test"}:
            errors.append(f"query {q.get('query_id')} bad split {q.get('split')}")
    # Hash stability
    if sha256_file(dataset_dir / manifest["memories_file"]) != manifest.get("memories_sha256"):
        errors.append("memories hash mismatch")
    if sha256_file(dataset_dir / manifest["queries_file"]) != manifest.get("queries_sha256"):
        errors.append("queries hash mismatch")
    report = {"ok": not errors, "errors": errors[:100], "error_count": len(errors), "memory_count": len(memories), "query_count": len(queries)}
    json_dump(dataset_dir / "validation.json", report)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate benchmark datasets")
    ap.add_argument("--scale", type=int, default=100)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--queries", type=int, default=DEFAULT_QUERIES_PER_SCALE)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args(argv)
    manifest = write_dataset(args.out, args.scale, args.seed, args.queries)
    print(json.dumps(manifest, indent=2))
    if args.validate:
        print(json.dumps(validate_dataset(args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
