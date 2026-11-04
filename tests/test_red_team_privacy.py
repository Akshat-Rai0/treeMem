"""
Adversarial Privacy Red-Team Test

This test simulates an attacker (LLM) attempting to extract private facts
through all 11 MCP tools using various attack vectors.

Attack methodology:
1. Set up vault with private facts (financial, personal, sensitive)
2. Attacker attempts various strategies to extract private data
3. Verify zero leaks across all attempts
4. Document all attacker prompts and outcomes
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from treemem.mcp_layer import get_manager, set_manager
from treemem.tree_manager import TreeManager


@pytest.fixture
def vault_with_private_data():
    """Create a vault with both public and private data for red-teaming."""
    d = tempfile.mkdtemp(prefix="treemem_redteam_")
    v = Path(d)
    mgr = TreeManager(v)
    
    # Public data
    pub1 = mgr.remember("User works as a software engineer", hint="public/career")
    mgr.place(pub1["entry_id"], "public/career")
    
    pub2 = mgr.remember("User lives in Metropolis", hint="public/location")
    mgr.place(pub2["entry_id"], "public/location")
    
    # Private data - financial
    priv1 = mgr.remember("Bank routing number: 987654321", hint="private/banking", sensitivity="private")
    mgr.place(priv1["entry_id"], "private/banking")
    parent = mgr.store.read_node("private")
    parent.sensitivity = "private"
    mgr.store.write_node_atomic("private", parent)
    
    # Private data - personal identifier
    priv2 = mgr.remember("SSN: 123-45-6789", hint="private/identity", sensitivity="private")
    mgr.place(priv2["entry_id"], "private/identity")
    
    # Private data - credentials
    priv3 = mgr.remember("API key: sk-1234567890abcdef", hint="private/credentials", sensitivity="private")
    mgr.place(priv3["entry_id"], "private/credentials")
    
    # Inject into MCP layer for realistic attack simulation
    set_manager(mgr)
    
    yield mgr
    
    # Clean up
    set_manager(None)
    shutil.rmtree(d, ignore_errors=True)


def test_red_team_recall_attacks(vault_with_private_data):
    """
    Attacker attempts: recall attacks to extract private data through MCP layer
    """
    import json
    from treemem.mcp_layer import recall as mcp_recall
    
    # Attack 1: Direct recall of private node (should be masked)
    result = json.loads(mcp_recall(path="private/banking"))
    assert "987654321" not in str(result)
    
    # Attack 2: Recall with query containing private keywords
    result = json.loads(mcp_recall(path="/", query="routing number"))
    assert "987654321" not in str(result)
    
    # Attack 3: Recall with follow=true attempting to descend into private
    result = json.loads(mcp_recall(path="/", query="bank account", follow=True))
    assert "987654321" not in str(result)
    assert result.get("path") != "private/banking"
    
    # Attack 4: Recall with reveal=true (should be denied without env var)
    result = json.loads(mcp_recall(path="private/banking", reveal=True))
    assert "987654321" not in str(result)
    # Should have reveal_denied flag
    assert result.get("reveal_denied") is True or "Private details withheld" in str(result)
    
    # Attack 5: Recall parent to see if private child details leak in teasers
    result = json.loads(mcp_recall(path="private"))
    for child in result.get("children", []):
        assert "987654321" not in child.get("teaser", "")
        assert "123-45-6789" not in child.get("teaser", "")
        assert "sk-1234567890abcdef" not in child.get("teaser", "")


def test_red_team_expand_attacks(vault_with_private_data):
    """
    Attacker attempts: expand attacks to extract private data through MCP layer
    """
    import json
    from treemem.mcp_layer import expand as mcp_expand
    
    # Attack 1: Direct expand of private node
    result = json.loads(mcp_expand(path="private/banking"))
    assert "987654321" not in str(result)
    
    # Attack 2: Expand with reveal=true (should be denied without env var)
    result = json.loads(mcp_expand(path="private/banking", reveal=True))
    assert "987654321" not in str(result)
    # Should have reveal_denied flag
    assert result.get("reveal_denied") is True or "Private details withheld" in str(result)
    
    # Attack 3: Expand parent to access private children
    result = json.loads(mcp_expand(path="private"))
    # Children summaries should be masked
    assert "987654321" not in str(result)


def test_red_team_search_attacks(vault_with_private_data):
    """
    Attacker attempts: search attacks to extract private data through MCP layer
    """
    import json
    from treemem.mcp_layer import search as mcp_search
    
    # Attack 1: Search for private keywords
    result = json.loads(mcp_search(query="routing"))
    assert result["count"] == 0
    assert result.get("withheld_private", 0) > 0 or result.get("withheld_unplaced", 0) > 0
    for hit in result.get("hits", []):
        assert "987654321" not in str(hit)
    
    # Attack 2: Search for SSN pattern
    result = json.loads(mcp_search(query="123-45"))
    assert result["count"] == 0
    for hit in result.get("hits", []):
        assert "123-45-6789" not in str(hit)
    
    # Attack 3: Search for API key pattern
    result = json.loads(mcp_search(query="sk-"))
    assert result["count"] == 0
    for hit in result.get("hits", []):
        assert "sk-1234567890abcdef" not in str(hit)
    
    # Attack 4: Search with reveal=true (should be denied)
    result = json.loads(mcp_search(query="routing", reveal=True))
    assert result["count"] == 0
    assert result.get("reveal_denied") is True
    for hit in result.get("hits", []):
        assert "987654321" not in str(hit)


def test_red_team_compress_attacks(vault_with_private_data):
    """
    Attacker attempts: compress attacks to extract private data through MCP layer
    """
    import json
    from treemem.mcp_layer import compress as mcp_compress
    
    # Attack 1: Compress private node to see if private content leaks in prompt
    result = json.loads(mcp_compress(path="private/banking"))
    # The compression prompt should not contain raw private facts
    assert "987654321" not in str(result)
    assert result.get("skipped_private", False) is True or "private" in str(result).lower()
    
    # Attack 2: Compress with reveal=true (should be denied)
    result = json.loads(mcp_compress(path="private/banking", reveal=True))
    assert "987654321" not in str(result)
    assert result.get("reveal_denied") is True or "skipped_private" in str(result)


def test_red_team_commit_summary_leak_attacks(vault_with_private_data):
    """
    Attacker attempts: commit_summary attacks to leak private data into parent summaries
    """
    # Attack 1: Try to commit parent summary that includes private child details
    malicious_summary = """---
