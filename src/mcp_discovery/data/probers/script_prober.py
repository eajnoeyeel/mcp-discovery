"""ScriptProber -- fallback prober for arbitrary-script MCP servers (ADR-0018).

Always returns TRANSPORT_UNSUPPORTED. Exists to cleanly handle ScriptTransportSpec
entries without crashing ProberRegistry. A custom runner can subclass ScriptProber
or register a dedicated prober for a specific script type in the future.
"""

from __future__ import annotations

import hashlib

from mcp_discovery.data.probers.base import Prober
from mcp_discovery.models.probe import ProbeErrorKind, ProbeResult, TransportSpec


def _compute_spec_hash(spec: TransportSpec) -> str:
    return hashlib.sha256(spec.model_dump_json().encode()).hexdigest()


class ScriptProber(Prober):
    """Fallback prober that always returns TRANSPORT_UNSUPPORTED.

    Uses stdio_sem (semaphore capacity 2) because script probes are expected
    to be resource-equivalent to stdio probes. Pool_prober selects the
    appropriate semaphore based on transport type.
    """

    def supports(self, spec: TransportSpec) -> bool:
        return spec.transport == "script"

    async def probe(self, server_id: str, spec: TransportSpec) -> ProbeResult:
        return ProbeResult(
            server_id=server_id,
            success=False,
            spec_hash=_compute_spec_hash(spec),
            error_kind=ProbeErrorKind.TRANSPORT_UNSUPPORTED,
            error_message=(
                f"ScriptTransportSpec for '{server_id}' is not supported by automated probing."
                " Manual inspection required."
            ),
        )
