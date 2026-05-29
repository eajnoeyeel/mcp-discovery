"""Tests for hosted runtime schema verification helpers."""

from __future__ import annotations

import json

import httpx
import pytest

from service.scripts.verify_runtime_schema import (
    fetch_mcp_auth_requirements_uniqueness_state,
    fetch_runtime_schema_state,
    summarize_mcp_auth_requirements_uniqueness_checks,
    summarize_schema_checks,
)


def _request_json(request: httpx.Request) -> dict:
    return json.loads(request.content.decode())


class TestSummarizeSchemaChecks:
    def test_marks_missing_checks_in_required_order(self) -> None:
        summary = summarize_schema_checks(
            {
                "mcp_servers.transport_type": True,
                "mcp_servers.requires_gateway": False,
                "mcp_oauth_sessions": False,
                "mcp_gateway_routes": True,
                "query_logs.recommended_tool_id": True,
                "execution_logs.query_log_id": True,
                "tool_operational_stats": True,
                "oauth_provider_registry.bootstrap_metadata": True,
                "oauth_provider_bootstrap_drafts": True,
                "oauth_state_nonces": True,
                "mcp_auth_requirements": True,
                "user_provider_connections": False,
                "pending_executions.resume_contract": False,
            }
        )

        assert summary["ready"] is False
        assert summary["missing"] == [
            "mcp_servers.requires_gateway",
            "mcp_oauth_sessions",
            "user_provider_connections",
            "pending_executions.resume_contract",
        ]
        assert summary["present"] == [
            "execution_logs.query_log_id",
            "mcp_auth_requirements",
            "mcp_gateway_routes",
            "mcp_servers.transport_type",
            "oauth_provider_bootstrap_drafts",
            "oauth_provider_registry.bootstrap_metadata",
            "oauth_state_nonces",
            "query_logs.recommended_tool_id",
            "tool_operational_stats",
        ]

    def test_is_ready_when_all_required_checks_present(self) -> None:
        summary = summarize_schema_checks(
            {
                "mcp_servers.transport_type": True,
                "mcp_servers.requires_gateway": True,
                "mcp_oauth_sessions": True,
                "mcp_gateway_routes": True,
                "query_logs.recommended_tool_id": True,
                "execution_logs.query_log_id": True,
                "tool_operational_stats": True,
                "oauth_provider_registry.bootstrap_metadata": True,
                "oauth_provider_bootstrap_drafts": True,
                "oauth_state_nonces": True,
                "mcp_auth_requirements": True,
                "user_provider_connections": True,
                "pending_executions.resume_contract": True,
            }
        )

        assert summary == {
            "ready": True,
            "missing": [],
            "present": [
                "execution_logs.query_log_id",
                "mcp_auth_requirements",
                "mcp_gateway_routes",
                "mcp_oauth_sessions",
                "mcp_servers.requires_gateway",
                "mcp_servers.transport_type",
                "oauth_provider_bootstrap_drafts",
                "oauth_provider_registry.bootstrap_metadata",
                "oauth_state_nonces",
                "pending_executions.resume_contract",
                "query_logs.recommended_tool_id",
                "tool_operational_stats",
                "user_provider_connections",
            ],
        }


class TestSummarizeMcpAuthRequirementsUniquenessChecks:
    def test_marks_missing_uniqueness_checks_in_required_order(self) -> None:
        summary = summarize_mcp_auth_requirements_uniqueness_checks(
            {
                "mcp_auth_requirements.server_default_unique": False,
                "mcp_auth_requirements.tool_id_unique": True,
            }
        )

        assert summary == {
            "ready": False,
            "missing": ["mcp_auth_requirements.server_default_unique"],
            "present": ["mcp_auth_requirements.tool_id_unique"],
        }

    def test_is_ready_when_all_uniqueness_checks_pass(self) -> None:
        summary = summarize_mcp_auth_requirements_uniqueness_checks(
            {
                "mcp_auth_requirements.server_default_unique": True,
                "mcp_auth_requirements.tool_id_unique": True,
            }
        )

        assert summary == {
            "ready": True,
            "missing": [],
            "present": [
                "mcp_auth_requirements.server_default_unique",
                "mcp_auth_requirements.tool_id_unique",
            ],
        }


