"""Unit tests for src/mcp_discovery/data/transport_spec.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mcp_discovery.data.transport_spec import (
    HttpTransportSpec,
    ScriptTransportSpec,
    StdioTransportSpec,
    load_transports_yaml,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "transports.yaml"
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# StdioTransportSpec — version pin validation
# ---------------------------------------------------------------------------


class TestStdioVersionPin:
    def test_accepts_pinned_version(self):
        spec = StdioTransportSpec(
            server_id="test",
            transport="stdio",
            command="npx -y @foo/bar@1.2.3",
        )
        assert spec.command == "npx -y @foo/bar@1.2.3"

    def test_accepts_prerelease_version(self):
        spec = StdioTransportSpec(
            server_id="test",
            transport="stdio",
            command="npx -y @foo/bar@1.2.3-beta.1",
        )
        assert spec.command == "npx -y @foo/bar@1.2.3-beta.1"

    def test_accepts_date_version(self):
        spec = StdioTransportSpec(
            server_id="test",
            transport="stdio",
            command="npx -y @modelcontextprotocol/server-github@2024.11.5",
        )
        assert "2024.11.5" in spec.command

    def test_accepts_smithery_cli_sub_command(self):
        """Smithery CLI pattern: npx -y @smithery/cli@0.1.0 run @smithery-ai/github.
        The sub-command target (@smithery-ai/github) need not be versioned."""
        spec = StdioTransportSpec(
            server_id="github",
            transport="stdio",
            command="npx -y @smithery/cli@0.1.0 run @smithery-ai/github",
        )
        assert spec.server_id == "github"

    def test_rejects_latest_tag(self):
        with pytest.raises(ValueError, match="latest"):
            StdioTransportSpec(
                server_id="test",
                transport="stdio",
                command="npx -y @foo/bar@latest",
            )

    def test_rejects_next_tag(self):
        with pytest.raises(ValueError, match="@next"):
            StdioTransportSpec(
                server_id="test",
                transport="stdio",
                command="npx -y @foo/bar@next",
            )

    def test_rejects_beta_tag(self):
        with pytest.raises(ValueError, match="beta"):
            StdioTransportSpec(
                server_id="test",
                transport="stdio",
                command="npx -y @foo/bar@beta",
            )

    def test_rejects_unpinned_primary_package(self):
        """npx -y @foo/bar (no version at all) must be rejected."""
        with pytest.raises(ValueError, match="version pin"):
            StdioTransportSpec(
                server_id="test",
                transport="stdio",
                command="npx -y @foo/bar",
            )


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


class TestLoadTransportsYaml:
    def test_loads_stdio_entry(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path,
            """
            servers:
              my-server:
                transport: stdio
                command: "npx -y @test/pkg@1.0.0"
                env: {}
            """,
        )
        specs = load_transports_yaml(p)
        assert "my-server" in specs
        assert isinstance(specs["my-server"], StdioTransportSpec)
        assert specs["my-server"].server_id == "my-server"

    def test_loads_http_entry(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path,
            """
            servers:
              http-server:
                transport: http
                url: "https://example.com/mcp"
            """,
        )
        specs = load_transports_yaml(p)
        assert "http-server" in specs
        assert isinstance(specs["http-server"], HttpTransportSpec)
        assert specs["http-server"].url == "https://example.com/mcp"

    def test_loads_script_entry(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path,
            """
            servers:
              script-server:
                transport: script
                script_path: "/opt/my_server.py"
            """,
        )
        specs = load_transports_yaml(p)
        assert isinstance(specs["script-server"], ScriptTransportSpec)

    def test_loads_real_transports_yaml(self):
        """Load the actual seed file bundled with the project."""
        real_path = Path("src/mcp_discovery/data/transports.yaml")
        if not real_path.exists():
            pytest.skip("transports.yaml not found at expected path")
        specs = load_transports_yaml(real_path)
        assert len(specs) >= 1

    def test_raises_on_latest_in_yaml(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path,
            """
            servers:
              bad-server:
                transport: stdio
                command: "npx -y @foo/bar@latest"
            """,
        )
        with pytest.raises(ValueError, match="failed validation"):
            load_transports_yaml(p)

    def test_raises_on_unknown_transport_kind(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path,
            """
            servers:
              unknown-server:
                transport: websocket
                url: "ws://example.com"
            """,
        )
        with pytest.raises(ValueError, match="unknown transport kind"):
            load_transports_yaml(p)

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_transports_yaml("/nonexistent/path/transports.yaml")

    def test_empty_servers_returns_empty(self, tmp_path: Path):
        p = _write_yaml(tmp_path, "servers: {}")
        specs = load_transports_yaml(p)
        assert specs == {}

    def test_missing_servers_key_returns_empty(self, tmp_path: Path):
        p = tmp_path / "transports.yaml"
        p.write_text("# no servers key\n")
        specs = load_transports_yaml(p)
        assert specs == {}
