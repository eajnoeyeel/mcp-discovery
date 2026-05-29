"""HttpProber -- probes HTTP/SSE MCP endpoints (ADR-0018).

Sends JSON-RPC initialize + tools/list over HTTP POST.
Tool parsing delegates to MCPDirectConnector.parse_tools() (AC26).
"""

from __future__ import annotations

import hashlib

import httpx
from loguru import logger

from mcp_discovery.data.mcp_connector import MCPDirectConnector
from mcp_discovery.data.probers.base import Prober
from mcp_discovery.models.probe import (
    ProbeErrorKind,
    ProbeResult,
    RawToolInventory,
    TransportSpec,
)

_JSONRPC_VERSION = "2.0"
_INITIALIZE_METHOD = "initialize"
_TOOLS_LIST_METHOD = "tools/list"
_DEFAULT_TIMEOUT_SECONDS = 30.0


def _compute_spec_hash(spec: TransportSpec) -> str:
    return hashlib.sha256(spec.model_dump_json().encode()).hexdigest()


class HttpProber(Prober):
    """Probes HTTP/SSE MCP endpoints via JSON-RPC over HTTPS.

    Calls initialize then tools/list against the endpoint URL.
    Tool objects are passed verbatim to MCPDirectConnector.parse_tools() (AC26).
    """

    def supports(self, spec: TransportSpec) -> bool:
        return spec.transport == "http"

    async def probe(self, server_id: str, spec: TransportSpec) -> ProbeResult:
        from mcp_discovery.data.transport_spec import HttpTransportSpec

        spec_hash = _compute_spec_hash(spec)

        if not isinstance(spec, HttpTransportSpec):
            return ProbeResult(
                server_id=server_id,
                success=False,
                spec_hash=spec_hash,
                error_kind=ProbeErrorKind.TRANSPORT_UNSUPPORTED,
                error_message=f"HttpProber received non-http spec: {spec.transport}",
            )

        timeout = spec.timeout_seconds
        headers = dict(spec.headers)

        try:
            async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
                protocol_version, tools_result = await self._handshake(client, spec.url, server_id)
        except httpx.TimeoutException:
            logger.warning(f"HttpProber: timeout probing '{server_id}'")
            return ProbeResult(
                server_id=server_id,
                success=False,
                spec_hash=spec_hash,
                error_kind=ProbeErrorKind.TIMEOUT,
                error_message=f"HTTP request timed out after {timeout}s",
            )
        except httpx.ConnectError as exc:
            logger.warning(f"HttpProber: connection error probing '{server_id}': {exc}")
            return ProbeResult(
                server_id=server_id,
                success=False,
                spec_hash=spec_hash,
                error_kind=ProbeErrorKind.UNREACHABLE,
                error_message=str(exc),
            )
        except _AuthRequiredError:
            return ProbeResult(
                server_id=server_id,
                success=False,
                spec_hash=spec_hash,
                error_kind=ProbeErrorKind.AUTH_REQUIRED,
                error_message="HTTP endpoint returned 401/403",
            )
        except _ProtocolMismatchError as exc:
            return ProbeResult(
                server_id=server_id,
                success=False,
                spec_hash=spec_hash,
                error_kind=ProbeErrorKind.PROTOCOL_VERSION_MISMATCH,
                error_message=str(exc),
                server_offered_protocol_version=exc.offered_version,
            )
        except Exception as exc:
            logger.warning(
                f"HttpProber: unexpected error probing '{server_id}': {type(exc).__name__}"
            )
            return ProbeResult(
                server_id=server_id,
                success=False,
                spec_hash=spec_hash,
                error_kind=ProbeErrorKind.HANDSHAKE_FAILED,
                error_message=str(exc),
            )

        # Delegate to canonical parser (AC26)
        MCPDirectConnector.parse_tools(server_id, tools_result)

        inventory = RawToolInventory(
            server_id=server_id,
            tools=tools_result.get("tools", []),
            protocol_version=protocol_version,
        )
        return ProbeResult(
            server_id=server_id,
            success=True,
            spec_hash=spec_hash,
            inventory=inventory,
            server_offered_protocol_version=protocol_version,
        )

    async def _handshake(
        self, client: httpx.AsyncClient, url: str, server_id: str
    ) -> tuple[str | None, dict]:
        init_req = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": 1,
            "method": _INITIALIZE_METHOD,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-discovery-prober", "version": "0.1.0"},
            },
        }
        init_resp = await client.post(url, json=init_req)

        if init_resp.status_code in (401, 403):
            raise _AuthRequiredError(f"Server '{server_id}' returned HTTP {init_resp.status_code}")
        init_resp.raise_for_status()

        init_data = init_resp.json()
        _check_json_rpc_error(init_data, server_id)

        protocol_version: str | None = None
        init_result = init_data.get("result", {})
        if isinstance(init_result, dict):
            protocol_version = init_result.get("protocolVersion")
            if protocol_version and protocol_version < "2024-11-05":
                raise _ProtocolMismatchError(
                    f"Server '{server_id}' offered old protocol version '{protocol_version}'",
                    offered_version=protocol_version,
                )

        tools_req = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": 2,
            "method": _TOOLS_LIST_METHOD,
            "params": {},
        }
        tools_resp = await client.post(url, json=tools_req)

        if tools_resp.status_code in (401, 403):
            raise _AuthRequiredError(
                f"Server '{server_id}' returned HTTP {tools_resp.status_code} on tools/list"
            )
        tools_resp.raise_for_status()

        tools_data = tools_resp.json()
        _check_json_rpc_error(tools_data, server_id)

        tools_result = tools_data.get("result", {})
        if not isinstance(tools_result, dict):
            raise RuntimeError(
                f"Server '{server_id}' returned non-dict tools/list result: {type(tools_result)}"
            )
        return protocol_version, tools_result


def _check_json_rpc_error(response: dict, server_id: str) -> None:
    error = response.get("error")
    if not error:
        return
    code = error.get("code", 0)
    if code in (-32000, 401, 403):
        raise _AuthRequiredError(f"Server '{server_id}' returned auth error (code {code})")
    raise RuntimeError(f"Server '{server_id}' returned JSON-RPC error: {error}")


class _AuthRequiredError(Exception):
    pass


class _ProtocolMismatchError(Exception):
    def __init__(self, message: str, *, offered_version: str | None = None) -> None:
        super().__init__(message)
        self.offered_version = offered_version