class TestFetchRuntimeSchemaState:
    @pytest.mark.asyncio
    async def test_uses_read_only_get_requests_for_each_required_check(self) -> None:
        seen: list[tuple[str, str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, str(request.url), request.headers["Authorization"]))
            assert request.headers["apikey"] == "service-key"
            return httpx.Response(200, json=[])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            checks = await fetch_runtime_schema_state(
                "https://db.example.co",
                "service-key",
                client=client,
            )

        assert checks == {
            "mcp_servers.transport_type": True,
            "mcp_servers.requires_gateway": True,
            "mcp_oauth_sessions": True,
            "mcp_gateway_routes": True,
            "query_logs.recommended_tool_id": True,
            "execution_logs.query_log_id": True,
            "tool_operational_stats": True,
            "oauth_provider_registry.bootstrap_metadata": True,
            "oauth_provider_bootstrap_drafts": True,
            "oauth_state_nonces": True,
            "mcp_auth_requirements": True,
            "user_provider_connections": True,
            "pending_executions.resume_contract": True,
        }
        assert seen == [
            (
                "GET",
                "https://db.example.co/rest/v1/mcp_servers?select=transport_type&limit=1",
                "Bearer service-key",
            ),
            (
                "GET",
                "https://db.example.co/rest/v1/mcp_servers?select=requires_gateway&limit=1",
                "Bearer service-key",
            ),
            (
                "GET",
                "https://db.example.co/rest/v1/mcp_oauth_sessions?select=server_id&limit=1",
                "Bearer service-key",
            ),
            (
                "GET",
                "https://db.example.co/rest/v1/mcp_gateway_routes?select=server_id&limit=1",
                "Bearer service-key",
            ),
            (
                "GET",
                "https://db.example.co/rest/v1/query_logs?select=recommended_tool_id&limit=1",
                "Bearer service-key",
            ),
            (
                "GET",
                "https://db.example.co/rest/v1/execution_logs?select=query_log_id&limit=1",
                "Bearer service-key",
            ),
            (
                "GET",
                "https://db.example.co/rest/v1/tool_operational_stats?select=tool_id&limit=1",
                "Bearer service-key",
            ),
            (
                "GET",
                "https://db.example.co/rest/v1/oauth_provider_registry?"
                "select=provider_key%2Cissuer%2Cmetadata_url%2Cregistration_endpoint%2C"
                "client_secret_ref%2Ctoken_endpoint_auth_method%2Cbootstrap_status&limit=1",
                "Bearer service-key",
            ),
            (
                "GET",
                (
                    "https://db.example.co/rest/v1/oauth_provider_bootstrap_drafts?"
                    "select=id%2Cowner_user_id%2Cprovider_key%2Cstatus%2Cidempotency_key&limit=1"
                ),
                "Bearer service-key",
            ),
            (
                "GET",
                (
                    "https://db.example.co/rest/v1/oauth_state_nonces?"
                    "select=nonce_hash%2Ccode_verifier%2Crequired_scopes%2Cuser_id%2Cprovider_key%2Cexpires_at%2Cconsumed_at&limit=1"
                ),
                "Bearer service-key",
            ),
            (
                "GET",
                (
                    "https://db.example.co/rest/v1/mcp_auth_requirements?"
                    "select=provider_key%2Ctool_id%2Crequired_scopes%2Cscope_mode&limit=1"
                ),
                "Bearer service-key",
            ),
            (
                "GET",
                (
                    "https://db.example.co/rest/v1/user_provider_connections?"
                    "select=id%2Cuser_id%2Cprovider_key%2Cstatus&limit=1"
                ),
                "Bearer service-key",
            ),
            (
                "GET",
                (
                    "https://db.example.co/rest/v1/pending_executions?"
                    "select=id%2Cretry_token%2Cstatus%2Cconnection_id%2Cresult_json%2Cerror_message"
                    "&limit=1"
                ),
                "Bearer service-key",
            ),
        ]

    @pytest.mark.asyncio
    async def test_marks_missing_columns_or_tables_without_live_network(self) -> None:
        statuses = {
            "/rest/v1/mcp_servers?select=transport_type&limit=1": 200,
            "/rest/v1/mcp_servers?select=requires_gateway&limit=1": 400,
            "/rest/v1/mcp_oauth_sessions?select=server_id&limit=1": 404,
            "/rest/v1/mcp_gateway_routes?select=server_id&limit=1": 200,
            "/rest/v1/query_logs?select=recommended_tool_id&limit=1": 200,
            "/rest/v1/execution_logs?select=query_log_id&limit=1": 400,
            "/rest/v1/tool_operational_stats?select=tool_id&limit=1": 200,
            "/rest/v1/oauth_provider_registry?"
            "select=provider_key%2Cissuer%2Cmetadata_url%2Cregistration_endpoint%2C"
            "client_secret_ref%2Ctoken_endpoint_auth_method%2Cbootstrap_status&limit=1": 404,
            (
                "/rest/v1/oauth_provider_bootstrap_drafts?"
                "select=id%2Cowner_user_id%2Cprovider_key%2Cstatus%2Cidempotency_key&limit=1"
            ): 404,
            (
                "/rest/v1/oauth_state_nonces?"
                "select=nonce_hash%2Ccode_verifier%2Crequired_scopes%2Cuser_id%2Cprovider_key%2Cexpires_at%2Cconsumed_at&limit=1"
            ): 404,
            (
                "/rest/v1/mcp_auth_requirements?"
                "select=provider_key%2Ctool_id%2Crequired_scopes%2Cscope_mode&limit=1"
            ): 404,
            (
                "/rest/v1/user_provider_connections?"
                "select=id%2Cuser_id%2Cprovider_key%2Cstatus&limit=1"
            ): 404,
            (
                "/rest/v1/pending_executions?"
                "select=id%2Cretry_token%2Cstatus%2Cconnection_id%2Cresult_json%2Cerror_message"
                "&limit=1"
            ): 400,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            status_code = statuses[request.url.raw_path.decode()]
            return httpx.Response(status_code, json={"message": "mocked"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            checks = await fetch_runtime_schema_state(
                "https://db.example.co",
                "service-key",
                client=client,
            )

        assert checks == {
            "mcp_servers.transport_type": True,
            "mcp_servers.requires_gateway": False,
            "mcp_oauth_sessions": False,
            "mcp_gateway_routes": True,
            "query_logs.recommended_tool_id": True,
            "execution_logs.query_log_id": False,
            "tool_operational_stats": True,
            "oauth_provider_registry.bootstrap_metadata": False,
            "oauth_provider_bootstrap_drafts": False,
            "oauth_state_nonces": False,
            "mcp_auth_requirements": False,
            "user_provider_connections": False,
            "pending_executions.resume_contract": False,
        }


class TestFetchMcpAuthRequirementsUniquenessState:
    @pytest.mark.asyncio
    async def test_detects_unique_indexes_with_temporary_rows(self) -> None:
        seen: list[tuple[str, str]] = []
        auth_insert_counts: dict[tuple[str, str | None], int] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path))
            assert request.headers["apikey"] == "service-key"
            assert request.headers["Authorization"] == "Bearer service-key"

            if request.method == "GET" and request.url.path.endswith("/oauth_provider_registry"):
                return httpx.Response(200, json=[{"provider_key": "apify"}])
            if request.method == "POST" and request.url.path.endswith("/mcp_servers"):
                assert request.headers["Prefer"] == "return=representation"
                return httpx.Response(201, json=[_request_json(request)])
            if request.method == "POST" and request.url.path.endswith("/mcp_tools"):
                assert request.headers["Prefer"] == "return=representation"
                return httpx.Response(201, json=[_request_json(request)])
            if request.method == "POST" and request.url.path.endswith("/mcp_auth_requirements"):
                assert request.headers["Prefer"] == "return=representation"
                body = _request_json(request)
                key = (body["server_id"], body.get("tool_id"))
                auth_insert_counts[key] = auth_insert_counts.get(key, 0) + 1
                if auth_insert_counts[key] > 1:
                    return httpx.Response(409, json={"code": "23505"})
                return httpx.Response(201, json=[body])
            if request.method == "DELETE":
                assert request.headers["Prefer"] == "return=minimal"
                return httpx.Response(204)
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            checks = await fetch_mcp_auth_requirements_uniqueness_state(
                "https://db.example.co",
                "service-key",
                client=client,
            )

        assert checks == {
            "mcp_auth_requirements.server_default_unique": True,
            "mcp_auth_requirements.tool_id_unique": True,
        }
        assert seen[0] == ("GET", "/rest/v1/oauth_provider_registry")
        assert ("DELETE", "/rest/v1/mcp_auth_requirements") in seen
        assert ("DELETE", "/rest/v1/mcp_tools") in seen
        assert ("DELETE", "/rest/v1/mcp_servers") in seen

    @pytest.mark.asyncio
    async def test_detects_missing_server_default_uniqueness_and_cleans_up_probe_rows(self) -> None:
        auth_requirement_posts = 0
        cleanup_calls: list[tuple[str, str, str | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal auth_requirement_posts
            assert request.headers["apikey"] == "service-key"
            assert request.headers["Authorization"] == "Bearer service-key"

            if request.method == "GET" and request.url.path == "/rest/v1/oauth_provider_registry":
                assert request.url.query == b"select=provider_key&enabled=eq.true&limit=1"
                return httpx.Response(200, json=[{"provider_key": "github"}])

            if request.method == "POST" and request.url.path == "/rest/v1/mcp_servers":
                assert request.headers["Prefer"] == "return=representation"
                payload = _request_json(request)
                assert payload["name"] == "runtime schema uniqueness probe"
                return httpx.Response(201, json=[{"id": "server-row"}])

            if request.method == "POST" and request.url.path == "/rest/v1/mcp_tools":
                assert request.headers["Prefer"] == "return=representation"
                payload = _request_json(request)
                assert payload["tool_name"] == "probe_tool"
                return httpx.Response(201, json=[{"id": "tool-row"}])

            if request.method == "POST" and request.url.path == "/rest/v1/mcp_auth_requirements":
                auth_requirement_posts += 1
                assert request.headers["Prefer"] == "return=representation"
                if auth_requirement_posts in {1, 2, 3}:
                    return httpx.Response(
                        201, json=[{"id": f"requirement-{auth_requirement_posts}"}]
                    )
                if auth_requirement_posts == 4:
                    return httpx.Response(400, json={"code": "23505"})

                raise AssertionError(f"unexpected auth insert count: {auth_requirement_posts}")

            if request.method == "DELETE":
                cleanup_calls.append(
                    (
                        request.url.path,
                        request.headers["Prefer"],
                        request.url.params.get("server_id"),
                    )
                )
                return httpx.Response(204)

            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            checks = await fetch_mcp_auth_requirements_uniqueness_state(
                "https://db.example.co",
                "service-key",
                client=client,
            )

        assert checks == {
            "mcp_auth_requirements.server_default_unique": False,
            "mcp_auth_requirements.tool_id_unique": True,
        }
        assert len(cleanup_calls) == 3
        assert cleanup_calls[0][2]
        assert cleanup_calls == [
            ("/rest/v1/mcp_auth_requirements", "return=minimal", cleanup_calls[0][2]),
            ("/rest/v1/mcp_tools", "return=minimal", cleanup_calls[0][2]),
            ("/rest/v1/mcp_servers", "return=minimal", cleanup_calls[0][2]),
        ]

    @pytest.mark.asyncio
    async def test_reports_false_when_duplicate_rows_are_accepted(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path.endswith("/oauth_provider_registry"):
                return httpx.Response(200, json=[{"provider_key": "apify"}])
            if request.method == "POST":
                return httpx.Response(201, json=[_request_json(request)])
            if request.method == "DELETE":
                return httpx.Response(204)
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            checks = await fetch_mcp_auth_requirements_uniqueness_state(
                "https://db.example.co",
                "service-key",
                client=client,
            )

        assert checks == {
            "mcp_auth_requirements.server_default_unique": False,
            "mcp_auth_requirements.tool_id_unique": False,
        }

    @pytest.mark.asyncio
    async def test_reports_false_when_no_enabled_provider_exists(self) -> None:
        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path))
            if request.method == "GET" and request.url.path.endswith("/oauth_provider_registry"):
                return httpx.Response(200, json=[])
            if request.method == "DELETE":
                assert request.headers["Prefer"] == "return=minimal"
                return httpx.Response(204)
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            checks = await fetch_mcp_auth_requirements_uniqueness_state(
                "https://db.example.co",
                "service-key",
                client=client,
            )

        assert checks == {
            "mcp_auth_requirements.server_default_unique": False,
            "mcp_auth_requirements.tool_id_unique": False,
        }
        assert ("POST", "/rest/v1/mcp_servers") not in seen