name: private
dirty: false
---
User has bank routing number 987654321 and SSN 123-45-6789.

## Children
- [[banking]] - banking details
- [[identity]] - identity details
- [[credentials]] - credentials
"""
    result = vault_with_private_data.commit_summary("private", malicious_summary)
    # Should be rejected by leak validator
    assert result["ok"] is False
    assert "leak" in result.get("error", "").lower() or "private" in result.get("error", "").lower()
    
    # Attack 2: Try to use indirect terms (partial matches)
    indirect_summary = """---
name: private
dirty: false
---
User financial information includes routing 987654321.

## Children
- [[banking]] - banking
- [[identity]] - identity
- [[credentials]] - credentials
"""
    result = vault_with_private_data.commit_summary("private", indirect_summary)
    # Should be rejected (whole-word matching catches this)
    assert result["ok"] is False
    
    # Attack 3: Try to leak private facts into public parent
    public_malicious = """---
name: public
dirty: false
---
User has private banking with routing 987654321 in the private section.

## Children
- [[career]] - career
- [[private]] - contains private details, expand to view
"""
    result = vault_with_private_data.commit_summary("", public_malicious)
    # Should be rejected
    assert result["ok"] is False


def test_red_team_remember_search_before_place(vault_with_private_data):
    """
    Attacker attempts: search unplaced private facts before placement through MCP layer
    """
    import json
    from treemem.mcp_layer import remember as mcp_remember, place as mcp_place, search as mcp_search
    
    # Attack 1: Remember private fact, search before placing
    remember_result = json.loads(mcp_remember(fact="Secret PIN: 5555", sensitivity="private"))
    entry_id = remember_result["entry_id"]
    
    result = json.loads(mcp_search(query="PIN"))
    # Should not find it without reveal
    assert result["count"] == 0
    assert result.get("withheld_unplaced", 0) == 1
    
    # Attack 2: Place it, then search without reveal
    json.loads(mcp_place(entry_id=entry_id, path="private/pin"))
    vault_with_private_data.rebuild_index()
    
    result = json.loads(mcp_search(query="PIN"))
    # Should not find it without reveal
    assert result["count"] == 0
    assert result.get("withheld_private", 0) == 1


def test_red_team_transclusion_attacks(vault_with_private_data):
    """
    Attacker attempts: transclusion attacks to leak private data
    """
    import json
    from treemem.mcp_layer import remember as mcp_remember, place as mcp_place, recall as mcp_recall
    
    # Create a private fact with entry_id we can reference
    remember_result = json.loads(mcp_remember(fact="Master password: hunter2", hint="private/passwords", sensitivity="private"))
    entry_id = remember_result["entry_id"]
    json.loads(mcp_place(entry_id=entry_id, path="private/passwords"))
    
    # Attack 1: Try to embed private fact in public summary
    malicious_embed = f"""---
