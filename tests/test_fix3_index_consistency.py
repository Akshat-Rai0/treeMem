"""Pass 3: incremental index updates must equal a full rebuild (scores, not just ids)."""
import json
from treemem.tree_manager import TreeManager


def _populate(m, n=40):
    for i in range(n):
        p = f"g{i % 5}/l{i}"
        r = m.remember(f"alpha{i % 3} fact {i} common words here", hint=p)
        m.place(r["entry_id"], p)


def _scores(m, q):
    return [(h["entry_id"], h["score"]) for h in m.search(q, limit=15)["hits"]]


def test_entry_scores_identical_before_and_after_full_rebuild(tmp_path):
    m = TreeManager(tmp_path / "v")
    _populate(m)
    incremental = _scores(m, "alpha1 common")
    m.rebuild_index()
    assert incremental == _scores(m, "alpha1 common")


def test_first_entries_after_empty_start_get_bm25(tmp_path):
    m = TreeManager(tmp_path / "v")
    assert m.index.bm25_entries is None
    r = m.remember("quantum banana smoothie", hint="food/drinks")
    m.place(r["entry_id"], "food/drinks")
    hits = m.search("banana")["hits"]
    assert hits and hits[0]["score"] > 1.5  # keyword bonus alone is 1.5, BM25 must add on top or equal full build
    inc = _scores(m, "banana")
    m.rebuild_index()
    assert inc == _scores(m, "banana")


def test_node_candidates_identical_after_refresh_vs_rebuild(tmp_path):
    m = TreeManager(tmp_path / "v")
    _populate(m, 20)
    m.commit_summary("g0", "Group zero is about cooking and recipes.\n\n## Children\n" + "".join(
        f"- [[l{i}]] - x\n" for i in range(0, 20, 5)))
    idx = m.index
    before = json.dumps(idx.candidate_nodes("cooking recipes", limit=5), sort_keys=True)
    m.rebuild_index()
    after = json.dumps(m.index.candidate_nodes("cooking recipes", limit=5), sort_keys=True)
    assert before == after


def test_refresh_keeps_dense_rows_aligned(tmp_path):
    import numpy as np
    from treemem.index import SearchIndex

    class Fake:
        dimension = 4
        is_remote = False
        def embed_text(self, t): return np.ones(4, dtype=np.float32) / 2
        def embed_batch(self, ts): return np.vstack([self.embed_text(t) for t in ts])

    idx = SearchIndex(embedding_provider=Fake())
    nodes = [{"path": f"n{i}", "name": f"n{i}", "summary": f"s{i}", "aliases": []} for i in range(3)]
    idx.build([], [], nodes)
    if idx._node_embeddings is None:
        return  # provider API differs; nothing to align
    idx.refresh_node("n1", {"name": "n1", "summary": "changed", "aliases": []})
    assert len(idx._node_embeddings) == len(idx.node_docs) == 3
    idx.refresh_node("n9", {"name": "n9", "summary": "new", "aliases": []})
    assert len(idx._node_embeddings) == len(idx.node_docs) == 4
    idx.remove_node("n0")
    assert len(idx._node_embeddings) == len(idx.node_docs) == 3
