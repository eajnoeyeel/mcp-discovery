"""Record real bridge runs for root-vision validation evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

from service.harness.bridge_loop import summarize_bridge_runs

LOOKUP_TOOL_NAME = "lookup"
DEFAULT_RUN_INPUTS = ["alpha", "beta", "gamma"]
DEFAULT_SOURCE = "local_sam"


def utc_timestamp() -> str:
    """Return an ISO8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


def utc_stamp_for_filename() -> str:
    """Return a compact UTC timestamp for artifact file names."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_output_path(source: str, timestamp: str) -> Path:
    """Build the canonical raw-evidence path for recorded bridge runs."""
    safe_source = source.replace("/", "_").replace(" ", "_")
    return Path("service/harness/fixtures") / f"bridge_runs_recorded_{safe_source}_{timestamp}.json"


def build_search_query(slug: str) -> str:
    """Create an exact-token lexical query for the pending-freshness path."""
    return f"lookup verification records by query {slug}"


def build_register_payload(server_id: str, server_url: str, slug: str) -> dict[str, Any]:
    """Create a deterministic provider registration payload."""
    return {
        "server_id": server_id,
        "name": "Recorded Bridge Verification Server",
        "description": (f"Recorded bridge verification provider for root-vision proof {slug}."),
        "url": server_url,
        "tags": ["verification", "root-vision", "recorded-bridge-runs"],
        "tools": [
            {
                "tool_name": LOOKUP_TOOL_NAME,
                "description": (
                    f"Lookup verification records by query {slug} for recorded bridge proof."
                ),
                "input_schema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
            }
        ],
    }


def parse_bridge_call_text(response_json: dict[str, Any]) -> dict[str, Any]:
    """Extract the inner JSON payload from a bridge JSON-RPC tools/call response."""
    result = response_json.get("result", {})
    content = result.get("content", [])
    if not content:
        return {}
    text = content[0].get("text", "")
    return json.loads(text) if text else {}


def extract_top_tool_id(search_payload: dict[str, Any]) -> str | None:
    """Read the top result tool_id from a find_best_tool payload."""
    results = search_payload.get("results", [])
    if not results:
        return None

    top_result = results[0]
    if isinstance(top_result, dict):
        tool = top_result.get("tool")
        if isinstance(tool, dict):
            return tool.get("tool_id")
        return top_result.get("tool_id")
    return None


def build_recorded_run(
    *,
    query: str,
    server_id: str,
    tool_id: str,
    register_result: dict[str, Any],
    search_payload: dict[str, Any],
    execute_payload: dict[str, Any],
    recorded_at: str,
    session_provenance: dict[str, Any],
    endpoint_provenance: dict[str, Any],
) -> dict[str, Any]:
    """Build a raw bridge-run record compatible with bridge_loop plus proof metadata."""
    recommended_tool_id = extract_top_tool_id(search_payload)
    # query_log_id is emitted by find_best_tool when the bridge logs the query.
    # Recorded here for funnel traceability; may be None if bridge version predates migration 022.
    query_log_id: int | None = search_payload.get("query_log_id")
    return {
        "query": query,
        "server_id": server_id,
        "tool_id": tool_id,
        "register_status": register_result.get("status_code"),
        "search_ok": recommended_tool_id is not None,
        "execute_ok": "error" not in execute_payload,
        "search_latency_ms": float(search_payload.get("latency_ms", 0.0)),
        "execute_latency_ms": float(execute_payload.get("latency_ms", 0.0)),
        "recommended_tool_id": recommended_tool_id,
        "query_log_id": query_log_id,
        "provider_registration_result": register_result,
        "bridge_search_result": search_payload,
        "execute_tool_result": execute_payload,
        "timestamp": recorded_at,
        "session_provenance": session_provenance,
        "endpoint_provenance": endpoint_provenance,
    }


class HostedMCPSampleHandler(BaseHTTPRequestHandler):
    """Minimal hosted HTTP MCP sample server for execute_tool verification."""

    server_version = "HostedMCPSample/1.0"

    def log_message(self, *_args: Any) -> None:  # pragma: no cover - silence stdlib logging
        return

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/mcp":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        payload = json.loads(body or b"{}")
        req_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params", {})

        if method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": LOOKUP_TOOL_NAME,
                            "description": "Lookup verification records by query.",
                            "inputSchema": {
                                "type": "object",
                                "required": ["query"],
                                "properties": {"query": {"type": "string"}},
                            },
                        }
                    ]
                },
            }
        elif method == "tools/call" and params.get("name") == LOOKUP_TOOL_NAME:
            query = params.get("arguments", {}).get("query", "")
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "lookup_query": query,
                                    "server": "hosted_mcp_sample",
                                    "ok": True,
                                }
                            ),
                        }
                    ]
                },
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Method not found"},
            }

        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@contextmanager
def hosted_mcp_sample_server(host: str = "0.0.0.0", port: int = 0):
    """Run a tiny hosted MCP sample server for the duration of the proof run."""
    httpd = ThreadingHTTPServer((host, port), HostedMCPSampleHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


async def create_provider_session(
    *,
    supabase_url: str,
    service_key: str,
    anon_key: str,
    email: str,
    password: str,
) -> dict[str, Any]:
    """Create a disposable provider user and return an access token."""
    supabase_url = supabase_url.rstrip("/")
    admin_headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    auth_headers = {
        "apikey": anon_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        create_response = await client.post(
            f"{supabase_url}/auth/v1/admin/users",
            headers=admin_headers,
            json={"email": email, "password": password, "email_confirm": True},
        )
        if create_response.status_code not in {200, 201}:
            create_response.raise_for_status()

        token_response = await client.post(
            f"{supabase_url}/auth/v1/token?grant_type=password",
            headers=auth_headers,
            json={"email": email, "password": password},
        )
        token_response.raise_for_status()
        token_payload = token_response.json()

    return {
        "email": email,
        "access_token": token_payload["access_token"],
        "user_id": token_payload["user"]["id"],
    }


async def register_provider_server(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    bearer_token: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Register the hosted MCP sample through the MLP provider API."""
    started = time.perf_counter()
    response = await client.post(
        f"{base_url.rstrip('/')}/api/servers",
        headers={
            "x-api-key": api_key,
            "authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    response.raise_for_status()
    return {
        "status_code": response.status_code,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "body": response.json(),
    }


async def mark_tool_indexed_for_local_proof(
    client: httpx.AsyncClient,
    *,
    supabase_url: str,
    service_key: str,
    tool_id: str,
) -> dict[str, Any]:
    """Force the registered tool into indexed status for local bridge proof."""
    started = time.perf_counter()
    response = await client.patch(
        f"{supabase_url.rstrip('/')}/rest/v1/mcp_tools",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        params={"tool_id": f"eq.{tool_id}"},
        json={"index_status": "indexed"},
    )
    response.raise_for_status()
    return {
        "status_code": response.status_code,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "body": response.json(),
    }


async def call_bridge_tool(
    client: httpx.AsyncClient,
    *,
    bridge_url: str,
    api_key: str,
    name: str,
    arguments: dict[str, Any],
    rpc_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Send a JSON-RPC tools/call request to the bridge MCP endpoint."""
    response = await client.post(
        bridge_url,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": rpc_id,
        },
    )
    response.raise_for_status()
    rpc_payload = response.json()
    return rpc_payload, parse_bridge_call_text(rpc_payload)


async def poll_for_expected_tool(
    client: httpx.AsyncClient,
    *,
    bridge_url: str,
    api_key: str,
    query: str,
    expected_tool_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    rpc_id_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Retry bridge search until the expected pending-freshness tool appears on top."""
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    last_rpc: dict[str, Any] = {}
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        attempt += 1
        last_rpc, last_payload = await call_bridge_tool(
            client,
            bridge_url=bridge_url,
            api_key=api_key,
            name="find_best_tool",
            arguments={"query": query, "top_k": 1},
            rpc_id=rpc_id_seed + attempt,
        )
        if extract_top_tool_id(last_payload) == expected_tool_id:
            return last_rpc, last_payload
        await asyncio.sleep(poll_interval_seconds)
    raise TimeoutError(
        f"Expected tool '{expected_tool_id}' did not become the top bridge result "
        f"for query '{query}'. Last payload: {last_payload or last_rpc}"
    )


async def record_bridge_runs(
    *,
    base_url: str,
    api_key: str,
    supabase_url: str,
    supabase_service_key: str,
    supabase_anon_key: str,
    output_path: Path,
    source: str,
    run_inputs: list[str],
    timestamp_token: str | None = None,
    search_timeout_seconds: float = 12.0,
    poll_interval_seconds: float = 1.0,
) -> dict[str, Any]:
    """Register a hosted MCP sample, then record repeated bridge search+execute runs."""
    timestamp = timestamp_token or utc_stamp_for_filename()
    slug = f"recorded-bridge-{timestamp.lower()}"
    email = f"{slug}@example.com"
    password = f"RalPh-{timestamp}-proof!"
    session_id = f"{source}-{timestamp}"

    provider = await create_provider_session(
        supabase_url=supabase_url,
        service_key=supabase_service_key,
        anon_key=supabase_anon_key,
        email=email,
        password=password,
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        with hosted_mcp_sample_server() as sample_server:
            sample_port = sample_server.server_address[1]
            hosted_sample_url = f"http://host.docker.internal:{sample_port}"
            local_sample_url = f"http://127.0.0.1:{sample_port}/mcp"
            bridge_url = f"{base_url.rstrip('/')}/mcp"
            register_url = f"{base_url.rstrip('/')}/api/servers"
            server_id = f"recorded-bridge-{timestamp.lower()}"
            tool_id = f"{server_id}::{LOOKUP_TOOL_NAME}"

            register_payload = build_register_payload(server_id, hosted_sample_url, slug)
            register_result = await register_provider_server(
                client,
                base_url=base_url,
                api_key=api_key,
                bearer_token=provider["access_token"],
                payload=register_payload,
            )
            index_override = await mark_tool_indexed_for_local_proof(
                client,
                supabase_url=supabase_url,
                service_key=supabase_service_key,
                tool_id=tool_id,
            )
            register_result["post_register_index_override"] = index_override

            search_query = build_search_query(slug)
            runs: list[dict[str, Any]] = []
            endpoint_provenance = {
                "register_url": register_url,
                "bridge_mcp_url": bridge_url,
                "hosted_mcp_url": f"{hosted_sample_url}/mcp",
                "host_bind_mcp_url": local_sample_url,
            }
            session_provenance = {
                "session_id": session_id,
                "provider_email": provider["email"],
                "provider_user_id": provider["user_id"],
                "server_id": server_id,
                "tool_id": tool_id,
                "source": source,
            }

            for index, input_value in enumerate(run_inputs, start=1):
                _, search_payload = await poll_for_expected_tool(
                    client,
                    bridge_url=bridge_url,
                    api_key=api_key,
                    query=search_query,
                    expected_tool_id=tool_id,
                    timeout_seconds=search_timeout_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                    rpc_id_seed=index * 100,
                )
                _, execute_payload = await call_bridge_tool(
                    client,
                    bridge_url=bridge_url,
                    api_key=api_key,
                    name="execute_tool",
                    arguments={"tool_id": tool_id, "params": {"query": input_value}},
                    rpc_id=1000 + index,
                )
                runs.append(
                    build_recorded_run(
                        query=search_query,
                        server_id=server_id,
                        tool_id=tool_id,
                        register_result=register_result,
                        search_payload=search_payload,
                        execute_payload=execute_payload,
                        recorded_at=utc_timestamp(),
                        session_provenance={**session_provenance, "run_index": index},
                        endpoint_provenance=endpoint_provenance,
                    )
                )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(runs, indent=2))
    return {
        "artifact_path": str(output_path),
        "summary": summarize_bridge_runs(runs),
        "runs": runs,
    }


async def _async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Record real bridge search+execute runs for root-vision proof."
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("MLP_BASE_URL", "http://127.0.0.1:3000")
    )
    parser.add_argument("--api-key", default=os.environ.get("MLP_API_KEY", ""))
    parser.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL", ""))
    parser.add_argument(
        "--supabase-service-key",
        default=os.environ.get("SUPABASE_SERVICE_KEY", ""),
    )
    parser.add_argument("--supabase-anon-key", default=os.environ.get("SUPABASE_ANON_KEY", ""))
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--search-timeout-seconds", type=float, default=12.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument(
        "--output",
        help="Optional output path. Defaults to the canonical recorded-bridge-runs fixture path.",
    )
    parser.add_argument(
        "--run-input",
        action="append",
        dest="run_inputs",
        help="Repeated execute input values. Defaults to alpha/beta/gamma.",
    )
    args = parser.parse_args()

    required = {
        "api_key": args.api_key,
        "supabase_url": args.supabase_url,
        "supabase_service_key": args.supabase_service_key,
        "supabase_anon_key": args.supabase_anon_key,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit(f"Missing required inputs: {', '.join(missing)}")

    timestamp_token = utc_stamp_for_filename()
    output_path = (
        Path(args.output) if args.output else build_output_path(args.source, timestamp_token)
    )
    payload = await record_bridge_runs(
        base_url=args.base_url,
        api_key=args.api_key,
        supabase_url=args.supabase_url,
        supabase_service_key=args.supabase_service_key,
        supabase_anon_key=args.supabase_anon_key,
        output_path=output_path,
        source=args.source,
        run_inputs=args.run_inputs or DEFAULT_RUN_INPUTS,
        timestamp_token=timestamp_token,
        search_timeout_seconds=args.search_timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    print(json.dumps(payload, indent=2))


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
