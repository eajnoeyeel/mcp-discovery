"""Abstract base class for MCP transport probers (ADR-0018)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mcp_discovery.models.probe import ProbeResult, TransportSpec


class Prober(ABC):
    """ABC for MCP transport probers.

    Each concrete prober handles one transport type (stdio / http / script).
    ProberRegistry selects the appropriate prober via supports().
    """

    @abstractmethod
    async def probe(self, server_id: str, spec: TransportSpec) -> ProbeResult:
        """Execute a probe against the given server using the given transport spec.

        Implementations MUST:
        - Only call `initialize` + `tools/list` — never `tools/call`.
        - Respect the spec's timeout configuration.
        - Never log secrets (API keys, tokens). Log the offending key NAME only.
        - Set ProbeResult.server_offered_protocol_version from the initialize response.
        - Compute spec_hash as sha256(spec.model_dump_json()).
        """
        ...

    @abstractmethod
    def supports(self, spec: TransportSpec) -> bool:
        """Return True if this prober can handle the given transport spec."""
        ...
