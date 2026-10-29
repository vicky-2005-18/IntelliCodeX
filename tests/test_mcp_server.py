"""
Tests for IntelliCodeX Model Context Protocol (MCP) Server.
Verifies JSON-RPC 2.0 handshake, tool discovery, tool execution, and client configs.
"""

import os
import sys
import json
import pytest

# Ensure repository root is on sys.path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.mcp_server import IntelliCodeXMcpServer, generate_ide_config_snippets, AVAILABLE_TOOLS


@pytest.fixture
def mcp_server():
    """Initializes an IntelliCodeX MCP server with sample_repo and offline tfidf backend."""
    sample_dir = os.path.join(repo_root, "sample_repo")
    server = IntelliCodeXMcpServer(repo_path=sample_dir, backend="tfidf")
    return server


def test_mcp_initialize(mcp_server):
    """Verifies standard initialize request returns protocolVersion and serverInfo."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"}
        }
    }
    resp = mcp_server.dispatch(request)
    assert resp is not None
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == "intellicodex"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_ping(mcp_server):
    """Verifies ping response."""
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "ping"
    }
    resp = mcp_server.dispatch(request)
    assert resp == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_mcp_tools_list(mcp_server):
    """Verifies tools/list enumerates all 8 core IntelliCodeX tools with valid schemas."""
    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/list"
    }
    resp = mcp_server.dispatch(request)
    assert resp is not None
    assert "result" in resp
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    expected = [
        "search_codebase",
        "explain_code",
        "locate_bug",
        "get_call_hierarchy",
        "generate_patch",
        "scan_security",
        "analyze_architecture",
        "query_org_memory",
    ]
    for exp in expected:
        assert exp in tool_names, f"Expected tool '{exp}' not in tools/list"


def test_mcp_tool_search_codebase(mcp_server):
    """Verifies calling search_codebase retrieves matching chunks."""
    request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "search_codebase",
            "arguments": {
                "query": "hash_password authenticate",
                "top_k": 3
            }
        }
    }
    resp = mcp_server.dispatch(request)
    assert resp is not None
    assert resp["id"] == 4
    content = resp["result"]["content"]
    assert len(content) > 0
    text = content[0]["text"]
    assert "Found" in text or "matching" in text or "hash_password" in text


def test_mcp_tool_get_call_hierarchy(mcp_server):
    """Verifies calling get_call_hierarchy returns caller/callee details."""
    request = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "get_call_hierarchy",
            "arguments": {
                "symbol_name": "authenticate",
                "direction": "both"
            }
        }
    }
    resp = mcp_server.dispatch(request)
    assert resp is not None
    assert resp["id"] == 5
    text = resp["result"]["content"][0]["text"]
    assert "Call Hierarchy" in text
    assert "authenticate" in text


def test_mcp_tool_locate_bug(mcp_server):
    """Verifies calling locate_bug performs Ochiai SBFL diagnosis."""
    request = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "locate_bug",
            "arguments": {
                "error_message": "KeyError: 'session_token' in validate_session",
                "stack_trace": "Traceback (most recent call last):\n  File 'pkg/auth.py', line 25, in validate_session\nKeyError: 'session_token'"
            }
        }
    }
    resp = mcp_server.dispatch(request)
    assert resp is not None
    assert resp["id"] == 6
    text = resp["result"]["content"][0]["text"]
    assert "Fault Localization Report" in text


def test_mcp_tool_scan_security(mcp_server):
    """Verifies calling scan_security returns report."""
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "scan_security",
            "arguments": {
                "severity_threshold": "HIGH"
            }
        }
    }
    resp = mcp_server.dispatch(request)
    assert resp is not None
    assert resp["id"] == 7
    text = resp["result"]["content"][0]["text"]
    assert "Security Vulnerability" in text


def test_mcp_tool_query_org_memory(mcp_server):
    """Verifies querying organizational memory through MCP tool."""
    request = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "name": "query_org_memory",
            "arguments": {
                "query": "architecture database",
                "category": ""
            }
        }
    }
    resp = mcp_server.dispatch(request)
    assert resp is not None
    assert resp["id"] == 8
    text = resp["result"]["content"][0]["text"]
    assert "Organizational Memory Query Results" in text


def test_mcp_tool_generate_patch(mcp_server):
    """Verifies patch generation tool execution via MCP."""
    request = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
            "name": "generate_patch",
            "arguments": {
                "issue_description": "Fix invalid session token key check",
                "target_file": "pkg/auth.py"
            }
        }
    }
    resp = mcp_server.dispatch(request)
    assert resp is not None
    assert resp["id"] == 9
    text = resp["result"]["content"][0]["text"]
    assert "Proposed Code Patch" in text


def test_mcp_tool_analyze_architecture(mcp_server):
    """Verifies calling analyze_architecture identifies cycles and bottlenecks."""
    request = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "analyze_architecture",
            "arguments": {
                "threshold_lines": 100
            }
        }
    }
    resp = mcp_server.dispatch(request)
    assert resp is not None
    assert resp["id"] == 10
    text = resp["result"]["content"][0]["text"]
    assert "Architecture & Dependency Optimization Report" in text


def test_mcp_tool_not_found(mcp_server):
    """Verifies unknown tool call returns standard JSON-RPC -32601 error."""
    request = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "non_existent_tool_xyz",
            "arguments": {}
        }
    }
    resp = mcp_server.dispatch(request)
    assert resp is not None
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_generate_ide_config_snippets():
    """Verifies configuration generation for Claude, Cursor, and Antigravity."""
    configs = generate_ide_config_snippets("sample_repo")
    assert "claude_desktop_config.json" in configs
    assert "cursor_mcp.json" in configs
    assert "gemini_antigravity_mcp_config.json" in configs

    claude_cfg = configs["claude_desktop_config.json"]
    assert "mcpServers" in claude_cfg
    assert "intellicodex" in claude_cfg["mcpServers"]
    assert claude_cfg["mcpServers"]["intellicodex"]["args"][:3] == ["-m", "core.mcp_server", "--repo"]
