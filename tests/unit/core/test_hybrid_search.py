"""Tests for QdrantStore hybrid search — named vectors + RRF fusion."""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from mcp_discovery.embedding.sparse_embedder import SparseVector
from mcp_discovery.models import MCPTool
from mcp_discovery.retrieval.qdrant_store import QdrantStore


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def store(mock_client: AsyncMock) -> QdrantStore:
    return QdrantStore(client=mock_client, collection_name="mcp_tools_hybrid")


@pytest.fixture
def sample_tool() -> MCPTool:
    return MCPTool(
        server_id="github",
        tool_name="search_repositories",
        tool_id="github::search_repositories",
        description="Search GitHub repositories by query",
    )


@pytest.fixture
def dense_vector() -> np.ndarray:
    return np.ones(1536, dtype=np.float32)


@pytest.fixture
def sparse_vector() -> SparseVector:
    return SparseVector(indices=[0, 5, 42], values=[0.9, 0.7, 0.3])


class TestEnsureHybridCollection:
    async def test_ensure_hybrid_collection_uses_named_vectors(
        self, store: QdrantStore, mock_client: AsyncMock
    ):
        """create_collection must use named vectors_config dict + sparse_vectors_config."""
        mock_collections = MagicMock()
        mock_collections.collections = []
        mock_client.get_collections = AsyncMock(return_value=mock_collections)
        mock_client.create_collection = AsyncMock()

        await store.ensure_hybrid_collection(dense_dimension=1536)

        mock_client.create_collection.assert_called_once()
        call_kwargs = mock_client.create_collection.call_args.kwargs
        # vectors_config must be a dict (named vectors), not a VectorParams instance
        assert isinstance(call_kwargs["vectors_config"], dict)
        assert "dense" in call_kwargs["vectors_config"]
        # sparse_vectors_config must be present
        assert "sparse_vectors_config" in call_kwargs
        assert "sparse" in call_kwargs["sparse_vectors_config"]

    async def test_ensure_hybrid_collection_skips_if_exists(
        self, store: QdrantStore, mock_client: AsyncMock
    ):
        """Must not recreate collection if it already exists."""
        existing_collection = MagicMock()
        existing_collection.name = "mcp_tools_hybrid"  # set directly (MagicMock(name=) is special)
        mock_collections = MagicMock()
        mock_collections.collections = [existing_collection]
        mock_client.get_collections = AsyncMock(return_value=mock_collections)
        mock_client.create_collection = AsyncMock()

        await store.ensure_hybrid_collection(dense_dimension=1536)

        mock_client.create_collection.assert_not_called()


