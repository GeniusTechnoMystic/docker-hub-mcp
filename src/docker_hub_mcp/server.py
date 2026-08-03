"""
Docker Hub Image Stats — MCP Server

Wraps the Docker Hub public API (v2 repositories, v1 search).
No API key required. Rate-limited to ~4400 requests per 6h for unauthenticated clients.

Tools:
  - get_image_stats(image)         — single image metadata (pulls, stars, last_updated, etc.)
  - search_images(query, limit)    — keyword search against Docker Hub
  - batch_image_stats(images)      — concurrent lookup for up to 100 images
  - get_publisher_images(publisher, limit) — list all images for a namespace
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)

logger = logging.getLogger("docker-hub-mcp")

DOCKER_HUB_BASE = "https://hub.docker.com"
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds
BATCH_MAX = 100

# ── shared HTTP client ─────────────────────────────────────────────────────────

_shared_client: httpx.AsyncClient = httpx.AsyncClient(
    limits=httpx.Limits(
        max_keepalive_connections=10,
        max_connections=20,
        keepalive_expiry=30.0,
    ),
    timeout=httpx.Timeout(
        connect=10.0,
        read=15.0,
        write=10.0,
        pool=10.0,
    ),
)

# ── validation ─────────────────────────────────────────────────────────────────

VALID_IMAGE_SEGMENT = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


def _validate_image_segment(name: str, label: str) -> str:
    """Validate a single Docker Hub image name segment (namespace or repo).

    Raises ValueError with a clear message if the segment is invalid.
    """
    if not name:
        raise ValueError(f"{label} cannot be empty")
    if len(name) > 128:
        raise ValueError(f"{label} too long: {len(name)} chars (max 128)")
    if not VALID_IMAGE_SEGMENT.fullmatch(name):
        raise ValueError(
            f"Invalid {label} '{name}': must match [a-z0-9]+(?:[._-][a-z0-9]+)*"
        )
    return name


# ── helpers ──────────────────────────────────────────────────────────────────


def _normalize_image(image: str) -> tuple[str, str]:
    """Return (namespace, repo) for a Docker image reference.

    Validates both segments against Docker Hub naming rules and URL-quotes them.
    Raises ValueError if the image name is invalid.
    """
    if not image or not isinstance(image, str):
        raise ValueError("Image name must be a non-empty string")
    if image.count("/") > 1:
        raise ValueError(
            f"Invalid image name '{image}': too many path segments (expected 1 or 0 slashes)"
        )
    parts = image.split("/")
    if len(parts) == 1:
        namespace = "library"
        repo = parts[0]
    else:
        namespace = parts[0]
        repo = parts[1]
    namespace = _validate_image_segment(namespace, "namespace")
    repo = _validate_image_segment(repo, "repo")
    return namespace, repo


async def _fetch_json(
    client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """GET a URL and return parsed JSON, with basic retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url, params=params, timeout=15.0)
            if resp.status_code == 429:
                logger.warning("Rate limited on %s, retrying...", url)
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None  # not found — not retryable
            last_exc = exc
            logger.warning("HTTP error on %s: %s", url, exc)
        except httpx.RequestError as exc:
            last_exc = exc
            logger.warning("Request error on %s: %s", url, exc)
        await asyncio.sleep(RETRY_DELAY)
    logger.error("All %d retries exhausted for %s", MAX_RETRIES, url)
    return None


def _extract_image_info(data: Any) -> dict[str, Any] | None:
    """Normalise a v2 single-repo response into a flat dict."""
    if not isinstance(data, dict):
        return None
    return {
        "name": data.get("name", ""),
        "namespace": data.get("namespace", ""),
        "description": data.get("description", ""),
        "pull_count": data.get("pull_count", 0),
        "star_count": data.get("star_count", 0),
        "is_official": data.get("is_official", False),
        "is_verified": data.get("is_verified", False),
        "is_automated": data.get("is_automated", False),
        "last_updated": data.get("last_updated", ""),
        "date_registered": data.get("date_registered", ""),
        "affiliation": data.get("affiliation", ""),
        "hub_user": data.get("user", ""),
    }


def _fmt_num(n: Any) -> str:
    """Format large numbers with friendly suffixes."""
    try:
        n_int = int(n)
    except (ValueError, TypeError):
        return str(n)
    if n_int >= 1_000_000_000:
        return f"{n_int / 1_000_000_000:.1f}B"
    if n_int >= 1_000_000:
        return f"{n_int / 1_000_000:.1f}M"
    if n_int >= 1_000:
        return f"{n_int:,}"
    return str(n_int)