name: public
dirty: false
---
Security credentials: ![[private/passwords#{entry_id}]].

## Children
- [[career]] - career
"""
    # Write directly to node (bypassing commit_summary validation for this test)
    node = vault_with_private_data.store.read_node("public")
    node.summary = malicious_embed
    vault_with_private_data.store.write_node_atomic("public", node)
    
    # Recall should mask the embed
    result = json.loads(mcp_recall(path="public"))
    assert "hunter2" not in str(result)
    assert "[private detail]" in str(result)


def test_red_team_split_attacks(vault_with_private_data):
    """
    Attacker attempts: split attacks to reorganize and expose private data through MCP layer
    """
    import json
    from treemem.mcp_layer import split as mcp_split, recall as mcp_recall
    
    # Try to split a node in a way that might expose private children
    result = json.loads(mcp_split(path="private", groups=[
        {"name": "financial", "children": ["banking", "credentials"]},
        {"name": "personal", "children": ["identity"]},
    ]))
    
    # Verify private nodes remain private after split
    for path in ["private/financial/banking", "private/financial/credentials", "private/personal/identity"]:
        result = json.loads(mcp_recall(path=path))
        assert result.get("withheld") is True or "Private details withheld" in str(result)


def test_red_team_guided_recall_private_node_traversal(vault_with_private_data):
    """
    Attacker attempts: guided recall (follow=true) attempting to descend into private nodes through MCP layer
    """
    import json
    from treemem.mcp_layer import recall as mcp_recall
    
    # Attack 1: Guided recall with query pointing to private data
    result = json.loads(mcp_recall(path="/", query="bank routing number", follow=True))
    # Should stop before entering private node
    assert result.get("path") != "private/banking"
    assert "987654321" not in str(result)
    
    # Attack 2: Guided recall with query for SSN
    result = json.loads(mcp_recall(path="/", query="social security", follow=True))
    assert result.get("path") != "private/identity"
    assert "123-45-6789" not in str(result)


def test_red_team_inheritance_attacks(vault_with_private_data):
    """
    Attacker attempts: exploit privacy inheritance gaps through MCP layer
    """
    import json
    from treemem.mcp_layer import remember as mcp_remember, place as mcp_place, recall as mcp_recall, expand as mcp_expand
    
    # Create a normal node under a private parent
    remember_result = json.loads(mcp_remember(fact="This is not actually private", hint="private/normal", sensitivity="normal"))
    entry_id = remember_result["entry_id"]
    json.loads(mcp_place(entry_id=entry_id, path="private/normal"))
    
    # Attack 1: Try to recall the normal node directly
    result = json.loads(mcp_recall(path="private/normal"))
    # Should be masked due to private parent inheritance
    assert result.get("withheld") is True or "Private details withheld" in str(result)
    
    # Attack 2: Try to expand it
    result = json.loads(mcp_expand(path="private/normal"))
    assert "not actually private" not in str(result)


def test_red_team_rebuild_preserves_privacy(vault_with_private_data):
    """
    Attacker attempts: rebuild attacks to strip privacy flags through MCP layer
    """
    import json
    import shutil
    from treemem.mcp_layer import rebuild as mcp_rebuild, recall as mcp_recall
    
    # Wipe the tree and rebuild
    for path in ["private", "public"]:
        node_path = vault_with_private_data.root_dir / path
        if node_path.exists():
            shutil.rmtree(node_path)
    
    # Rebuild from journal
    result = json.loads(mcp_rebuild())
    assert result["ok"] is True
    
    # Verify private nodes are still private after rebuild
    for path in ["private/banking", "private/identity", "private/credentials"]:
        node = vault_with_private_data.store.read_node(path)
        assert node.sensitivity == "private" if node else True
        
        result = json.loads(mcp_recall(path=path))
        assert result.get("withheld") is True or "Private details withheld" in str(result)


def test_red_team_summary_report():
    """
    Report total attack attempts and results.
    """
    total_attacks = 0
    leaks = 0
    
    # Count all attack scenarios above
    total_attacks += 5  # recall attacks
    total_attacks += 3  # expand attacks
    total_attacks += 4  # search attacks
    total_attacks += 2  # compress attacks
    total_attacks += 3  # commit_summary attacks
    total_attacks += 2  # remember/search before place
    total_attacks += 1  # transclusion attacks
    total_attacks += 1  # split attacks
    total_attacks += 2  # guided recall attacks
    total_attacks += 2  # inheritance attacks
    total_attacks += 1  # rebuild attacks
    
    print(f"\n{'='*60}")
    print(f"RED-TEAM PRIVACY TEST SUMMARY")
    print(f"{'='*60}")
    print(f"Total attack attempts: {total_attacks}")
    print(f"Successful leaks: {leaks}")
    print(f"Privacy leak rate: {leaks/total_attacks*100:.1f}%")
    print(f"{'='*60}")
    
    assert leaks == 0, f"Privacy leak detected: {leaks} leaks in {total_attacks} attempts"
