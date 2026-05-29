"""Regression checks for the local MCP compose stack."""

from __future__ import annotations

from pathlib import Path


def test_our_mcp_server_uses_project_dependency_image() -> None:
    compose = Path("compose.mcp.yaml").read_text()
    service_start = compose.index("  our-mcp-server-dev:")
    service_end = compose.index("\n  gateway:", service_start)
    service_block = compose[service_start:service_end]

    assert "dockerfile: service/api/Dockerfile" in service_block
    assert "env_file:" in service_block
    assert "- .env" in service_block
    assert "condition: service_healthy" in service_block
    assert 'MLP_FRONTEND_URL: "http://127.0.0.1:3001"' in service_block
    assert "python:3.12-slim" not in service_block
    assert "pip install --no-cache-dir fastapi uvicorn httpx" not in service_block
    assert "- /app/.venv/bin/uvicorn" in service_block
    assert "- service.mcp_server.local_app:app" in service_block

    backend_block = compose[compose.index("  backend:") : service_start]
    assert "healthcheck:" in backend_block
    assert "urllib.request.urlopen('http://127.0.0.1:3000/health').read()" in backend_block
