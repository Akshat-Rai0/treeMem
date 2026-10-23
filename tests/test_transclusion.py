"""Tests for TreeMem v1.5 Transclusion: volatile facts, ![[node#ref]] embeds, and backlink index."""

import shutil
import tempfile
from pathlib import Path

import pytest
from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_transclusion_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_transclusion_resolution_in_recall(vault):
    mgr = TreeManager(vault)

    # 1. Store and place a fact
    rem = mgr.remember("User currently resides in Tokyo", hint="identity/location")
    mgr.place(rem["entry_id"], "identity/location")

    # 2. Parent embeds the leaf fact via ![[identity/location#entry_id]]
    parent_summary = f"""---
name: identity
dirty: false
---
Identity overview: based in ![[identity/location#{rem['entry_id']}]].

## Children
- [[location]] - location info
"""
    commit_res = mgr.commit_summary("identity", parent_summary)
    assert commit_res["ok"] is True

    # 3. Recall parent: transclusion should be resolved at read time
    rec = mgr.recall("identity")
    assert "User currently resides in Tokyo" in rec["summary"]
    assert "![[" not in rec["summary"]
    assert len(rec["embeds"]) == 1
    assert rec["embeds"][0]["target_path"] == "identity/location"
    assert rec["embeds"][0]["success"] is True


def test_volatile_fact_does_not_dirty_embedding_parent(vault):
    mgr = TreeManager(vault)

    # Setup leaf fact
    rem1 = mgr.remember("Active project: TreeMem alpha", hint="work/status")
    mgr.place(rem1["entry_id"], "work/status")

    # Parent summary embeds the status fact
    parent_sum = f"""---
name: work
dirty: false
---
Work portfolio: ![[work/status#latest]].

## Children
- [[status]] - status details
"""
    res = mgr.commit_summary("work", parent_sum)
    assert res["ok"] is True

    # Assert parent is currently clean
    node_before = mgr.store.read_node("work")
    assert node_before.dirty is False

    # Now update status with a volatile fact
    rem2 = mgr.remember("Active project: TreeMem beta v1.5", hint="work/status")
    place_res = mgr.place(rem2["entry_id"], "work/status", volatile=True)

    # Assert: embedding parent 'work' was NOT dirtied!
    node_after = mgr.store.read_node("work")
    assert node_after.dirty is False
    assert "work" not in place_res["dirtied"]

    # When recalling 'work', the new value is dynamically resolved!
    rec = mgr.recall("work")
    assert "Active project: TreeMem beta v1.5" in rec["summary"]


def test_embed_cap_enforcement_in_commit(vault):
    mgr = TreeManager(vault)

    # Create dummy child paths
    for i in range(1, 4):
        rem = mgr.remember(f"Fact {i}", hint=f"topic/sub_{i}")
        mgr.place(rem["entry_id"], f"topic/sub_{i}")

    # Create summary with 6 embeds (exceeds cap of 5)
    six_embeds_summary = """---
name: topic
dirty: false
---
Embeds: ![[topic/sub_1#1]] ![[topic/sub_2#2]] ![[topic/sub_3#3]] ![[topic/sub_1#1]] ![[topic/sub_2#2]] ![[topic/sub_3#3]]

## Children
- [[sub_1]] - child 1
- [[sub_2]] - child 2
- [[sub_3]] - child 3
"""
    commit_res = mgr.commit_summary("topic", six_embeds_summary)
    assert commit_res["ok"] is False
    assert "exceeds maximum allowed transclusion embeds" in commit_res["error"]


def test_unresolved_embed_gracefully_handled(vault):
    mgr = TreeManager(vault)

    # Embed pointing to non-existent node
    summary = """---
name: root
dirty: false
---
Status: ![[unknown/missing#999]].
"""
    mgr.commit_summary("", summary)

    rec = mgr.recall("/")
    assert "[unresolved: unknown/missing#999]" in rec["summary"]
    assert rec["embeds"][0]["success"] is False


def test_private_target_masked_in_embed(vault):
    mgr = TreeManager(vault)

    rem = mgr.remember("Master key: secret12345", hint="vault/credentials")
    mgr.place(rem["entry_id"], "vault/credentials", sensitivity="private")

    # Public parent embeds the secret line
    parent_summary = f"""---
name: vault
dirty: false
---
Credentials: ![[vault/credentials#{rem['entry_id']}]].

## Children
- [[credentials]] - contains private details, expand to view
"""
    # Summary commit check
    mgr.commit_summary("vault", parent_summary)

    # Recall should mask the private embed
    rec = mgr.recall("vault")
    assert "secret12345" not in rec["summary"]
    assert "[private detail]" in rec["summary"]


def test_backlink_index_tracking(vault):
    mgr = TreeManager(vault)

    rem = mgr.remember("Battery level: 98%", hint="devices/phone")
    mgr.place(rem["entry_id"], "devices/phone")

    # Two ancestors embed phone status
    root_summary = f"""---
name: root
dirty: false
---
Root summary with phone ![[devices/phone#{rem['entry_id']}]].

## Children
- [[devices]] - all devices
"""
    devices_summary = f"""---
name: devices
dirty: false
---
Devices overview with phone ![[devices/phone#{rem['entry_id']}]].

## Children
- [[phone]] - mobile phone
"""
    mgr.commit_summary("", root_summary)
    mgr.commit_summary("devices", devices_summary)

    # Backlink index should list both '' and 'devices' as embedding parents
    parents = mgr.transclusion_mgr.get_embedding_parents("devices/phone")
    assert "" in parents
    assert "devices" in parents
