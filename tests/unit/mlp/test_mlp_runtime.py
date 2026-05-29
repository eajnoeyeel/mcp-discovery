"""Tests for the shared MLP search runtime factory."""

from unittest.mock import MagicMock, call, patch

import pytest

from service.shared.runtime import SearchRuntime, build_search_runtime


@patch.dict("service.shared.runtime.os.environ", {}, clear=True)
@patch("service.shared.runtime._get_sparse_embedder")
@patch("service.shared.runtime.FlatStrategy")
@patch("service.shared.runtime.QdrantStore")
@patch("service.shared.runtime.AsyncQdrantClient")
@patch("service.shared.runtime.OpenAIEmbedder")
@patch("service.shared.runtime.Settings")
@patch("service.shared.runtime.MLPSettings")
def test_build_search_runtime_creates_expected_parts(
    mock_mlp_settings,
    mock_settings,
    mock_embedder,
    mock_qdrant_client,
    mock_store,
    mock_strategy,
    mock_get_sparse,
):
    settings = MagicMock(
        openai_api_key="openai-key",
        embedding_model="text-embedding-3-small",
        embedding_dimension=1536,
        qdrant_url="http://localhost:6333",
        qdrant_api_key="qdrant-key",
        qdrant_collection_name="mcp_tools",
    )
    mlp_settings = MagicMock(server_collection_name="mcp_servers")
    mock_settings.return_value = settings
    mock_mlp_settings.return_value = mlp_settings

    embedder = MagicMock(name="embedder")
    tool_store = MagicMock(name="tool_store")
    server_store = MagicMock(name="server_store")
    sparse_embedder = MagicMock(name="sparse_embedder")
    mock_embedder.return_value = embedder
    mock_qdrant_client.return_value = MagicMock(name="qdrant_client")
    mock_store.side_effect = [tool_store, server_store]
    mock_get_sparse.return_value = sparse_embedder
    strategy = MagicMock(name="strategy")
    mock_strategy.return_value = strategy

    runtime = build_search_runtime()

    assert isinstance(runtime, SearchRuntime)
    assert runtime.settings is settings
    assert runtime.mlp_settings is mlp_settings
    assert runtime.tool_store is tool_store
    assert runtime.server_store is server_store
    assert runtime.strategy is strategy

    mock_settings.assert_called_once_with()
    mock_mlp_settings.assert_called_once_with()
    mock_qdrant_client.assert_called_once_with(
        url="http://localhost:6333",
        api_key="qdrant-key",
        timeout=10,
    )
    mock_embedder.assert_called_once_with(
        api_key="openai-key",
        model="text-embedding-3-small",
        dimension=1536,
    )
    assert mock_store.call_args_list == [
        call(client=mock_qdrant_client.return_value, collection_name="mcp_tools"),
        call(client=mock_qdrant_client.return_value, collection_name="mcp_servers"),
    ]
    mock_strategy.assert_called_once_with(
        embedder=embedder,
        tool_store=tool_store,
        reranker=None,
        sparse_embedder=sparse_embedder,
    )


@patch("service.shared.runtime.OpenAIEmbedder")
@patch("service.shared.runtime.Settings")
@patch("service.shared.runtime.MLPSettings")
def test_build_search_runtime_raises_without_openai_key(
    mock_mlp_settings,
    mock_settings,
    mock_embedder,
):
    settings = MagicMock(
        openai_api_key=None,
        embedding_model="text-embedding-3-small",
        embedding_dimension=1536,
        qdrant_url="http://localhost:6333",
        qdrant_api_key=None,
        qdrant_collection_name="mcp_tools",
    )
    mock_settings.return_value = settings
    mock_mlp_settings.return_value = MagicMock(server_collection_name="mcp_servers")

    with pytest.raises(ValueError, match="OpenAI API key is required"):
        build_search_runtime()

    mock_embedder.assert_not_called()