class TestUpsertToolsHybrid:
    async def test_upsert_tools_hybrid_includes_both_vectors(
        self,
        store: QdrantStore,
        mock_client: AsyncMock,
        sample_tool: MCPTool,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """Each point's vector must be a dict with 'dense' and 'sparse' keys."""
        mock_client.upsert = AsyncMock()

        await store.upsert_tools_hybrid(
            tools=[sample_tool],
            dense_vectors=[dense_vector],
            sparse_vectors=[sparse_vector],
        )

        mock_client.upsert.assert_called_once()
        call_kwargs = mock_client.upsert.call_args.kwargs
        points = call_kwargs["points"]
        assert len(points) == 1
        vector = points[0].vector
        assert isinstance(vector, dict)
        assert "dense" in vector
        assert "sparse" in vector

    async def test_upsert_tools_hybrid_dense_vector_as_list(
        self,
        store: QdrantStore,
        mock_client: AsyncMock,
        sample_tool: MCPTool,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """Dense vector must be serialized as a plain list."""
        mock_client.upsert = AsyncMock()

        await store.upsert_tools_hybrid(
            tools=[sample_tool],
            dense_vectors=[dense_vector],
            sparse_vectors=[sparse_vector],
        )

        call_kwargs = mock_client.upsert.call_args.kwargs
        points = call_kwargs["points"]
        assert isinstance(points[0].vector["dense"], list)

    async def test_upsert_tools_hybrid_sparse_vector_indices_values(
        self,
        store: QdrantStore,
        mock_client: AsyncMock,
        sample_tool: MCPTool,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """Sparse vector must carry the correct indices and values."""
        mock_client.upsert = AsyncMock()

        await store.upsert_tools_hybrid(
            tools=[sample_tool],
            dense_vectors=[dense_vector],
            sparse_vectors=[sparse_vector],
        )

        call_kwargs = mock_client.upsert.call_args.kwargs
        qdrant_sparse = call_kwargs["points"][0].vector["sparse"]
        assert list(qdrant_sparse.indices) == [0, 5, 42]
        assert list(qdrant_sparse.values) == [0.9, 0.7, 0.3]

    async def test_upsert_tools_hybrid_raises_on_length_mismatch(
        self,
        store: QdrantStore,
        mock_client: AsyncMock,
        sample_tool: MCPTool,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """Must raise ValueError when tools/vectors lengths do not match."""
        with pytest.raises(ValueError):
            await store.upsert_tools_hybrid(
                tools=[sample_tool],
                dense_vectors=[dense_vector, dense_vector],
                sparse_vectors=[sparse_vector],
            )


class TestHybridSearch:
    def _make_hit(self, tool_id: str, server_id: str, score: float) -> MagicMock:
        hit = MagicMock()
        hit.score = score
        hit.payload = {
            "tool_id": tool_id,
            "server_id": server_id,
            "tool_name": tool_id.split("::")[-1],
            "description": "desc",
            "input_schema": None,
        }
        return hit

    def _setup_mock_response(self, mock_client: AsyncMock, hits: list) -> None:
        mock_response = MagicMock()
        mock_response.points = hits
        mock_client.query_points = AsyncMock(return_value=mock_response)

    async def test_hybrid_search_uses_prefetch_and_fusion(
        self,
        store: QdrantStore,
        mock_client: AsyncMock,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """query_points must be called with a prefetch list of 2 items and Fusion.RRF."""
        self._setup_mock_response(mock_client, [])

        await store.hybrid_search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            top_k=5,
            prefetch_limit=20,
        )

        mock_client.query_points.assert_called_once()
        call_kwargs = mock_client.query_points.call_args.kwargs
        prefetch = call_kwargs["prefetch"]
        assert len(prefetch) == 2
        # query must be FusionQuery wrapping Fusion.RRF
        from qdrant_client.models import Fusion, FusionQuery

        assert call_kwargs["query"] == FusionQuery(fusion=Fusion.RRF)

    async def test_hybrid_search_prefetch_uses_correct_vector_names(
        self,
        store: QdrantStore,
        mock_client: AsyncMock,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """First prefetch uses 'dense', second uses 'sparse'."""
        self._setup_mock_response(mock_client, [])

        await store.hybrid_search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            top_k=5,
            prefetch_limit=20,
        )

        call_kwargs = mock_client.query_points.call_args.kwargs
        prefetch = call_kwargs["prefetch"]
        assert prefetch[0].using == "dense"
        assert prefetch[1].using == "sparse"

    async def test_hybrid_search_applies_pool_filter(
        self,
        mock_client: AsyncMock,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """Pool filter must be applied to both prefetch queries when pool_server_ids set."""
        self._setup_mock_response(mock_client, [])
        store_with_pool = QdrantStore(
            client=mock_client,
            collection_name="mcp_tools_hybrid",
            pool_server_ids=["srv1", "srv2"],
        )

        await store_with_pool.hybrid_search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            top_k=5,
            prefetch_limit=20,
        )

        call_kwargs = mock_client.query_points.call_args.kwargs
        prefetch = call_kwargs["prefetch"]
        for pf in prefetch:
            assert pf.filter is not None
            # Must restrict to pool server IDs
            condition = pf.filter.must[0]
            assert condition.key == "server_id"
            assert set(condition.match.any) == {"srv1", "srv2"}

    async def test_hybrid_search_no_filter_without_pool(
        self,
        store: QdrantStore,
        mock_client: AsyncMock,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """Prefetch filter must be None when no pool_server_ids configured."""
        self._setup_mock_response(mock_client, [])

        await store.hybrid_search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            top_k=5,
            prefetch_limit=20,
        )

        call_kwargs = mock_client.query_points.call_args.kwargs
        prefetch = call_kwargs["prefetch"]
        for pf in prefetch:
            assert pf.filter is None

    async def test_hybrid_search_returns_search_results(
        self,
        store: QdrantStore,
        mock_client: AsyncMock,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """Must return SearchResult list with correct rank and score ordering."""
        hits = [
            self._make_hit("github::search_repos", "github", 0.95),
            self._make_hit("gitlab::search_repos", "gitlab", 0.80),
        ]
        self._setup_mock_response(mock_client, hits)

        results = await store.hybrid_search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            top_k=5,
            prefetch_limit=20,
        )

        assert len(results) == 2
        assert results[0].rank == 1
        assert results[0].score == pytest.approx(0.95)
        assert results[0].tool.tool_id == "github::search_repos"
        assert results[1].rank == 2
        assert results[1].score == pytest.approx(0.80)

    async def test_hybrid_search_passes_top_k_as_limit(
        self,
        store: QdrantStore,
        mock_client: AsyncMock,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """limit kwarg must equal top_k."""
        self._setup_mock_response(mock_client, [])

        await store.hybrid_search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            top_k=7,
            prefetch_limit=30,
        )

        call_kwargs = mock_client.query_points.call_args.kwargs
        assert call_kwargs["limit"] == 7

    async def test_hybrid_search_passes_prefetch_limit(
        self,
        store: QdrantStore,
        mock_client: AsyncMock,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
    ):
        """Each prefetch item's limit must equal prefetch_limit."""
        self._setup_mock_response(mock_client, [])

        await store.hybrid_search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            top_k=5,
            prefetch_limit=42,
        )

        call_kwargs = mock_client.query_points.call_args.kwargs
        for pf in call_kwargs["prefetch"]:
            assert pf.limit == 42
