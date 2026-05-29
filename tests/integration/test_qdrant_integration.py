"""Integration tests for QdrantStore — runs against real Qdrant Docker (localhost:6333)."""

import os

import numpy as np
import pytest
from qdrant_client import AsyncQdrantClient

from mcp_discovery.models import MCPTool, SearchResult
from mcp_discovery.retrieval.qdrant_store import QdrantStore

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

# Skip all tests if Qdrant is not reachable
pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_QDRANT", "false").lower() == "true",
    reason="SKIP_QDRANT=true",
)

TEST_COLLECTION = "test_mcp_tools_integration"
VECTOR_DIM = 128  # small dimension for fast tests


@pytest.fixture
async def qdrant_client():
    """Create a real AsyncQdrantClient and clean up test collection after."""
    client = AsyncQdrantClient(url=QDRANT_URL)
    yield client
    # Cleanup: delete test collection
    try:
        await client.delete_collection(collection_name=TEST_COLLECTION)
    except Exception:
        pass
    await client.close()


@pytest.fixture
async def store(qdrant_client):
    """Create a QdrantStore with real client."""
    return QdrantStore(client=qdrant_client, collection_name=TEST_COLLECTION)


@pytest.fixture
def sample_tools() -> list[MCPTool]:
    return [
        MCPTool(
            server_id="@smithery-ai/github",
            tool_name="search_issues",
            tool_id="@smithery-ai/github::search_issues",
            description="Search GitHub issues by query",
        ),
        MCPTool(
            server_id="@smithery-ai/github",
            tool_name="create_pr",
            tool_id="@smithery-ai/github::create_pr",
            description="Create a pull request on GitHub",
        ),
        MCPTool(
            server_id="@anthropic/fetch-mcp",
            tool_name="fetch_url",
            tool_id="@anthropic/fetch-mcp::fetch_url",
            description="Fetch content from a URL",
        ),
    ]


def random_vectors(n: int, dim: int = VECTOR_DIM) -> list[np.ndarray]:
    """Generate deterministic random vectors for reproducible tests."""
    rng = np.random.default_rng(seed=42)
    return [rng.standard_normal(dim).astype(np.float32) for _ in range(n)]


class TestEnsureCollection:
    async def test_creates_new_collection(self, store, qdrant_client):
        await store.ensure_collection(dimension=VECTOR_DIM)

        collections = await qdrant_client.get_collections()
        names = [c.name for c in collections.collections]
        assert TEST_COLLECTION in names

    async def test_idempotent_when_already_exists(self, store):
        await store.ensure_collection(dimension=VECTOR_DIM)
        # Calling again should not raise
        await store.ensure_collection(dimension=VECTOR_DIM)


class TestUpsertTools:
    async def test_upserts_tools_and_retrieves(self, store, qdrant_client, sample_tools):
        await store.ensure_collection(dimension=VECTOR_DIM)
        vectors = random_vectors(len(sample_tools))

        await store.upsert_tools(sample_tools, vectors)

        # Verify points exist
        info = await qdrant_client.get_collection(TEST_COLLECTION)
        assert info.points_count == len(sample_tools)

    async def test_upsert_is_idempotent(self, store, qdrant_client, sample_tools):
        await store.ensure_collection(dimension=VECTOR_DIM)
        vectors = random_vectors(len(sample_tools))

        await store.upsert_tools(sample_tools, vectors)
        await store.upsert_tools(sample_tools, vectors)  # same tools again

        info = await qdrant_client.get_collection(TEST_COLLECTION)
        assert info.points_count == len(sample_tools)  # no duplicates


