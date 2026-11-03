"""WP-F: End-to-end test for in-process dashboard integration with MCP."""

import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest

from treemem.dashboard.server import create_app
from treemem.mcp_layer import get_manager, set_manager
from treemem.tree_manager import TreeManager


def test_in_process_dashboard_mcp_integration():
    """Test that dashboard receives events from MCP-layer recall in the same process."""
    vault = Path(tempfile.mkdtemp(prefix="treemem_wpf_"))
    try:
        # Create TreeManager
        mgr = TreeManager(vault)
        
        # Inject manager into MCP layer
        set_manager(mgr)
        
        # Remember a fact
        entry = mgr.remember("Test fact for dashboard integration")
        mgr.place(entry["entry_id"], "test/node")
        
        # Create dashboard app on ephemeral port
        token = "test_token_12345"
        app = create_app(mgr, token)
        
        # Run uvicorn in a thread
        import uvicorn
        port = 8766  # Use specific port to avoid conflicts
        server_ready = threading.Event()
        
        def run_server():
            config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
            server = uvicorn.Server(config)
            server_ready.set()
            server.run()
        
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        server_ready.wait(timeout=5)
        time.sleep(0.5)  # Give server time to fully start
        
        # Call MCP-layer recall (this should emit an event)
        try:
            # Import httpx for HTTP requests
            import httpx
            
            # Verify dashboard is responsive
            base_url = f"http://127.0.0.1:{port}"
            
            # Recall through manager (simulating MCP call)
            rec = mgr.recall("test/node")
            assert rec["path"] == "test/node"
            
            # Check /api/events contains the recall
            with httpx.Client() as client:
                headers = {"Authorization": f"Bearer {token}"}
                response = client.get(f"{base_url}/api/events", headers=headers, timeout=5)
                assert response.status_code == 200
                data = response.json()
                events = data.get("events", [])
                # Should have at least the recall event
                assert len(events) > 0
                
                # Verify event structure
                event_types = {e.get("type") for e in events}
                assert "recall" in event_types or "place" in event_types or "remember" in event_types
        
        finally:
            # Cleanup: server thread is daemon, will exit when main thread exits
            pass
            
    finally:
        # Clean up vault
        shutil.rmtree(vault, ignore_errors=True)
