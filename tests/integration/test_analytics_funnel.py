"""Integration tests for migration 022 analytics funnel schema + views.

Tests:
- T4: execution_logs.query_log_id FK (cascade, violation, null, valid)
- plan AC: tool_exposure_facts view (unnest alternatives WITH ORDINALITY)
- tool_conversion_funnel view (LEFT JOIN, funnel_outcome classification)

All DB-dependent tests are skipped when SUPABASE_URL is not set.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Set ANALYTICS_FUNNEL_TESTS=true to run these tests.
# They require migration 022 to be applied (recommended_tool_id column +
# query_log_id FK + tool_exposure_facts / tool_conversion_funnel views).
# Without the migration the tests will fail with PGRST204 schema errors.
_analytics_enabled = os.getenv("ANALYTICS_FUNNEL_TESTS", "").lower() == "true"

pytestmark = pytest.mark.skipif(
    not SUPABASE_URL or not _analytics_enabled,
    reason=(
        "Skipping analytics funnel integration tests. "
        "Requires SUPABASE_URL + ANALYTICS_FUNNEL_TESTS=true + migration 022 applied."
    ),
)


def _headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _rest(path: str) -> str:
    return f"{SUPABASE_URL.rstrip('/')}/rest/v1/{path}"


def _rpc(fn: str) -> str:
    return f"{SUPABASE_URL.rstrip('/')}/rest/v1/rpc/{fn}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_query_log(
    client: httpx.AsyncClient,
    *,
    recommended_tool_id: str | None = "srv::t1",
    alternatives: list[dict] | None = None,
    query: str | None = None,
) -> int:
    """Insert a query_logs row and return its id."""
    payload: dict = {
        "query": query or f"test-query-{uuid.uuid4()}",
        "recommended_tool_id": recommended_tool_id,
        "alternatives": alternatives,
    }
    resp = await client.post(_rest("query_logs"), headers=_headers(), json=payload)
    resp.raise_for_status()
    rows = resp.json()
    assert len(rows) == 1, f"Expected 1 row, got: {rows}"
    return rows[0]["id"]


async def _insert_execution_log(
    client: httpx.AsyncClient,
    *,
    tool_id: str = "srv::t1",
    server_id: str = "srv",
    query_log_id: int | None = None,
) -> int | None:
    """Insert an execution_logs row and return its id (or None on failure)."""
    payload: dict = {
        "tool_id": tool_id,
        "server_id": server_id,
        "success": True,
        "latency_ms": 42.0,
    }
    if query_log_id is not None:
        payload["query_log_id"] = query_log_id

    resp = await client.post(_rest("execution_logs"), headers=_headers(), json=payload)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    return rows[0]["id"]


async def _delete_query_log(client: httpx.AsyncClient, row_id: int) -> None:
    resp = await client.delete(
        _rest("query_logs"),
        headers=_headers(),
        params={"id": f"eq.{row_id}"},
    )
    resp.raise_for_status()


async def _delete_execution_log(client: httpx.AsyncClient, row_id: int) -> None:
    resp = await client.delete(
        _rest("execution_logs"),
        headers=_headers(),
        params={"id": f"eq.{row_id}"},
    )
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# FK cascade tests (T4)
# ---------------------------------------------------------------------------


class TestExecutionLogQueryLogIdFK:
    async def test_fk_on_delete_set_null(self) -> None:
        """Deleting query_logs row sets execution_logs.query_log_id = NULL."""
        exec_id: int | None = None
        async with httpx.AsyncClient(timeout=15.0) as client:
            ql_id = await _insert_query_log(client)
            exec_id = await _insert_execution_log(client, query_log_id=ql_id)

            # Delete the parent query_logs row
            await _delete_query_log(client, ql_id)

            # Verify query_log_id is now NULL on the execution_logs row
            resp = await client.get(
                _rest("execution_logs"),
                headers=_headers(),
                params={"id": f"eq.{exec_id}", "select": "id,query_log_id"},
            )
            resp.raise_for_status()
            rows = resp.json()
            assert len(rows) == 1
            assert rows[0]["query_log_id"] is None

            # Cleanup
            await _delete_execution_log(client, exec_id)

    async def test_fk_violation_with_nonexistent_query_log_id(self) -> None:
        """Inserting execution_logs with a non-existent query_log_id must fail."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            payload = {
                "tool_id": "srv::t1",
                "server_id": "srv",
                "success": True,
                "latency_ms": 10.0,
                "query_log_id": 99999999,
            }
            resp = await client.post(
                _rest("execution_logs"),
                headers={**_headers(), "Prefer": "return=representation"},
                json=payload,
            )
            # FK violation: expect 409 (Supabase REST) or 4xx
            assert resp.status_code in {409, 400, 422, 500}, (
                f"Expected FK violation status, got {resp.status_code}: {resp.text}"
            )

    async def test_null_query_log_id_allowed(self) -> None:
        """NULL query_log_id must be accepted (represents direct execution)."""
        exec_id: int | None = None
        async with httpx.AsyncClient(timeout=15.0) as client:
            exec_id = await _insert_execution_log(client, query_log_id=None)
            assert exec_id is not None

            # Verify stored as NULL
            resp = await client.get(
                _rest("execution_logs"),
                headers=_headers(),
                params={"id": f"eq.{exec_id}", "select": "id,query_log_id"},
            )
            resp.raise_for_status()
            rows = resp.json()
            assert len(rows) == 1
            assert rows[0]["query_log_id"] is None

            await _delete_execution_log(client, exec_id)

    async def test_valid_query_log_id_accepted(self) -> None:
        """A valid query_log_id referencing an existing query_logs row must succeed."""
        exec_id: int | None = None
        ql_id: int | None = None
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                ql_id = await _insert_query_log(client)
                exec_id = await _insert_execution_log(client, query_log_id=ql_id)
                assert exec_id is not None

                resp = await client.get(
                    _rest("execution_logs"),
                    headers=_headers(),
                    params={"id": f"eq.{exec_id}", "select": "id,query_log_id"},
                )
                resp.raise_for_status()
                rows = resp.json()
                assert len(rows) == 1
                assert rows[0]["query_log_id"] == ql_id
            finally:
                if exec_id is not None:
                    await _delete_execution_log(client, exec_id)
                if ql_id is not None:
                    await _delete_query_log(client, ql_id)


