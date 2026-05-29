"""Unit tests for ProbeErrorKind and PROTOCOL_VERSION_MISMATCH (AC19)."""

from __future__ import annotations

import hashlib

from mcp_discovery.models.probe import ProbeErrorKind, ProbeResult, TransportSpec


def _spec_hash(transport: str = "stdio") -> str:
    spec = TransportSpec(transport=transport, server_id="test")
    return hashlib.sha256(spec.model_dump_json().encode()).hexdigest()


class TestProbeErrorKind:
    def test_all_seven_variants_defined(self) -> None:
        expected = {
            "TRANSPORT_UNSUPPORTED",
            "AUTH_REQUIRED",
            "TIMEOUT",
            "HANDSHAKE_FAILED",
            "PROTOCOL_VERSION_MISMATCH",
            "UNREACHABLE",
            "SCHEMA_INVALID",
        }
        actual = {e.value for e in ProbeErrorKind}
        assert actual == expected

    def test_values_are_strings(self) -> None:
        for kind in ProbeErrorKind:
            assert isinstance(kind.value, str)

    def test_enum_is_stable(self) -> None:
        """Value strings match names (used as stable identifiers in reconcile plans)."""
        for kind in ProbeErrorKind:
            assert kind.value == kind.name


class TestProtocolVersionMismatch:
    """AC19: PROTOCOL_VERSION_MISMATCH enum + server_offered_protocol_version field."""

    def test_probe_result_captures_offered_version(self) -> None:
        result = ProbeResult(
            server_id="old-server",
            success=False,
            spec_hash=_spec_hash(),
            error_kind=ProbeErrorKind.PROTOCOL_VERSION_MISMATCH,
            error_message="Server offered outdated protocol version '2023-01-01'",
            server_offered_protocol_version="2023-01-01",
        )
        assert result.error_kind == ProbeErrorKind.PROTOCOL_VERSION_MISMATCH
        assert result.server_offered_protocol_version == "2023-01-01"

    def test_server_offered_version_optional_on_other_errors(self) -> None:
        result = ProbeResult(
            server_id="test",
            success=False,
            spec_hash=_spec_hash(),
            error_kind=ProbeErrorKind.TIMEOUT,
        )
        assert result.server_offered_protocol_version is None

    def test_server_offered_version_on_success(self) -> None:
        from mcp_discovery.models.probe import RawToolInventory

        result = ProbeResult(
            server_id="test",
            success=True,
            spec_hash=_spec_hash(),
            inventory=RawToolInventory(server_id="test", tools=[]),
            server_offered_protocol_version="2024-11-05",
        )
        assert result.server_offered_protocol_version == "2024-11-05"

    async def test_script_prober_returns_transport_unsupported(self) -> None:
        from mcp_discovery.data.probers.script_prober import ScriptProber
        from mcp_discovery.models.probe import TransportSpec

        spec = TransportSpec(transport="script", server_id="test")
        prober = ScriptProber()
        result = await prober.probe("test", spec)
        assert result.success is False
        assert result.error_kind == ProbeErrorKind.TRANSPORT_UNSUPPORTED

    async def test_http_prober_returns_transport_unsupported_for_wrong_spec(self) -> None:
        from mcp_discovery.data.probers.http_prober import HttpProber
        from mcp_discovery.models.probe import TransportSpec

        spec = TransportSpec(transport="stdio", server_id="test")
        prober = HttpProber()
        result = await prober.probe("test", spec)
        assert result.success is False
        assert result.error_kind == ProbeErrorKind.TRANSPORT_UNSUPPORTED

    async def test_stdio_prober_returns_transport_unsupported_for_wrong_spec(self) -> None:
        from mcp_discovery.data.probers.stdio_prober import StdioProber
        from mcp_discovery.models.probe import TransportSpec

        spec = TransportSpec(transport="http", server_id="test")
        prober = StdioProber()
        result = await prober.probe("test", spec)
        assert result.success is False
        assert result.error_kind == ProbeErrorKind.TRANSPORT_UNSUPPORTED
