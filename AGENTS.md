# docker-hub-mcp

An MCP server providing Docker Hub image statistics via the public Docker Hub API.

## Project commands

```bash
uv sync                    # install dependencies
uv run docker-hub-mcp       # run the server (stdio)
uv run pytest tests/        # run tests
uv run ruff check .         # lint
uv build                    # build package
```

## MCP server pattern

This is a stdio-based MCP server. It reads JSON-RPC messages from stdin and writes responses to stdout. No HTTP server, no file I/O.

## Project structure

- `src/docker_hub_mcp/server.py` — main server, 404 lines, all logic in one file
- `tests/test_server.py` — unit + integration tests
- `pyproject.toml` — managed by `uv`

## Updating

- Keep `pyproject.toml` dependencies synced with `uv sync`
- Bump version in `pyproject.toml` before tagging
- Tag with `v*` triggers PyPI publish via CI