"""Unit tests for pool_prober module (Track A, AC26).

Tests:
  - probe_server uses cache when available
  - probe_server bypasses cache with force=True
  - probe_server selects correct prober via registry
  - AC26: StdioProber output equals MCPDirectConnector.parse_tools() for same mock response
  - probe_servers returns dict keyed by server_id
  - secret-scan blocks cache write on match
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_discovery.data.mcp_connector import MCPDirectConnector
from mcp_discovery.data.pool_prober import (
    ProberRegistry,
    _write_cache,
    probe_server,
    probe_servers,
)
from mcp_discovery.data.probers.base import Prober
from mcp_discovery.data.probers.script_prober import ScriptProber
from mcp_discovery.data.probers.stdio_prober import StdioProber
from mcp_discovery.models.probe import (
    ProbeErrorKind,
    ProbeResult,
    RawToolInventory,
    TransportSpec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(transport: str = "stdio", server_id: str = "test-server") -> TransportSpec:
    return TransportSpec(transport=transport, server_id=server_id)


def _probe_result(server_id: str = "test-server", *, success: bool = True) -> ProbeResult:
    spec = _make_spec(server_id=server_id)
    spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
    if success:
        return ProbeResult(
            server_id=server_id,
            success=True,
            spec_hash=spec_hash,
            inventory=RawToolInventory(server_id=server_id, tools=[]),
        )
    return ProbeResult(
        server_id=server_id,
        success=False,
        spec_hash=spec_hash,
        error_kind=ProbeErrorKind.TIMEOUT,
        error_message="timeout",
    )


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestProberRegistry:
    def test_register_and_get(self) -> None:
        reg = ProberRegistry()
        prober = ScriptProber()
        reg.register("script", prober)
        assert reg.get("script") is prober

    def test_get_missing_returns_none(self) -> None:
        reg = ProberRegistry()
        assert reg.get("unknown") is None

    def test_get_for_spec_returns_correct_prober(self) -> None:
        reg = ProberRegistry()
        stdio_prober = StdioProber()
        reg.register("stdio", stdio_prober)
        spec = _make_spec("stdio")
        found = reg.get_for_spec(spec)
        assert found is stdio_prober

    def test_get_for_spec_no_match_returns_none(self) -> None:
        reg = ProberRegistry()
        spec = _make_spec("http")
        assert reg.get_for_spec(spec) is None

    def test_transports_lists_registered(self) -> None:
        reg = ProberRegistry()
        reg.register("stdio", StdioProber())
        reg.register("script", ScriptProber())
        assert sorted(reg.transports) == ["script", "stdio"]


# ---------------------------------------------------------------------------
# probe_server — cache logic
# ---------------------------------------------------------------------------


class TestProbeServerCache:
    async def test_cache_hit_returns_cached_result(self, tmp_path: Path) -> None:
        spec = _make_spec()
        spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
        cache_file = tmp_path / f"{spec_hash}.json"

        expected = _probe_result()
        cache_file.write_text(expected.model_dump_json())

        mock_prober = AsyncMock(spec=Prober)
        mock_prober.supports.return_value = True
        reg = ProberRegistry()
        reg.register("stdio", mock_prober)

        result = await probe_server("test-server", spec, registry=reg, cache_dir=tmp_path)

        assert result.server_id == "test-server"
        mock_prober.probe.assert_not_called()

    async def test_cache_bypass_with_force(self, tmp_path: Path) -> None:
        spec = _make_spec()
        spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
        cache_file = tmp_path / f"{spec_hash}.json"
        cache_file.write_text(_probe_result().model_dump_json())

        fresh_result = _probe_result(success=False)
        mock_prober = AsyncMock(spec=Prober)
        mock_prober.supports.return_value = True
        mock_prober.probe.return_value = fresh_result
        reg = ProberRegistry()
        reg.register("stdio", mock_prober)

        result = await probe_server(
            "test-server", spec, registry=reg, cache_dir=tmp_path, force=True
        )

        mock_prober.probe.assert_called_once()
        assert result.success is False

    async def test_no_prober_returns_unsupported(self, tmp_path: Path) -> None:
        spec = _make_spec("http")
        reg = ProberRegistry()  # empty registry

        result = await probe_server("test-server", spec, registry=reg, cache_dir=tmp_path)

        assert result.success is False
        assert result.error_kind == ProbeErrorKind.TRANSPORT_UNSUPPORTED


# ---------------------------------------------------------------------------
# AC26: StdioProber delegates to MCPDirectConnector.parse_tools
# ---------------------------------------------------------------------------


class TestDelegatesToParseTools:
    """AC26: StdioProber output equals MCPDirectConnector.parse_tools(server_id, mock_response)."""

    async def test_delegates_to_parse_tools(self, tmp_path: Path) -> None:
        """Test that StdioProber invokes MCPDirectConnector.parse_tools with the raw response."""
        mock_response = {
            "tools": [
                {"name": "list_commits", "description": "List commits", "inputSchema": {}},
                {"name": "create_issue", "description": "Create issue", "inputSchema": {}},
            ]
        }
        server_id = "github"

        # Compute expected output using canonical parser
        expected_tools = MCPDirectConnector.parse_tools(server_id, mock_response)
        # Stub out subprocess execution — simulate a successful handshake response
        protocol_version = "2024-11-05"
        init_resp_bytes = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": protocol_version,
                        "capabilities": {},
                        "serverInfo": {"name": "github-mcp", "version": "1.0.0"},
                    },
                }
            )
            + "\n"
        ).encode()
        tools_resp_bytes = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": mock_response,
                }
            )
            + "\n"
        ).encode()

        # Fake blocking readline: first call returns init, second tools response.
        # StdioProber now uses subprocess.Popen (blocking) under asyncio.to_thread
        # to avoid a macOS Python 3.12 asyncio.subprocess hang; the test mock
        # mirrors that: a synchronous readline() returning bytes.
        read_call_count = 0

        def fake_readline() -> bytes:
            nonlocal read_call_count
            read_call_count += 1
            if read_call_count == 1:
                return init_resp_bytes
            return tools_resp_bytes

        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.flush = MagicMock()

        mock_stdout = MagicMock()
        mock_stdout.readline = fake_readline

        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.kill = MagicMock()
        mock_process.wait = MagicMock(return_value=0)

        from mcp_discovery.data.transport_spec import StdioTransportSpec

        spec = StdioTransportSpec(
            transport="stdio",
            server_id=server_id,
            command="npx -y @smithery/cli@0.1.0 run @smithery-ai/github",
        )

        with patch(
            "mcp_discovery.data.probers.stdio_prober.subprocess.Popen",
            return_value=mock_process,
        ):
            prober = StdioProber()
            result = await prober.probe(server_id, spec)

        assert result.success is True, f"Probe failed: {result.error_kind} — {result.error_message}"
        assert result.inventory is not None
        # Compare tool names from inventory with expected tools from parse_tools
        raw_names = {t["name"] for t in result.inventory.tools}
        expected_names = {t.tool_name for t in expected_tools}
        assert raw_names == expected_names, (
            f"StdioProber inventory tool names {raw_names} != "
            f"MCPDirectConnector.parse_tools() names {expected_names}"
        )


async def _real_wait_for(coro, timeout=None):
    """Pass-through for asyncio.wait_for in tests (timeouts are irrelevant with mocks)."""
    return await coro


# ---------------------------------------------------------------------------
# probe_servers — multi-server orchestration
# ---------------------------------------------------------------------------


class TestProbeServers:
    async def test_returns_results_for_all_servers(self, tmp_path: Path) -> None:
        specs = {
            "server-a": TransportSpec(transport="script", server_id="server-a"),
            "server-b": TransportSpec(transport="script", server_id="server-b"),
        }
        results = await probe_servers(specs, cache_dir=tmp_path)
        assert set(results.keys()) == {"server-a", "server-b"}
        for r in results.values():
            assert r.error_kind == ProbeErrorKind.TRANSPORT_UNSUPPORTED


# ---------------------------------------------------------------------------
# Secret-scan write-blocking
# ---------------------------------------------------------------------------


class TestCacheSecretScan:
    def test_write_blocked_on_secret_match(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "test.json"
        # Craft a ProbeResult whose serialisation would contain a secret
        spec = _make_spec()
        spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
        result = ProbeResult(
            server_id="test",
            success=False,
            spec_hash=spec_hash,
            error_kind=ProbeErrorKind.AUTH_REQUIRED,
            # error_message contains a fake high-entropy token
            error_message=(
                "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0MTIzNDU2Nzg5MEFCQ0RFRkdISUpLTE1OTw"
            ),
        )
        _write_cache(result, cache_file)
        assert not cache_file.exists(), "Cache file should NOT be written when secret is detected"

    def test_write_succeeds_without_secret(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "clean.json"
        spec = _make_spec()
        spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
        result = ProbeResult(
            server_id="test",
            success=False,
            spec_hash=spec_hash,
            error_kind=ProbeErrorKind.TIMEOUT,
            error_message="Connection timed out",
        )
        _write_cache(result, cache_file)
        assert cache_file.exists(), "Cache file SHOULD be written when no secrets detected"
