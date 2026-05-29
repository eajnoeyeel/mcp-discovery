"""Unit tests for ProberRegistry (Track A)."""

from __future__ import annotations

from mcp_discovery.data.pool_prober import ProberRegistry
from mcp_discovery.data.probers.http_prober import HttpProber
from mcp_discovery.data.probers.script_prober import ScriptProber
from mcp_discovery.data.probers.stdio_prober import StdioProber
from mcp_discovery.models.probe import TransportSpec


def _spec(transport: str) -> TransportSpec:
    return TransportSpec(transport=transport, server_id="test")


class TestProberRegistryFull:
    """Comprehensive registry tests."""

    def test_default_registry_has_three_probers(self) -> None:
        from mcp_discovery.data.pool_prober import _default_registry

        reg = _default_registry()
        assert sorted(reg.transports) == ["http", "script", "stdio"]

    def test_stdio_prober_supports_stdio(self) -> None:
        prober = StdioProber()
        assert prober.supports(_spec("stdio")) is True
        assert prober.supports(_spec("http")) is False
        assert prober.supports(_spec("script")) is False

    def test_http_prober_supports_http(self) -> None:
        prober = HttpProber()
        assert prober.supports(_spec("http")) is True
        assert prober.supports(_spec("stdio")) is False

    def test_script_prober_supports_script(self) -> None:
        prober = ScriptProber()
        assert prober.supports(_spec("script")) is True
        assert prober.supports(_spec("stdio")) is False

    def test_registry_override(self) -> None:
        reg = ProberRegistry()
        original = StdioProber()
        replacement = StdioProber()
        reg.register("stdio", original)
        reg.register("stdio", replacement)
        assert reg.get("stdio") is replacement

    def test_get_for_spec_linear_scan_fallback(self) -> None:
        """get_for_spec must find prober even when transport key is not a string match."""
        reg = ProberRegistry()
        script_prober = ScriptProber()
        # Register under non-standard key; supports() is still the authority
        reg.register("__fallback", script_prober)
        spec = _spec("script")
        found = reg.get_for_spec(spec)
        assert found is script_prober