def _text(content: str) -> list[TextContent]:
    """Wrap text in a list of TextContent for MCP tool results."""
    return [TextContent(type="text", text=content)]


# ── tool implementations ─────────────────────────────────────────────────────


async def get_image_stats_impl(image: str) -> str:
    namespace, repo = _normalize_image(image)
    url = f"{DOCKER_HUB_BASE}/v2/repositories/{quote(namespace, safe='')}/{quote(repo, safe='')}"
    data = await _fetch_json(_shared_client, url)
    if not isinstance(data, dict):
        return f"Image '{image}' not found on Docker Hub."
    info = _extract_image_info(data)
    lines = [
        f"# {info['namespace']}/{info['name']}",
        f"**Description:** {info['description'] or '(none)'}",
        f"**Pull count:** {_fmt_num(info['pull_count'])}",
        f"**Star count:** {_fmt_num(info['star_count'])}",
        f"**Official:** {'✓ Yes' if info['is_official'] else 'No'}",
        f"**Verified:** {'✓ Yes' if info['is_verified'] else 'No'}",
        f"**Automated build:** {'Yes' if info['is_automated'] else 'No'}",
        f"**Last updated:** {info['last_updated']}",
        f"**Registered:** {info['date_registered']}",
        f"**Affiliation:** {info['affiliation'] or '(none)'}",
        f"**Hub user:** {info['hub_user'] or '(none)'}",
    ]
    return "\n".join(lines)


async def search_images_impl(query: str, limit: int = 50) -> str:
    limit = min(max(limit, 1), 100)
    results: list[dict[str, Any]] = []
    page = 1
    fetched = 0

    while fetched < limit:
        params = {"query": query, "page": page, "page_size": min(limit - fetched, 50)}
        data = await _fetch_json(_shared_client, f"{DOCKER_HUB_BASE}/v2/search/repositories", params)
        if data is None:
            break
        items = data.get("results", []) if isinstance(data, dict) else []
        if not items:
            break
        for item in items:
            results.append({
                "name": item.get("repo_name", ""),
                "namespace": item.get("repo_owner", "library") or "library",
                "description": item.get("short_description", ""),
                "pull_count": item.get("pull_count", 0),
                "star_count": item.get("star_count", 0),
                "is_official": item.get("is_official", False),
                "is_automated": item.get("is_automated", False),
                "last_updated": "",
            })
            fetched += 1
            if fetched >= limit:
                break
        page += 1

    if not results:
        return f"No results found for '{query}'."

    lines = [f"# Search results for '{query}' ({len(results)} results)\n"]
    for i, r in enumerate(results, 1):
        full = f"{r['namespace']}/{r['name']}" if r['namespace'] != "library" else r['name']
        official = " ✓ OFFICIAL" if r["is_official"] else ""
        automated = " [AUTO]" if r["is_automated"] else ""
        pulls = _fmt_num(r["pull_count"])
        stars = _fmt_num(r["star_count"])
        desc = (r["description"] or "")[:120]
        lines.append(f"{i}. **{full}**{official}{automated} — {pulls} pulls, ⭐{stars}")
        if desc:
            lines.append(f"   {desc}")
    return "\n".join(lines)


async def batch_image_stats_impl(images: list[str]) -> str:
    if not images:
        return "No images provided."
    images = images[:BATCH_MAX]

    async def _fetch_single(img: str) -> tuple[str, dict[str, Any] | None]:
        namespace, repo = _normalize_image(img)
        url = f"{DOCKER_HUB_BASE}/v2/repositories/{quote(namespace, safe='')}/{quote(repo, safe='')}"
        data = await _fetch_json(_shared_client, url)
        return img, (_extract_image_info(data) if isinstance(data, dict) else None)

    tasks = [_fetch_single(img) for img in images]
    results = await asyncio.gather(*tasks)

    lines = [f"# Batch stats for {len(results)} images\n"]
    lines.append("| # | Image | Pulls | Stars | Official | Verified | Last Updated |")
    lines.append("|---|-------|-------|-------|----------|----------|-------------|")
    for i, (img, info) in enumerate(results, 1):
        if info is None:
            lines.append(f"| {i} | {img} | — | — | — | — | NOT FOUND |")
        else:
            official = "✓" if info["is_official"] else ""
            verified = "✓" if info["is_verified"] else ""
            lines.append(
                f"| {i} | {img} | {_fmt_num(info['pull_count'])} | {_fmt_num(info['star_count'])} | {official} | {verified} | {info['last_updated'][:10]} |"
            )
    return "\n".join(lines)


