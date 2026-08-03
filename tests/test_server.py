"""Tests for docker-hub-mcp server."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

# ── import / smoke tests ──────────────────────────────────────────────────────


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


# ── _normalize_image ──────────────────────────────────────────────────────────


class TestNormalizeImage:
    """Tests for _normalize_image."""

    def test_library_image(self):
        from docker_hub_mcp.server import _normalize_image
        assert _normalize_image("nginx") == ("library", "nginx")

    def test_user_image(self):
        from docker_hub_mcp.server import _normalize_image
        assert _normalize_image("grafana/grafana") == ("grafana", "grafana")

    def test_explicit_library(self):
        from docker_hub_mcp.server import _normalize_image
        assert _normalize_image("library/ubuntu") == ("library", "ubuntu")

    def test_valid_with_separators(self):
        """Valid Docker Hub names with separators."""
        from docker_hub_mcp.server import _normalize_image
        assert _normalize_image("my-org/my_image") == ("my-org", "my_image")
        assert _normalize_image("org.name/repo.name") == ("org.name", "repo.name")

    # ── edge cases that raise ValueError ──────────────────────────────────

    def test_empty_string_raises(self):
        """Edge: empty string raises ValueError."""
        from docker_hub_mcp.server import _normalize_image
        with pytest.raises(ValueError, match="non-empty"):
            _normalize_image("")

    def test_multi_segment_raises(self):
        """Edge: more than one slash raises ValueError."""
        from docker_hub_mcp.server import _normalize_image
        with pytest.raises(ValueError, match="too many path segments"):
            _normalize_image("a/b/c")

    def test_special_chars_raises(self):
        """Edge: invalid characters raise ValueError."""
        from docker_hub_mcp.server import _normalize_image
        with pytest.raises(ValueError, match="Invalid namespace"):
            _normalize_image("FOO/bar")
        with pytest.raises(ValueError, match="Invalid namespace"):
            _normalize_image("foo!@#/bar")

    def test_trailing_slash_raises(self):
        """Edge: trailing slash causes empty repo, raises ValueError."""
        from docker_hub_mcp.server import _normalize_image
        with pytest.raises(ValueError, match="repo cannot be empty"):
            _normalize_image("foo/")

    def test_only_slash_raises(self):
        """Edge: '/' has empty namespace, raises ValueError."""
        from docker_hub_mcp.server import _normalize_image
        with pytest.raises(ValueError, match="namespace cannot be empty"):
            _normalize_image("/")

    def test_leading_slash_raises(self):
        """Edge: '/foo' has empty namespace, raises ValueError."""
        from docker_hub_mcp.server import _normalize_image
        with pytest.raises(ValueError, match="namespace cannot be empty"):
            _normalize_image("/foo")


# ── _fmt_num ──────────────────────────────────────────────────────────────────


class TestFmtNum:
    """Tests for _fmt_num."""

    def test_small(self):
        from docker_hub_mcp.server import _fmt_num
        assert _fmt_num(500) == "500"

    def test_thousands(self):
        from docker_hub_mcp.server import _fmt_num
        assert _fmt_num(1500) == "1,500"

    def test_millions(self):
        from docker_hub_mcp.server import _fmt_num
        assert _fmt_num(2_500_000) == "2.5M"

    def test_billions(self):
        from docker_hub_mcp.server import _fmt_num
        assert _fmt_num(13_200_000_000) == "13.2B"

    def test_zero(self):
        from docker_hub_mcp.server import _fmt_num
        assert _fmt_num(0) == "0"

    def test_none(self):
        from docker_hub_mcp.server import _fmt_num
        assert _fmt_num(None) == "None"

    def test_non_numeric_string(self):
        from docker_hub_mcp.server import _fmt_num
        assert _fmt_num("abc") == "abc"

    def test_float(self):
        from docker_hub_mcp.server import _fmt_num
        assert _fmt_num(1500.0) == "1,500"

    def test_negative(self):
        from docker_hub_mcp.server import _fmt_num
        assert _fmt_num(-500) == "-500"


# ── _extract_image_info ───────────────────────────────────────────────────────


class TestExtractImageInfo:
    """Tests for _extract_image_info."""

    def test_valid_dict(self):
        from docker_hub_mcp.server import _extract_image_info
        result = _extract_image_info({
            "name": "nginx",
            "namespace": "library",
            "description": "Official Nginx",
            "pull_count": 1000000000,
            "star_count": 5000,
            "is_official": True,
            "is_verified": True,
            "is_automated": False,
            "last_updated": "2024-01-01T00:00:00Z",
            "date_registered": "2023-01-01T00:00:00Z",
            "affiliation": "Docker Inc",
            "user": "docker",
        })
        assert result["name"] == "nginx"
        assert result["namespace"] == "library"
        assert result["pull_count"] == 1000000000
        assert result["star_count"] == 5000
        assert result["is_official"] is True
        assert result["hub_user"] == "docker"

    def test_missing_keys_defaults(self):
        from docker_hub_mcp.server import _extract_image_info
        result = _extract_image_info({})
        assert result["name"] == ""
        assert result["namespace"] == ""
        assert result["pull_count"] == 0
        assert result["star_count"] == 0
        assert result["is_official"] is False
        assert result["last_updated"] == ""

    def test_none_input(self):
        from docker_hub_mcp.server import _extract_image_info
        assert _extract_image_info(None) is None

    def test_list_input(self):
        from docker_hub_mcp.server import _extract_image_info
        assert _extract_image_info(["a", "b"]) is None

    def test_string_input(self):
        from docker_hub_mcp.server import _extract_image_info
        assert _extract_image_info("nginx") is None

    def test_int_input(self):
        from docker_hub_mcp.server import _extract_image_info
        assert _extract_image_info(42) is None


# ── _text ─────────────────────────────────────────────────────────────────────


class TestText:
    """Tests for _text helper."""

    def test_returns_list_of_text_content(self):
        from docker_hub_mcp.server import TextContent, _text
        result = _text("hello")
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].type == "text"
        assert result[0].text == "hello"

    def test_empty_string(self):
        from docker_hub_mcp.server import _text
        result = _text("")
        assert len(result) == 1
        assert result[0].text == ""

    def test_multiline(self):
        from docker_hub_mcp.server import _text
        result = _text("line1\nline2\nline3")
        assert result[0].text == "line1\nline2\nline3"


# ── _fetch_json (mocked HTTP) ─────────────────────────────────────────────────


class TestFetchJson:
    """Tests for _fetch_json with mocked HTTP responses."""

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_successful_response(self, httpx_mock):
        from docker_hub_mcp.server import _fetch_json
        httpx_mock.add_response(
            url="https://hub.docker.com/v2/repositories/library/nginx",
            json={"name": "nginx", "pull_count": 1000000000},
        )
        async with httpx.AsyncClient() as client:
            result = await _fetch_json(
                client, "https://hub.docker.com/v2/repositories/library/nginx"
            )
        assert result == {"name": "nginx", "pull_count": 1000000000}

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_404_returns_none(self, httpx_mock):
        from docker_hub_mcp.server import _fetch_json
        httpx_mock.add_response(
            url="https://hub.docker.com/v2/repositories/library/nonexistent",
            status_code=404,
        )
        async with httpx.AsyncClient() as client:
            result = await _fetch_json(
                client, "https://hub.docker.com/v2/repositories/library/nonexistent"
            )
        assert result is None

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_429_then_success(self, httpx_mock):
        from docker_hub_mcp.server import _fetch_json
        url = "https://hub.docker.com/v2/repositories/library/nginx"
        httpx_mock.add_response(url=url, status_code=429)
        httpx_mock.add_response(url=url, json={"name": "nginx"})
        async with httpx.AsyncClient() as client:
            result = await _fetch_json(client, url)
        assert result == {"name": "nginx"}

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_429_all_retries_exhausted(self, httpx_mock):
        from docker_hub_mcp.server import MAX_RETRIES, _fetch_json
        url = "https://hub.docker.com/v2/repositories/library/nginx"
        for _ in range(MAX_RETRIES):
            httpx_mock.add_response(url=url, status_code=429)
        async with httpx.AsyncClient() as client:
            result = await _fetch_json(client, url)
        assert result is None

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_5xx_retries_exhausted(self, httpx_mock):
        from docker_hub_mcp.server import MAX_RETRIES, _fetch_json
        url = "https://hub.docker.com/v2/repositories/library/nginx"
        for _ in range(MAX_RETRIES):
            httpx_mock.add_response(url=url, status_code=500)
        async with httpx.AsyncClient() as client:
            result = await _fetch_json(client, url)
        assert result is None

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_network_error_retries(self, httpx_mock):
        from docker_hub_mcp.server import _fetch_json
        url = "https://hub.docker.com/v2/repositories/library/nginx"
        httpx_mock.add_exception(httpx.ConnectError("connection refused"), url=url)
        async with httpx.AsyncClient() as client:
            result = await _fetch_json(client, url)
        assert result is None

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_network_error_then_success(self, httpx_mock):
        from docker_hub_mcp.server import _fetch_json
        url = "https://hub.docker.com/v2/repositories/library/nginx"
        httpx_mock.add_exception(httpx.ConnectError("timeout"), url=url)
        httpx_mock.add_response(url=url, json={"name": "nginx"})
        async with httpx.AsyncClient() as client:
            result = await _fetch_json(client, url)
        assert result == {"name": "nginx"}


# ── handler output formatting (mocked HTTP) ───────────────────────────────────


class TestGetImageStatsImpl:
    """Tests for get_image_stats_impl output formatting."""

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_successful_response(self, httpx_mock):
        from docker_hub_mcp.server import get_image_stats_impl
        httpx_mock.add_response(
            url="https://hub.docker.com/v2/repositories/library/nginx",
            json={
                "name": "nginx",
                "namespace": "library",
                "description": "Official build of Nginx",
                "pull_count": 1000000000,
                "star_count": 15000,
                "is_official": True,
                "is_verified": True,
                "is_automated": False,
                "last_updated": "2024-06-15T10:00:00Z",
                "date_registered": "2013-01-01T00:00:00Z",
                "affiliation": "",
                "user": "",
            },
        )
        result = await get_image_stats_impl("nginx")
        assert "# library/nginx" in result
        assert "**Description:** Official build of Nginx" in result
        assert "**Pull count:** 1.0B" in result
        assert "**Star count:** 15,000" in result
        assert "**Official:** ✓ Yes" in result
        assert "**Verified:** ✓ Yes" in result
        assert "**Last updated:** 2024-06-15T10:00:00Z" in result

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_image_not_found(self, httpx_mock):
        from docker_hub_mcp.server import get_image_stats_impl
        httpx_mock.add_response(
            url="https://hub.docker.com/v2/repositories/library/nonexistent",
            status_code=404,
        )
        result = await get_image_stats_impl("nonexistent")
        assert "not found" in result
        assert "nonexistent" in result

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_retry_exhaustion_returns_not_found(self, httpx_mock):
        from docker_hub_mcp.server import MAX_RETRIES, get_image_stats_impl
        url = "https://hub.docker.com/v2/repositories/library/nginx"
        for _ in range(MAX_RETRIES):
            httpx_mock.add_response(url=url, status_code=429)
        result = await get_image_stats_impl("nginx")
        assert "not found" in result

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    async def test_image_without_description(self, httpx_mock):
        from docker_hub_mcp.server import get_image_stats_impl
        httpx_mock.add_response(
            url="https://hub.docker.com/v2/repositories/library/nginx",
            json={
                "name": "nginx",
                "namespace": "library",
                "description": "",
                "pull_count": 100,
                "star_count": 10,
                "is_official": False,
                "is_verified": False,
                "is_automated": False,
                "last_updated": "",
                "date_registered": "",
                "affiliation": "",
                "user": "",
            },
        )
        result = await get_image_stats_impl("nginx")
        assert "**Description:** (none)" in result
        assert "**Affiliation:** (none)" in result
        assert "**Hub user:** (none)" in result


class TestSearchImagesImpl:
    """Tests for search_images_impl output formatting."""

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True, assert_all_responses_were_requested=False)
    async def test_search_with_results(self, httpx_mock):
        from docker_hub_mcp.server import search_images_impl
        httpx_mock.add_response(
            json={
                "results": [
                    {
                        "repo_name": "nginx",
                        "repo_owner": "library",
                        "short_description": "Official build of Nginx",
                        "pull_count": 1000000000,
                        "star_count": 15000,
                        "is_official": True,
                        "is_automated": False,
                    },
                    {
                        "repo_name": "nginxinc/nginx",
                        "repo_owner": "nginxinc",
                        "short_description": "NGINX Open Source",
                        "pull_count": 50000000,
                        "star_count": 500,
                        "is_official": False,
                        "is_automated": True,
                    },
                ],
                "total": 2,
            },
        )
        result = await search_images_impl("nginx", limit=2)
        assert "Search results for 'nginx'" in result
        assert "nginx" in result
        assert "1.0B" in result
        assert "✓ OFFICIAL" in result
        assert "[AUTO]" in result
        assert "Official build of Nginx" in result

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True, assert_all_responses_were_requested=False)
    async def test_search_no_results(self, httpx_mock):
        from docker_hub_mcp.server import search_images_impl
        httpx_mock.add_response(json={"results": [], "total": 0})
        result = await search_images_impl("zzznotfound", limit=10)
        assert "No results found for 'zzznotfound'" in result

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True, assert_all_responses_were_requested=False)
    async def test_search_api_404(self, httpx_mock):
        from docker_hub_mcp.server import search_images_impl
        httpx_mock.add_response(status_code=404)
        result = await search_images_impl("nginx", limit=10)
        assert "No results found for 'nginx'" in result

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True, assert_all_responses_were_requested=False)
    async def test_limit_clamping(self, httpx_mock):
        from docker_hub_mcp.server import search_images_impl
        httpx_mock.add_response(
            json={"results": [{"repo_name": "nginx", "pull_count": 100, "star_count": 10}]},
        )
        result = await search_images_impl("nginx", limit=0)
        assert "1 results" in result or "Search results" in result


# ── startup test (no sleep race) ──────────────────────────────────────────────


def test_server_initializes():
    """Verify the MCP server initializes via stdio — no race condition (uses communicate)."""
    server_path = Path(__file__).parent.parent
    server_script = str(server_path / ".venv" / "bin" / "docker-hub-mcp")

    init = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    })
    proc = subprocess.Popen(
        [server_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(server_path),
    )
    out, err = proc.communicate(input=init + "\n", timeout=15)
    assert '"result"' in out, f"Init failed. stdout: {out[:500]}\nstderr: {err[:500]}"
    assert '"serverInfo"' in out, f"No serverInfo. stdout: {out[:500]}\nstderr: {err[:500]}"