class TestSearch:
    async def test_returns_search_results(self, store, sample_tools):
        await store.ensure_collection(dimension=VECTOR_DIM)
        vectors = random_vectors(len(sample_tools))
        await store.upsert_tools(sample_tools, vectors)

        query = vectors[0]  # search with first tool's vector
        results = await store.search(query, top_k=3)

        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(r.score is not None for r in results)
        # First result should have rank=1
        assert results[0].rank == 1

    async def test_top_k_limits_results(self, store, sample_tools):
        await store.ensure_collection(dimension=VECTOR_DIM)
        vectors = random_vectors(len(sample_tools))
        await store.upsert_tools(sample_tools, vectors)

        results = await store.search(vectors[0], top_k=1)
        assert len(results) == 1

    async def test_server_id_filter(self, store, sample_tools):
        await store.ensure_collection(dimension=VECTOR_DIM)
        vectors = random_vectors(len(sample_tools))
        await store.upsert_tools(sample_tools, vectors)

        results = await store.search(vectors[0], top_k=10, server_id_filter="@anthropic/fetch-mcp")
        assert all(r.tool.server_id == "@anthropic/fetch-mcp" for r in results)

    async def test_search_result_contains_correct_tool_data(self, store, sample_tools):
        await store.ensure_collection(dimension=VECTOR_DIM)
        vectors = random_vectors(len(sample_tools))
        await store.upsert_tools(sample_tools, vectors)

        results = await store.search(vectors[0], top_k=10)
        tool_ids = {r.tool.tool_id for r in results}
        expected_ids = {t.tool_id for t in sample_tools}
        assert tool_ids == expected_ids

    async def test_search_empty_collection(self, store):
        await store.ensure_collection(dimension=VECTOR_DIM)
        query = np.zeros(VECTOR_DIM, dtype=np.float32)
        results = await store.search(query, top_k=5)
        assert results == []


class TestErrorHandling:
    async def test_ensure_collection_fails_on_bad_connection(self):
        """Qdrant error handling when connection is invalid."""
        bad_client = AsyncQdrantClient(url="http://localhost:9999", timeout=1)
        store = QdrantStore(client=bad_client, collection_name="nonexistent")
        with pytest.raises(Exception):
            await store.ensure_collection(dimension=128)
        await bad_client.close()

    async def test_upsert_fails_on_nonexistent_collection(self, qdrant_client):
        """Upsert to a collection that doesn't exist should raise."""
        store = QdrantStore(client=qdrant_client, collection_name="nonexistent_collection_xyz")
        tools = [MCPTool(server_id="srv", tool_name="t", tool_id="srv::t", description="d")]
        vectors = [np.random.default_rng(42).standard_normal(128).astype(np.float32)]
        with pytest.raises(Exception):
            await store.upsert_tools(tools, vectors)

    async def test_search_fails_on_nonexistent_collection(self, qdrant_client):
        """Search on a collection that doesn't exist should raise."""
        store = QdrantStore(client=qdrant_client, collection_name="nonexistent_collection_xyz")
        with pytest.raises(Exception):
            await store.search(np.zeros(128, dtype=np.float32), top_k=5)

    async def test_search_server_ids_fails_on_nonexistent_collection(self, qdrant_client):
        """search_server_ids on nonexistent collection should raise."""
        store = QdrantStore(client=qdrant_client, collection_name="nonexistent_collection_xyz")
        with pytest.raises(Exception):
            await store.search_server_ids(np.zeros(128, dtype=np.float32), top_k=5)


class TestSearchServerIds:
    async def test_returns_server_ids(self, store, sample_tools):
        await store.ensure_collection(dimension=VECTOR_DIM)
        vectors = random_vectors(len(sample_tools))
        await store.upsert_tools(sample_tools, vectors)

        server_ids = await store.search_server_ids(vectors[0], top_k=10)
        assert isinstance(server_ids, list)
        assert len(server_ids) > 0
        assert all(isinstance(s, str) for s in server_ids)

    async def test_returns_unique_relevant_servers(self, store, sample_tools):
        await store.ensure_collection(dimension=VECTOR_DIM)
        vectors = random_vectors(len(sample_tools))
        await store.upsert_tools(sample_tools, vectors)

        server_ids = await store.search_server_ids(vectors[0], top_k=10)
        # We have 2 unique server_ids in sample_tools
        expected = {"@smithery-ai/github", "@anthropic/fetch-mcp"}
        assert set(server_ids).issubset(expected)