async def get_publisher_images_impl(publisher: str, limit: int = 100) -> str:
    limit = min(max(limit, 1), 500)
    results: list[dict[str, Any]] = []
    page = 1
    fetched = 0
    page_size = min(limit, 100)

    while fetched < limit:
        url = f"{DOCKER_HUB_BASE}/v2/repositories/{quote(_validate_image_segment(publisher, 'publisher'), safe='')}"
        params = {"page": page, "page_size": min(page_size, limit - fetched)}
        data = await _fetch_json(_shared_client, url, params)
        if data is None:
            break
        items = data.get("results", []) if isinstance(data, dict) else []
        if not items:
            break
        for item in items:
            info = _extract_image_info(item)
            if info is not None:
                results.append(info)
            fetched += 1
            if fetched >= limit:
                break
        page += 1

    if not results:
        return f"No images found for publisher '{publisher}'."

    lines = [f"# Images by {publisher} ({len(results)} total)\n"]
    lines.append("| # | Name | Pulls | Stars | Official | Verified | Description |")
    lines.append("|---|------|-------|-------|----------|----------|-------------|")
    for i, info in enumerate(results, 1):
        if info is None:
            continue
        official = "✓" if info["is_official"] else ""
        verified = "✓" if info["is_verified"] else ""
        desc = (info["description"] or "")[:60]
        lines.append(
            f"| {i} | {info['name']} | {_fmt_num(info['pull_count'])} | {_fmt_num(info['star_count'])} | {official} | {verified} | {desc} |"
        )
    return "\n".join(lines)


# ── tool schema ──────────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    Tool(
        name="get_image_stats",
        description="Fetch metadata for a single Docker Hub image. Accepts both 'library/nginx' and 'nginx' (auto-prepends 'library/') formats. Returns pulls, stars, description, official/verified status, last updated.",
        inputSchema={
            "type": "object",
            "properties": {
                "image": {
                    "type": "string",
                    "description": "Docker image name: 'nginx', 'python', 'grafana/grafana', etc.",
                }
            },
            "required": ["image"],
        },
    ),
    Tool(
        name="search_images",
        description="Search Docker Hub images by keyword. Returns results with name, namespace, description, pull_count, star_count, is_official, is_automated, and last_updated.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword (e.g. 'nginx', 'postgres', 'python').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (1-100, default: 50).",
                    "default": 50,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="batch_image_stats",
        description="Batch lookup metadata for up to 100 Docker Hub images in parallel. Pass a list of image names (e.g. ['nginx', 'python', 'grafana/grafana']). Returns a summary table with pulls, stars, and status for each.",
        inputSchema={
            "type": "object",
            "properties": {
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of Docker image names (max 100).",
                }
            },
            "required": ["images"],
        },
    ),
    Tool(
        name="get_publisher_images",
        description="List all images for a given publisher/namespace on Docker Hub. Useful for auditing an organisation's image catalog. Defaults to 100 results, max 500.",
        inputSchema={
            "type": "object",
            "properties": {
                "publisher": {
                    "type": "string",
                    "description": "Docker Hub namespace/publisher (e.g. 'library', 'grafana', 'nginx').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (1-500, default: 100).",
                    "default": 100,
                },
            },
            "required": ["publisher"],
        },
    ),
]

TOOL_HANDLERS = {
    "get_image_stats": get_image_stats_impl,
    "search_images": search_images_impl,
    "batch_image_stats": batch_image_stats_impl,
    "get_publisher_images": get_publisher_images_impl,
}


# ── request handlers ─────────────────────────────────────────────────────────


async def list_tools(
    ctx: ServerRequestContext, params: Any | None
) -> ListToolsResult:
    return ListToolsResult(tools=TOOLS)


async def call_tool(
    ctx: ServerRequestContext, params: CallToolRequestParams
) -> CallToolResult:
    name = params.name
    args = params.arguments or {}

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return CallToolResult(
            content=_text(f"Unknown tool: {name}"),
            isError=True,
        )

    try:
        result = await handler(**args)
        return CallToolResult(content=_text(result))
    except ValueError as exc:
        return CallToolResult(
            content=_text(f"Invalid input for {name}: {exc}"),
            isError=True,
        )
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return CallToolResult(
            content=_text(f"Error executing {name}: {exc}"),
            isError=True,
        )


# ── server ───────────────────────────────────────────────────────────────────

server = Server(
    "docker-hub-mcp",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)


async def main_async() -> None:
    async with stdio_server() as (read_stream, write_stream):
        try:
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        finally:
            await _shared_client.aclose()


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    asyncio.run(main_async())


if __name__ == "__main__":
    main()