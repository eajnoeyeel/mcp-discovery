"""StdioProber -- probes npx/stdio-based MCP servers (ADR-0018).

Security invariants (Architect FC4):
  - subprocess launched with a tightly restricted env: PATH, HOME
    (inherited from the caller so npm/npx can reuse its package cache),
    TMPDIR (prober-private), plus any resolved env vars declared in the
    TransportSpec. No ambient env leakage.
  - Hard timeout (wall-clock) on the overall probe via asyncio.wait_for
    and per-step readline via _readline_with_deadline.
  - No shell=True; arguments are never interpolated.
  - Only initialize + tools/list are called. tools/call is NEVER issued.
  - Uses blocking subprocess.Popen under asyncio.to_thread — pure
  `asyncio.create_subprocess_exec` with PIPE stdin/stdout hangs on
  macOS Python 3.12 for Node.js MCP servers.

Tool parsing delegates to MCPDirectConnector.parse_tools() (AC26).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import time

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
_DEFAULT_TIMEOUT_SECONDS = 120.0


def _compute_spec_hash(spec: TransportSpec) -> str:
    return hashlib.sha256(spec.model_dump_json().encode()).hexdigest()


class StdioProber(Prober):
    """Probes npx/stdio MCP servers by spawning a sandboxed subprocess.

    Calls initialize then tools/list. Tool objects are passed verbatim to
    MCPDirectConnector.parse_tools() for authoritative MCPTool construction (AC26).
    """

    def supports(self, spec: TransportSpec) -> bool:
        return spec.transport == "stdio"

    async def probe(self, server_id: str, spec: TransportSpec) -> ProbeResult:
        spec_hash = _compute_spec_hash(spec)
        try:
            return await asyncio.wait_for(
                self._run_probe(server_id, spec, spec_hash),
                timeout=_DEFAULT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(f"StdioProber: timeout probing '{server_id}'")
            return ProbeResult(
                server_id=server_id,
                success=False,
                spec_hash=spec_hash,
                error_kind=ProbeErrorKind.TIMEOUT,
                error_message=f"Probe timed out after {_DEFAULT_TIMEOUT_SECONDS}s",
            )
        except Exception as exc:
            logger.warning(
                f"StdioProber: unexpected error probing '{server_id}': {type(exc).__name__}"
            )
            return ProbeResult(
                server_id=server_id,
                success=False,
                spec_hash=spec_hash,
                error_kind=ProbeErrorKind.HANDSHAKE_FAILED,
                error_message=str(exc),
            )

    async def _run_probe(self, server_id: str, spec: TransportSpec, spec_hash: str) -> ProbeResult:
        # asyncio.create_subprocess_exec with PIPE stdin/stdout has
        # reproducible hangs on macOS Python 3.12 when the child is
        # a Node.js MCP server — pipes never drain. We therefore run
        # the probe in a worker thread using blocking subprocess.Popen,
        # which works correctly on the same machine in ~1s.
        return await asyncio.to_thread(self._run_probe_blocking, server_id, spec, spec_hash)

    def _run_probe_blocking(
        self, server_id: str, spec: TransportSpec, spec_hash: str
    ) -> ProbeResult:
        from mcp_discovery.data.transport_spec import StdioTransportSpec

        if not isinstance(spec, StdioTransportSpec):
            return ProbeResult(
                server_id=server_id,
                success=False,
                spec_hash=spec_hash,
                error_kind=ProbeErrorKind.TRANSPORT_UNSUPPORTED,
                error_message=f"StdioProber received non-stdio spec: {spec.transport}",
            )

        command_parts = spec.command.split()

        resolved_env: dict[str, str] = {}
        for var_name, env_key in spec.env.items():
            val = os.environ.get(env_key)
            if val is None:
                logger.warning(
                    f"StdioProber: env var '{env_key}' for server '{server_id}'"
                    " not set -- probe may fail with AUTH_REQUIRED"
                )
            else:
                resolved_env[var_name] = val

        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox_env = {
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "HOME": os.environ.get("HOME", tmpdir),
                "TMPDIR": tmpdir,
                **resolved_env,
            }
            try:
                process = subprocess.Popen(  # noqa: S603 — args are not shell-interpolated
                    command_parts,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=sandbox_env,
                    bufsize=0,
                )
            except FileNotFoundError:
                return ProbeResult(
                    server_id=server_id,
                    success=False,
                    spec_hash=spec_hash,
                    error_kind=ProbeErrorKind.UNREACHABLE,
                    error_message=f"Command not found: {command_parts[0]}",
                )

            try:
                protocol_version, tools_result = self._handshake_blocking(process, server_id)
            except _AuthRequiredError:
                process.kill()
                process.wait()
                return ProbeResult(
                    server_id=server_id,
                    success=False,
                    spec_hash=spec_hash,
                    error_kind=ProbeErrorKind.AUTH_REQUIRED,
                    error_message="Server requires authentication",
                )
            except _ProtocolMismatchError as exc:
                process.kill()
                process.wait()
                return ProbeResult(
                    server_id=server_id,
                    success=False,
                    spec_hash=spec_hash,
                    error_kind=ProbeErrorKind.PROTOCOL_VERSION_MISMATCH,
                    error_message=str(exc),
                    server_offered_protocol_version=exc.offered_version,
                )
            except Exception:
                process.kill()
                process.wait()
                raise

            process.kill()
            process.wait()

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

    def _handshake_blocking(
        self, process: subprocess.Popen, server_id: str
    ) -> tuple[str | None, dict]:
        assert process.stdin is not None
        assert process.stdout is not None

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
        process.stdin.write((json.dumps(init_req) + "\n").encode())
        process.stdin.flush()

        init_line = _readline_with_deadline(process.stdout, deadline_seconds=60.0)
        if not init_line:
            raise RuntimeError(f"Server '{server_id}' closed stdout after initialize")

        init_resp = json.loads(init_line.decode())
        _check_error(init_resp, server_id)

        protocol_version: str | None = None
        init_result = init_resp.get("result", {})
        if isinstance(init_result, dict):
            protocol_version = init_result.get("protocolVersion")
            offered = protocol_version
            if offered and offered < "2024-11-05":
                raise _ProtocolMismatchError(
                    f"Server '{server_id}' offered old protocol version '{offered}'",
                    offered_version=offered,
                )

        notif = {"jsonrpc": _JSONRPC_VERSION, "method": "notifications/initialized", "params": {}}
        process.stdin.write((json.dumps(notif) + "\n").encode())
        process.stdin.flush()

        tools_req = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": 2,
            "method": _TOOLS_LIST_METHOD,
            "params": {},
        }
        process.stdin.write((json.dumps(tools_req) + "\n").encode())
        process.stdin.flush()

        tools_line = _readline_with_deadline(process.stdout, deadline_seconds=30.0)
        if not tools_line:
            raise RuntimeError(f"Server '{server_id}' closed stdout after tools/list")

        tools_resp = json.loads(tools_line.decode())
        _check_error(tools_resp, server_id)

        tools_result = tools_resp.get("result", {})
        if not isinstance(tools_result, dict):
            raise RuntimeError(
                f"Server '{server_id}' returned non-dict tools/list result: {type(tools_result)}"
            )
        return protocol_version, tools_result


def _readline_with_deadline(stream, deadline_seconds: float) -> bytes:
    """Blocking readline with a wall-clock deadline.

    subprocess.Popen.stdout.readline() has no timeout. We poll in a
    tight loop with a very small sleep so long-running probes can't
    hang forever.
    """
    deadline = time.time() + deadline_seconds
    while True:
        line = stream.readline()
        if line:
            return line
        if time.time() >= deadline:
            raise asyncio.TimeoutError(f"readline exceeded deadline of {deadline_seconds}s")
        time.sleep(0.05)


def _check_error(response: dict, server_id: str) -> None:
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
