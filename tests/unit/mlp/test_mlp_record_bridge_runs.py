"""Tests for recorded bridge-run evidence helpers."""

from __future__ import annotations

import json

import httpx

from service.harness.record_bridge_runs import (
    LOOKUP_TOOL_NAME,
    build_output_path,
    build_recorded_run,
    build_register_payload,
    build_search_query,
    extract_top_tool_id,
    hosted_mcp_sample_server,
    parse_bridge_call_text,
)


def test_build_output_path_uses_canonical_recorded_prefix():
    path = build_output_path("local_sam", "20260408T131500Z")
    expected = "service/harness/fixtures/bridge_runs_recorded_local_sam_20260408T131500Z.json"
    assert str(path) == expected


def test_build_register_payload_embeds_slug_in_searchable_description():
    payload = build_register_payload(
        "recorded-bridge-test",
        "http://host.docker.internal:8765",
        "recorded-bridge-proof",
    )

    assert payload["server_id"] == "recorded-bridge-test"
    assert payload["url"] == "http://host.docker.internal:8765"
    assert payload["tools"][0]["tool_name"] == LOOKUP_TOOL_NAME
    assert "recorded-bridge-proof" in payload["tools"][0]["description"]


def test_build_search_query_uses_exact_tokens():
    assert build_search_query("proof-slug") == "lookup verification records by query proof-slug"


def test_parse_bridge_call_text_and_extract_top_tool_id():
    rpc_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "results": [
                                {
                                    "tool": {
                                        "tool_id": "recorded-bridge::lookup",
                                    }
                                }
                            ],
                            "latency_ms": 123.4,
                        }
                    ),
                }
            ]
        },
    }

    payload = parse_bridge_call_text(rpc_payload)
    assert payload["latency_ms"] == 123.4
    assert extract_top_tool_id(payload) == "recorded-bridge::lookup"


def test_build_recorded_run_includes_bridge_contract_fields():
    register_result = {"status_code": 201, "body": {"message": "ok"}}
    search_payload = {
        "results": [{"tool": {"tool_id": "srv::lookup"}}],
        "latency_ms": 45.0,
    }
    execute_payload = {"tool_id": "srv::lookup", "result": {"ok": True}, "latency_ms": 12.0}

    run = build_recorded_run(
        query="lookup verification records by query proof",
        server_id="srv",
        tool_id="srv::lookup",
        register_result=register_result,
        search_payload=search_payload,
        execute_payload=execute_payload,
        recorded_at="2026-04-08T13:15:00+00:00",
        session_provenance={"session_id": "test"},
        endpoint_provenance={"bridge_mcp_url": "http://127.0.0.1:3000/mcp"},
    )

    assert run["register_status"] == 201
    assert run["recommended_tool_id"] == "srv::lookup"
    assert run["search_ok"] is True
    assert run["execute_ok"] is True
    assert run["tool_id"] == "srv::lookup"
    assert "query_log_id" in run


def test_hosted_mcp_sample_server_handles_lookup_tool():
    with hosted_mcp_sample_server(host="127.0.0.1", port=0) as server:
        port = server.server_address[1]
        response = httpx.post(
            f"http://127.0.0.1:{port}/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": LOOKUP_TOOL_NAME, "arguments": {"query": "alpha"}},
                "id": 1,
            },
            timeout=5.0,
        )

    response.raise_for_status()
    body = response.json()
    content = json.loads(body["result"]["content"][0]["text"])
    assert content == {"lookup_query": "alpha", "server": "hosted_mcp_sample", "ok": True}
