"""Tests for MCP stdio protocol and tool execution."""

import json
import subprocess
import sys
from pathlib import Path


def test_mcp_stdio_lifecycle():
    sample_vault = str(Path("examples/sample_memory").resolve())
    python_bin = sys.executable

    proc = subprocess.Popen(
        [python_bin, "-m", "treemem.mcp_layer", sample_vault],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        def send_rpc(obj):
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            return json.loads(line) if line else None

        # 1. Initialize
        init_res = send_rpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-harness", "version": "1.0"},
            },
        })
        assert init_res is not None
        assert init_res.get("result", {}).get("serverInfo", {}).get("name") == "treemem"

        # 2. Initialized notification
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        # 3. List tools
        tools_res = send_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert tools_res is not None
        tool_names = [t["name"] for t in tools_res.get("result", {}).get("tools", [])]
        expected_tools = ["remember", "place", "recall", "expand", "compress", "commit_summary", "search", "split", "rebuild", "status"]
        for t in expected_tools:
            assert t in tool_names

        # 4. Call recall tool
        call_res = send_rpc({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "recall", "arguments": {"path": "/"}},
        })
        assert call_res is not None
        raw_text = call_res["result"]["content"][0]["text"]
        parsed_recall = json.loads(raw_text)
        assert parsed_recall["path"] == "/"
        assert "summary" in parsed_recall
        assert len(parsed_recall["children"]) > 0

        # 5. Call status tool
        status_res = send_rpc({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "status", "arguments": {}},
        })
        assert status_res is not None
        parsed_status = json.loads(status_res["result"]["content"][0]["text"])
        assert parsed_status["status"] == "ready"
        assert parsed_status["total_nodes"] >= 20

    finally:
        proc.terminate()
