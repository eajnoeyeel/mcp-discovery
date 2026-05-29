from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from service.adapters.supabase_client import SupabaseClient
from service.shared.provider_ownership import (
    OWNER_TAG_PREFIX,
    add_owner_tag,
    extract_owner_user_id,
    is_missing_column_error_payload,
    is_missing_owner_column_error_payload,
    strip_internal_owner_tags,
)


def _owner_column_missing_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://supabase.test/rest/v1/mcp_servers")
    response = httpx.Response(
        400,
        request=request,
        json={
            "code": "PGRST204",
            "message": (
                "Could not find the 'owner_user_id' column of 'mcp_servers' in the schema cache"
            ),
        },
    )
    return httpx.HTTPStatusError("schema cache miss", request=request, response=response)


def test_owner_tag_helpers_round_trip():
    tags = add_owner_tag(["search", "docs"], "user-123")

    assert f"{OWNER_TAG_PREFIX}user-123" in tags
    assert strip_internal_owner_tags(tags) == ["search", "docs"]
    assert extract_owner_user_id({"tags": tags}) == "user-123"


def test_missing_owner_column_payload_detection():
    assert is_missing_owner_column_error_payload(
        {
            "code": "42703",
            "message": "column mcp_servers.owner_user_id does not exist",
        }
    )
    assert not is_missing_owner_column_error_payload({"code": "23505", "message": "duplicate key"})


def test_is_missing_column_error_discriminates_columns():
    """Regression: 42703 error for column X must NOT match detection for column Y.

    The previous implementation returned True for any 42703 error regardless of
    which column was named in the error message. That defect caused
    ``_is_missing_owner_column_error`` to report True when any other column was
    the actual missing column, which cascaded through ``fetch_server`` fallback
    and silently dropped ``owner_user_id`` from the SELECT list — breaking
    dashboard tool-detail queries for servers with ``provider_id=NULL``.
    """
    payload = {
        "code": "42703",
        "message": "column mcp_servers.provider_id does not exist",
    }
    assert is_missing_column_error_payload(payload, "provider_id") is True
    assert is_missing_column_error_payload(payload, "owner_user_id") is False


def test_tool_metadata_column_detection_preserved():
    """Tool-metadata override columns must still be detected post-fix.

    The fix narrows only the 42703 ``or code == '42703'`` catch-all. PGRST204
    and column-specific 42703 messages must continue to match correctly, so
    ``_is_missing_tool_metadata_column_error`` keeps its ability to recognise
    stale tool-metadata columns.
    """
    pg_42703 = {
        "code": "42703",
        "message": "column mcp_tools.upstream_description does not exist",
    }
    assert is_missing_column_error_payload(pg_42703, "upstream_description") is True
    assert is_missing_column_error_payload(pg_42703, "usage_examples") is False

    pgrst_204 = {
        "code": "PGRST204",
        "message": (
            "Could not find the 'upstream_description' column of 'mcp_tools' in the schema cache"
        ),
    }
    assert is_missing_column_error_payload(pgrst_204, "upstream_description") is True
    assert is_missing_column_error_payload(pgrst_204, "usage_examples") is False


@pytest.mark.asyncio
async def test_fetch_owned_servers_falls_back_to_internal_owner_tag():
    client = SupabaseClient(url="https://supabase.test", service_key="service-key")
    client._get = AsyncMock(
        side_effect=[
            _owner_column_missing_error(),
            [
                {
                    "server_id": "owned-srv",
                    "name": "Owned",
                    "description": None,
                    "url": "https://owned.test",
                    "tags": add_owner_tag(["search"], "user-123"),
                    "index_status": "pending",
                    "created_at": "2026-04-06T00:00:00Z",
                    "updated_at": "2026-04-06T00:00:00Z",
                },
                {
                    "server_id": "other-srv",
                    "name": "Other",
                    "description": None,
                    "url": "https://other.test",
                    "tags": add_owner_tag(["weather"], "user-999"),
                    "index_status": "pending",
                    "created_at": "2026-04-06T00:00:00Z",
                    "updated_at": "2026-04-06T00:00:00Z",
                },
            ],
        ]
    )

    rows = await client.fetch_owned_servers("user-123")

    assert [row["server_id"] for row in rows] == ["owned-srv"]
    assert rows[0]["owner_user_id"] == "user-123"
    assert rows[0]["tags"] == ["search"]