# ---------------------------------------------------------------------------
# tool_exposure_facts view (plan AC)
# ---------------------------------------------------------------------------


class TestToolExposureFactsView:
    async def test_unnest_alternatives_returns_one_row_per_tool(self) -> None:
        """tool_exposure_facts must return 5 rows for 5 items in alternatives."""
        ql_id: int | None = None
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                recommended = "srv::t1"
                alternatives = [
                    {"tool_id": f"srv::t{i}", "score": 0.9 - i * 0.05} for i in range(5)
                ]
                ql_id = await _insert_query_log(
                    client,
                    recommended_tool_id=recommended,
                    alternatives=alternatives,
                )

                resp = await client.get(
                    _rest("tool_exposure_facts"),
                    headers=_headers(),
                    params={
                        "query_log_id": f"eq.{ql_id}",
                        "select": (
                            "query_log_id,exposed_tool_id,"
                            "exposed_rank,is_top_ranked,recommended_tool_id"
                        ),
                        "order": "exposed_rank.asc",
                    },
                )
                resp.raise_for_status()
                rows = resp.json()

                assert len(rows) == 5, f"Expected 5 exposure rows, got {len(rows)}: {rows}"

                # Verify ranks are 0..4
                ranks = [r["exposed_rank"] for r in rows]
                assert ranks == list(range(5)), f"Unexpected ranks: {ranks}"

                # is_top_ranked should be True only for srv::t0 (index 0 = recommended)
                for row in rows:
                    if row["exposed_tool_id"] == recommended:
                        assert row["is_top_ranked"] is True
                    else:
                        assert row["is_top_ranked"] is False
            finally:
                if ql_id is not None:
                    await _delete_query_log(client, ql_id)


# ---------------------------------------------------------------------------
# tool_conversion_funnel view
# ---------------------------------------------------------------------------


class TestToolConversionFunnelView:
    async def test_converted_and_diverged_outcomes(self) -> None:
        """Executions linked via query_log_id show correct funnel_outcome."""
        ql_id: int | None = None
        exec_converted_id: int | None = None
        exec_diverged_id: int | None = None

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                ql_id = await _insert_query_log(client, recommended_tool_id="srv::t1")

                # Execution matching recommended_tool_id → converted
                exec_converted_id = await _insert_execution_log(
                    client, tool_id="srv::t1", server_id="srv", query_log_id=ql_id
                )
                # Execution with different tool → diverged
                exec_diverged_id = await _insert_execution_log(
                    client, tool_id="srv::t2", server_id="srv", query_log_id=ql_id
                )

                resp = await client.get(
                    _rest("tool_conversion_funnel"),
                    headers=_headers(),
                    params={
                        "query_log_id": f"eq.{ql_id}",
                        "select": "query_log_id,executed_tool_id,funnel_outcome",
                    },
                )
                resp.raise_for_status()
                rows = resp.json()

                assert len(rows) == 2, f"Expected 2 funnel rows, got {len(rows)}: {rows}"

                outcomes_by_tool = {r["executed_tool_id"]: r["funnel_outcome"] for r in rows}
                assert outcomes_by_tool.get("srv::t1") == "converted"
                assert outcomes_by_tool.get("srv::t2") == "diverged"
            finally:
                if exec_converted_id is not None:
                    await _delete_execution_log(client, exec_converted_id)
                if exec_diverged_id is not None:
                    await _delete_execution_log(client, exec_diverged_id)
                if ql_id is not None:
                    await _delete_query_log(client, ql_id)

    async def test_no_execution_outcome_for_unexecuted_query_log(self) -> None:
        """A query_logs row with no linked execution shows funnel_outcome = no_execution."""
        ql_id: int | None = None

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                ql_id = await _insert_query_log(client, recommended_tool_id="srv::t1")

                resp = await client.get(
                    _rest("tool_conversion_funnel"),
                    headers=_headers(),
                    params={
                        "query_log_id": f"eq.{ql_id}",
                        "select": "query_log_id,executed_tool_id,funnel_outcome",
                    },
                )
                resp.raise_for_status()
                rows = resp.json()

                assert len(rows) == 1, f"Expected 1 funnel row, got {len(rows)}: {rows}"
                assert rows[0]["funnel_outcome"] == "no_execution"
                assert rows[0]["executed_tool_id"] is None
            finally:
                if ql_id is not None:
                    await _delete_query_log(client, ql_id)
