# Docker Hub MCP Server

A Model Context Protocol (MCP) server for querying Docker Hub image statistics. Provides pull counts, star counts, descriptions, official/verified status, and publisher catalogs through the public Docker Hub API — no API key required.

## Features

- **`get_image_stats(image)`** — single image metadata (pulls, stars, last_updated, description, is_official, is_verified)
- **`search_images(query, limit)`** — keyword search across Docker Hub
- **`batch_image_stats(images)`** — concurrent lookup for up to 100 images
- **`get_publisher_images(publisher, limit)`** — catalog all images from a namespace (e.g. `library`, `bitnami`, `grafana`)

## Installation

### uv (recommended)

```bash
uvx docker-hub-mcp
```

### pip

```bash
pip install docker-hub-mcp
docker-hub-mcp
```

## Configuration

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "docker-hub-mcp": {
      "command": "uvx",
      "args": ["docker-hub-mcp"]
    }
  }
}
```

### Cursor / VS Code

Add to your MCP configuration:

```json
{
  "mcpServers": {
    "docker-hub-mcp": {
      "command": "uvx",
      "args": ["docker-hub-mcp"]
    }
  }
}
```

### Hermes Agent (MCP Gateway)

Add to `~/.hermes/gateway.yaml`:

```yaml
docker-hub-mcp:
  command: uvx docker-hub-mcp
  lazy_spawn: true
  timeout: 30s
  env: {}
```

## Tools

| Tool | Description | Key Params |
|------|-------------|-----------|
| `get_image_stats` | Pull count, star count, last updated, description, official/verified status | `image` (required) — `"nginx"` or `"grafana/grafana"` |
| `search_images` | Keyword search, ranked results | `query` (required), `limit` (default 50) |
| `batch_image_stats` | Concurrent lookup of up to 100 images | `images` (required, list) |
| `get_publisher_images` | All images in a namespace | `publisher` (required), `limit` (default 100) |

## Examples

```python
# Get stats for nginx
get_image_stats({"image": "nginx"})
# → pull_count: 13.2B, star_count: 21K, is_official: true

# Search for postgres
search_images({"query": "postgres", "limit": 5})
# → ranked results with pulls, stars, official flags

# Batch compare web servers
batch_image_stats({"images": ["nginx", "httpd", "caddy", "traefik"]})

# Catalog a publisher
get_publisher_images({"publisher": "bitnami", "limit": 25})
```

## Data Source

Uses the [Docker Hub API](https://docs.docker.com/docker-hub/api/latest/) (`/v2/repositories` and `/v2/search`).

- **Auth:** None required for public data
- **Rate limit:** ~4,400 requests per 6 hours (unauthenticated)

## Development

```bash
git clone https://github.com/GeniusTechnoMystic/docker-hub-mcp.git
cd docker-hub-mcp
uv sync
uv run docker-hub-mcp
```

Run tests:

```bash
uv run pytest tests/
```

## License

MIT