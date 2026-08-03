# ── docker-hub-mcp ────────────────────────────────────────────────────────────
set positional := false

project := "docker-hub-mcp"

_default:
  just --list

# Install dependencies
sync:
    uv sync

# Run the server (stdio)
run:
    uv run {{ project }}

# Run tests
test:
    uv run pytest tests/ -v

# Lint
lint:
    uv run ruff check .

# Format
fmt:
    uv run ruff format .

# Build
build:
    uv build

# Release (tag + publish)
release tag:
    git tag v{{ tag }}
    git push origin v{{ tag }}

# Clean
clean:
    rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache __pycache__

# Show version
version:
    @grep '^version' pyproject.toml | cut -d'"' -f2