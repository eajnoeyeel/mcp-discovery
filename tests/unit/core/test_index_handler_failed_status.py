"""Test that Index Lambda marks tools as 'failed' when indexing fails."""

import json
import sys
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

_INDEX_PATCHES = [
    "mcp_discovery.config.Settings",
    "mcp_discovery.embedding.openai_embedder.OpenAIEmbedder",
    "mcp_discovery.embedding.fastembed_sparse.FastEmbedSparseEmbedder",
    "qdrant_client.AsyncQdrantClient",
    "mcp_discovery.retrieval.qdrant_store.QdrantStore",
]


@pytest.fixture(autouse=True)
def _teardown():
    yield
    sys.modules.pop("service.lambdas.index.handler", None)


def _mock_settings(**overrides) -> MagicMock:
    s = MagicMock()
    defaults = dict(
        openai_api_key="fake",
        embedding_model="text-embedding-3-small",
        embedding_dimension=1536,
        qdrant_url="http://localhost:6333",
        qdrant_api_key=None,
        qdrant_collection_name="mcp_tools",
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


async def test_index_failure_sets_failed_status():
    """When indexing fails, tools should be marked as 'failed', not left pending."""
    ms = _mock_settings()
    patches = [
        patch(p, return_value=ms) if p == "mcp_discovery.config.Settings" else patch(p)
        for p in _INDEX_PATCHES
    ]
    for p in patches:
        p.start()

    index_service = MagicMock()
    index_service.split_rows_by_content_hash = AsyncMock(
        return_value=(
            [{"tool_id": "s1::t1", "server_id": "s1", "tool_name": "t1", "description": "test"}],
            [],
        )
    )
    index_service.index_rows = AsyncMock(side_effect=RuntimeError("Embedding API down"))

    with patch("service.services.index_service.IndexService", return_value=index_service):
        sys.modules.pop("service.lambdas.index.handler", None)
        import service.lambdas.index.handler as mod

    try:
        with (
            patch.object(mod, "_fetch_pending_tools", new_callable=AsyncMock) as mock_fetch,
            patch.object(
                mod, "_claim_pending_tools", new_callable=AsyncMock, return_value=1
            ) as mock_claim,
            patch.object(mod, "_update_tool_status", new_callable=AsyncMock) as mock_update,
            patch.object(mod, "_finalize_server_status", new_callable=AsyncMock),
        ):
            mock_fetch.return_value = [
                {
                    "tool_id": "s1::t1",
                    "server_id": "s1",
                    "tool_name": "t1",
                    "description": "test",
                }
            ]

            result = await mod._async_handler({"detail": {"server_id": "s1"}}, None)

            assert result["statusCode"] == 500
            # Verify: optimistic claim called first, then "failed" on error
            mock_claim.assert_called_once_with(["s1::t1"])
            mock_update.assert_called_once_with(["s1::t1"], "failed")
    finally:
        for p in patches:
            p.stop()


async def test_fetch_pending_tools_failure_returns_500():
    """When _fetch_pending_tools raises, handler returns 500 without UnboundLocalError."""
    ms = _mock_settings()
    patches = [
        patch(p, return_value=ms) if p == "mcp_discovery.config.Settings" else patch(p)
        for p in _INDEX_PATCHES
    ]
    for p in patches:
        p.start()

    index_service = MagicMock()
    index_service.split_rows_by_content_hash = AsyncMock(return_value=([], []))
    index_service.index_rows = AsyncMock()

    with patch("service.services.index_service.IndexService", return_value=index_service):
        sys.modules.pop("service.lambdas.index.handler", None)
        import service.lambdas.index.handler as mod

    try:
        with (
            patch.object(
                mod,
                "_fetch_pending_tools",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Supabase unreachable"),
            ) as mock_fetch,
            patch.object(mod, "_update_tool_status", new_callable=AsyncMock) as mock_update,
            patch.object(mod, "_finalize_server_status", new_callable=AsyncMock),
        ):
            result = await mod._async_handler({"detail": {"server_id": "s1"}}, None)

            assert result["statusCode"] == 500
            # rows was empty list before the exception, so _mark_failed_safe
            # short-circuits without calling _update_tool_status
            mock_fetch.assert_called_once_with("s1")
            mock_update.assert_not_called()
    finally:
        for p in patches:
            p.stop()


async def test_index_claims_batch_with_indexing_status():
    """Index handler should atomically claim tools before embedding."""
    ms = _mock_settings()
    patches = [
        patch(p, return_value=ms) if p == "mcp_discovery.config.Settings" else patch(p)
        for p in _INDEX_PATCHES
    ]
    for p in patches:
        p.start()

    index_service = MagicMock()
    index_service.split_rows_by_content_hash = AsyncMock(
        return_value=(
            [{"tool_id": "s1::t1", "server_id": "s1", "tool_name": "t1", "description": "test"}],
            [],
        )
    )
    index_service.index_rows = AsyncMock(return_value=1)

    with patch("service.services.index_service.IndexService", return_value=index_service):
        sys.modules.pop("service.lambdas.index.handler", None)
        import service.lambdas.index.handler as mod

    try:
        with (
            patch.object(mod, "_fetch_pending_tools", new_callable=AsyncMock) as mock_fetch,
            patch.object(
                mod, "_claim_pending_tools", new_callable=AsyncMock, return_value=1
            ) as mock_claim,
            patch.object(mod, "_update_tool_status", new_callable=AsyncMock) as mock_update,
            patch.object(mod, "_finalize_server_status", new_callable=AsyncMock),
            patch.object(mod, "index_service", index_service),
        ):
            mock_fetch.return_value = [
                {
                    "tool_id": "s1::t1",
                    "server_id": "s1",
                    "tool_name": "t1",
                    "description": "test",
                }
            ]

            result = await mod._async_handler({"detail": {"server_id": "s1"}}, None)

            assert result["statusCode"] == 200
            # Verify: optimistic claim precedes final "indexed" status update
            mock_claim.assert_called_once_with(["s1::t1"])
            mock_update.assert_called_once_with(["s1::t1"], "indexed", indexed_at=ANY)
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_claim_returns_zero_when_already_claimed():
    """When another Lambda already claimed the tools, skip gracefully."""
    ms = _mock_settings()
    patches = [
        patch(p, return_value=ms) if p == "mcp_discovery.config.Settings" else patch(p)
        for p in _INDEX_PATCHES
    ]
    for p in patches:
        p.start()

    index_service = MagicMock()
    index_service.split_rows_by_content_hash = AsyncMock(return_value=([], []))
    index_service.index_rows = AsyncMock(return_value=0)

    with patch("service.services.index_service.IndexService", return_value=index_service):
        sys.modules.pop("service.lambdas.index.handler", None)
        import service.lambdas.index.handler as mod

    try:
        with (
            patch.object(mod, "_fetch_pending_tools", new_callable=AsyncMock) as mock_fetch,
            patch.object(
                mod, "_claim_pending_tools", new_callable=AsyncMock, return_value=0
            ) as mock_claim,
            patch.object(mod, "_update_tool_status", new_callable=AsyncMock) as mock_update,
        ):
            mock_fetch.return_value = [
                {
                    "tool_id": "s1::t1",
                    "server_id": "s1",
                    "tool_name": "t1",
                    "description": "test",
                }
            ]

            result = await mod._async_handler({"detail": {"server_id": "s1"}}, None)

            # Handler returns 200 with indexed_count=0, skipped_count=0, and already_claimed=True
            assert result["statusCode"] == 200
            body = json.loads(result["body"])
            assert body == {
                "server_id": "s1",
                "indexed_count": 0,
                "skipped_count": 0,
                "already_claimed": True,
            }
            # Claim was attempted but returned 0 — no further split/index/status work
            mock_claim.assert_called_once_with(["s1::t1"])
            index_service.split_rows_by_content_hash.assert_not_awaited()
            mock_update.assert_not_called()
            # index_service.index_rows must NOT be called
            index_service.index_rows.assert_not_called()
    finally:
        for p in patches:
            p.stop()
