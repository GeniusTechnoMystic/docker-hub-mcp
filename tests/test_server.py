"""Tests for docker-hub-mcp server."""
import json
import subprocess
import sys
from pathlib import Path


def test_server_imports():
    """Verify the server module imports without errors."""
    import docker_hub_mcp.server  # noqa: F401
    assert True


def test_tool_list():
    """Verify the TOOLS list has all 4 expected tools."""
    from docker_hub_mcp.server import TOOLS
    tool_names = {t.name for t in TOOLS}
    expected = {"get_image_stats", "search_images", "batch_image_stats", "get_publisher_images"}
    assert tool_names == expected, f"Expected {expected}, got {tool_names}"


def test_image_normalize():
    """Verify _normalize_image works for both official and user images."""
    from docker_hub_mcp.server import _normalize_image
    assert _normalize_image("nginx") == ("library", "nginx")
    assert _normalize_image("grafana/grafana") == ("grafana", "grafana")
    assert _normalize_image("library/ubuntu") == ("library", "ubuntu")


def test_fmt_num():
    """Verify _fmt_num formats numbers correctly."""
    from docker_hub_mcp.server import _fmt_num
    assert _fmt_num(500) == "500"
    assert _fmt_num(1500) == "1,500"
    assert _fmt_num(2_500_000) == "2.5M"
    assert _fmt_num(13_200_000_000) == "13.2B"


def test_server_initializes():
    """Verify the MCP server initializes via stdio."""
    server_path = Path(__file__).parent.parent
    proc = subprocess.Popen(
        [sys.executable, "-m", "uv", "run", "docker-hub-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(server_path),
    )
    init = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    })
    proc.stdin.write(init + "\n")
    proc.stdin.flush()
    import time
    time.sleep(0.5)
    proc.stdin.close()
    out, _ = proc.communicate(timeout=15)
    assert '"result"' in out, f"Init failed: {out[:200]}"
    assert '"serverInfo"' in out, f"No serverInfo: {out[:200]}"