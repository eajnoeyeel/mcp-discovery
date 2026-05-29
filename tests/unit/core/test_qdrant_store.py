"""Tests for QdrantStore — Qdrant Cloud wrapper."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from mcp_discovery.models import MCPTool
from mcp_discovery.retrieval.qdrant_store import MCP_DISCOVERY_NAMESPACE, QdrantStore


@pytest.fixture
def sample_tool() -> MCPTool:
    return MCPTool(
        server_id="@smithery-ai/github",
        tool_name="search_issues",
        tool_id="@smithery-ai/github::search_issues",
        description="Search GitHub issues by query",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    )


@pytest.fixture
def tool_no_description() -> MCPTool:
    return MCPTool(
        server_id="@test/srv",
        tool_name="no_desc",
        tool_id="@test/srv::no_desc",
    )


class TestBuildToolText:
    def test_with_description(self, sample_tool):
        text = QdrantStore.build_tool_text(sample_tool)
        assert text == "search_issues: Search GitHub issues by query"

    def test_without_description(self, tool_no_description):
        text = QdrantStore.build_tool_text(tool_no_description)
        assert text == "no_desc"


class TestToolToPayload:
    def test_contains_required_fields(self, sample_tool):
        payload = QdrantStore.tool_to_payload(sample_tool)
        assert payload["tool_id"] == "@smithery-ai/github::search_issues"
        assert payload["server_id"] == "@smithery-ai/github"
        assert payload["tool_name"] == "search_issues"
        assert payload["description"] == "Search GitHub issues by query"
        assert payload["input_schema"] is not None

    def test_none_description(self, tool_no_description):
        payload = QdrantStore.tool_to_payload(tool_no_description)
        assert payload["description"] is None

    def test_selection_description_included_when_set(self):
        tool = MCPTool(
            server_id="airtable",
            tool_name="search_records",
            tool_id="airtable::search_records",
            description="Search for records containing specific text",
            selection_description="Accepts base_id, table_name, and search_text.",
        )
        payload = QdrantStore.tool_to_payload(tool)
        assert payload["selection_description"] == "Accepts base_id, table_name, and search_text."

    def test_selection_description_omitted_when_none(self, sample_tool):
        payload = QdrantStore.tool_to_payload(sample_tool)
        assert "selection_description" not in payload


class TestPayloadToTool:
    def test_roundtrip(self, sample_tool):
        payload = QdrantStore.tool_to_payload(sample_tool)
        restored = QdrantStore.payload_to_tool(payload)
        assert restored.tool_id == sample_tool.tool_id
        assert restored.server_id == sample_tool.server_id
        assert restored.tool_name == sample_tool.tool_name
        assert restored.description == sample_tool.description

    def test_roundtrip_with_selection_description(self):
        tool = MCPTool(
            server_id="airtable",
            tool_name="search_records",
            tool_id="airtable::search_records",
            description="Search for records containing specific text",
            selection_description="Accepts base_id, table_name, and search_text.",
        )
        payload = QdrantStore.tool_to_payload(tool)
        restored = QdrantStore.payload_to_tool(payload)
        assert restored.selection_description == "Accepts base_id, table_name, and search_text."
        assert restored.description == "Search for records containing specific text"

    def test_roundtrip_selection_description_none_when_absent(self, sample_tool):
        payload = QdrantStore.tool_to_payload(sample_tool)
        restored = QdrantStore.payload_to_tool(payload)
        assert restored.selection_description is None

    def test_raises_on_missing_key(self):
        bad_payload = {"server_id": "srv"}  # missing tool_name, tool_id
        with pytest.raises(Exception):
            QdrantStore.payload_to_tool(bad_payload)


class TestGeneratePointId:
    def test_deterministic(self):
        id1 = QdrantStore.generate_point_id("@test/srv::tool")
        id2 = QdrantStore.generate_point_id("@test/srv::tool")
        assert id1 == id2

    def test_different_ids_for_different_tools(self):
        id1 = QdrantStore.generate_point_id("@a/srv::tool1")
        id2 = QdrantStore.generate_point_id("@a/srv::tool2")
        assert id1 != id2

    def test_returns_valid_uuid_string(self):
        result = QdrantStore.generate_point_id("@test/srv::tool")
        parsed = uuid.UUID(result)
        assert str(parsed) == result

    def test_uses_uuid5(self):
        tool_id = "@test/srv::tool"
        expected = str(uuid.uuid5(MCP_DISCOVERY_NAMESPACE, tool_id))
        assert QdrantStore.generate_point_id(tool_id) == expected


class TestMCPDiscoveryNamespace:
    def test_is_valid_uuid(self):
        assert isinstance(MCP_DISCOVERY_NAMESPACE, uuid.UUID)

    def test_is_fixed_value(self):
        assert str(MCP_DISCOVERY_NAMESPACE) == "7f1b3d4e-2a5c-4b8f-9e6d-1c0a3f5b7d9e"


class TestSearchServerIds:
    async def test_returns_server_ids_from_payloads(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = [
            MagicMock(payload={"server_id": "srv1", "name": "Server 1"}),
            MagicMock(payload={"server_id": "srv2", "name": "Server 2"}),
        ]
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_servers")
        server_ids = await store.search_server_ids(np.zeros(1536), top_k=5)
        assert server_ids == ["srv1", "srv2"]

    async def test_skips_payloads_without_server_id(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = [
            MagicMock(payload={"server_id": "srv1"}),
            MagicMock(payload={"name": "no_server_id_here"}),
            MagicMock(payload=None),
        ]
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_servers")
        server_ids = await store.search_server_ids(np.zeros(1536), top_k=5)
        assert server_ids == ["srv1"]

    async def test_passes_top_k_to_client(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_servers")
        await store.search_server_ids(np.zeros(1536), top_k=7)
        call_kwargs = mock_client.query_points.call_args.kwargs
        assert call_kwargs["limit"] == 7

    async def test_applies_pool_filter_to_server_search(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(
            client=mock_client,
            collection_name="mcp_servers",
            pool_server_ids=["srv1", "srv2"],
        )

        await store.search_server_ids(np.zeros(1536), top_k=5)

        call_kwargs = mock_client.query_points.call_args.kwargs
        query_filter = call_kwargs["query_filter"]
        assert query_filter is not None
        assert query_filter.must[0].key == "server_id"
        assert query_filter.must[0].match.any == ["srv1", "srv2"]


class TestFetchToolPayloads:
    async def test_fetch_tool_payloads_retrieves_payloads_by_deterministic_point_id(self):
        mock_client = AsyncMock()
        mock_client.retrieve = AsyncMock(
            return_value=[
                MagicMock(
                    payload={
                        "tool_id": "@test/srv::tool",
                        "server_id": "@test/srv",
                        "tool_name": "tool",
                        "description": "Search docs",
                    }
                )
            ]
        )
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        payloads = await store.fetch_tool_payloads(["@test/srv::tool"])

        assert payloads["@test/srv::tool"]["description"] == "Search docs"
        call_kwargs = mock_client.retrieve.call_args.kwargs
        assert call_kwargs["ids"] == [QdrantStore.generate_point_id("@test/srv::tool")]
        assert call_kwargs["with_payload"] is True
        assert call_kwargs["with_vectors"] is False

    async def test_fetch_tool_payloads_returns_empty_dict_without_calling_qdrant_for_empty_input(
        self,
    ):
        mock_client = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        assert await store.fetch_tool_payloads([]) == {}
        mock_client.retrieve.assert_not_called()


# ---------------------------------------------------------------------------
# EnsureCollection
# ---------------------------------------------------------------------------
class TestEnsureCollection:
    async def test_creates_collection_when_not_existing(self):
        mock_client = AsyncMock()
        collections_resp = MagicMock()
        collections_resp.collections = []
        mock_client.get_collections = AsyncMock(return_value=collections_resp)
        mock_client.create_collection = AsyncMock()

        store = QdrantStore(client=mock_client, collection_name="mcp_tools")
        await store.ensure_collection(dimension=1536)

        mock_client.create_collection.assert_awaited_once()
        call_kwargs = mock_client.create_collection.call_args.kwargs
        assert call_kwargs["collection_name"] == "mcp_tools"

    async def test_skips_creation_when_collection_already_exists_and_dims_match(self):
        from qdrant_client.models import Distance, VectorParams

        mock_client = AsyncMock()
        collections_resp = MagicMock()
        coll = MagicMock()
        coll.name = "mcp_tools"
        collections_resp.collections = [coll]
        mock_client.get_collections = AsyncMock(return_value=collections_resp)

        info = MagicMock()
        info.config.params.vectors = VectorParams(size=1536, distance=Distance.COSINE)
        mock_client.get_collection = AsyncMock(return_value=info)

        store = QdrantStore(client=mock_client, collection_name="mcp_tools")
        await store.ensure_collection(dimension=1536)

        mock_client.create_collection.assert_not_awaited()

    async def test_raises_on_dimension_mismatch(self):
        from qdrant_client.models import Distance, VectorParams

        mock_client = AsyncMock()
        collections_resp = MagicMock()
        coll = MagicMock()
        coll.name = "mcp_tools"
        collections_resp.collections = [coll]
        mock_client.get_collections = AsyncMock(return_value=collections_resp)

        info = MagicMock()
        info.config.params.vectors = VectorParams(size=512, distance=Distance.COSINE)
        mock_client.get_collection = AsyncMock(return_value=info)

        store = QdrantStore(client=mock_client, collection_name="mcp_tools")
        with pytest.raises(ValueError, match="dimension mismatch"):
            await store.ensure_collection(dimension=1536)

    async def test_raises_on_distance_mismatch(self):
        from qdrant_client.models import Distance, VectorParams

        mock_client = AsyncMock()
        collections_resp = MagicMock()
        coll = MagicMock()
        coll.name = "mcp_tools"
        collections_resp.collections = [coll]
        mock_client.get_collections = AsyncMock(return_value=collections_resp)

        info = MagicMock()
        info.config.params.vectors = VectorParams(size=1536, distance=Distance.DOT)
        mock_client.get_collection = AsyncMock(return_value=info)

        store = QdrantStore(client=mock_client, collection_name="mcp_tools")
        with pytest.raises(ValueError, match="distance mismatch"):
            await store.ensure_collection(dimension=1536)

    async def test_handles_dict_vector_config_with_empty_key(self):
        from qdrant_client.models import Distance, VectorParams

        mock_client = AsyncMock()
        collections_resp = MagicMock()
        coll = MagicMock()
        coll.name = "mcp_tools"
        collections_resp.collections = [coll]
        mock_client.get_collections = AsyncMock(return_value=collections_resp)

        info = MagicMock()
        info.config.params.vectors = {"": VectorParams(size=1536, distance=Distance.COSINE)}
        mock_client.get_collection = AsyncMock(return_value=info)

        store = QdrantStore(client=mock_client, collection_name="mcp_tools")
        await store.ensure_collection(dimension=1536)

        mock_client.create_collection.assert_not_awaited()

    async def test_skips_validation_for_unknown_vector_config_type(self):
        mock_client = AsyncMock()
        collections_resp = MagicMock()
        coll = MagicMock()
        coll.name = "mcp_tools"
        collections_resp.collections = [coll]
        mock_client.get_collections = AsyncMock(return_value=collections_resp)

        info = MagicMock()
        # Not a VectorParams or dict-with-empty-key — triggers the warning+return branch
        info.config.params.vectors = {"dense": MagicMock()}
        mock_client.get_collection = AsyncMock(return_value=info)

        store = QdrantStore(client=mock_client, collection_name="mcp_tools")
        # Should return without raising
        await store.ensure_collection(dimension=1536)
        mock_client.create_collection.assert_not_awaited()

    async def test_raises_when_get_collections_fails(self):
        mock_client = AsyncMock()
        mock_client.get_collections = AsyncMock(side_effect=RuntimeError("network error"))

        store = QdrantStore(client=mock_client, collection_name="mcp_tools")
        with pytest.raises(RuntimeError, match="network error"):
            await store.ensure_collection(dimension=1536)

    async def test_raises_when_create_collection_fails(self):
        mock_client = AsyncMock()
        collections_resp = MagicMock()
        collections_resp.collections = []
        mock_client.get_collections = AsyncMock(return_value=collections_resp)
        mock_client.create_collection = AsyncMock(side_effect=RuntimeError("create failed"))

        store = QdrantStore(client=mock_client, collection_name="mcp_tools")
        with pytest.raises(RuntimeError, match="create failed"):
            await store.ensure_collection(dimension=1536)

    async def test_continues_when_get_collection_schema_validation_raises_non_value_error(self):
        mock_client = AsyncMock()
        collections_resp = MagicMock()
        coll = MagicMock()
        coll.name = "mcp_tools"
        collections_resp.collections = [coll]
        mock_client.get_collections = AsyncMock(return_value=collections_resp)
        mock_client.get_collection = AsyncMock(side_effect=Exception("schema fetch failed"))

        store = QdrantStore(client=mock_client, collection_name="mcp_tools")
        # Should NOT raise — non-ValueError schema errors are logged and swallowed
        await store.ensure_collection(dimension=1536)


# ---------------------------------------------------------------------------
# UpsertTools
# ---------------------------------------------------------------------------
class TestUpsertTools:
    async def test_upserts_points_for_each_tool(self, sample_tool):
        mock_client = AsyncMock()
        mock_client.upsert = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        vectors = [np.random.rand(1536)]
        await store.upsert_tools([sample_tool], vectors)

        mock_client.upsert.assert_awaited_once()
        call_kwargs = mock_client.upsert.call_args.kwargs
        assert call_kwargs["collection_name"] == "mcp_tools"
        assert len(call_kwargs["points"]) == 1

    async def test_raises_on_length_mismatch(self, sample_tool):
        mock_client = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        with pytest.raises(ValueError, match="length mismatch"):
            await store.upsert_tools([sample_tool], [])

    async def test_raises_when_upsert_fails(self, sample_tool):
        mock_client = AsyncMock()
        mock_client.upsert = AsyncMock(side_effect=RuntimeError("upsert failed"))
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        with pytest.raises(RuntimeError, match="upsert failed"):
            await store.upsert_tools([sample_tool], [np.random.rand(1536)])

    async def test_point_id_is_deterministic_uuid(self, sample_tool):
        mock_client = AsyncMock()
        mock_client.upsert = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        await store.upsert_tools([sample_tool], [np.zeros(1536)])
        points = mock_client.upsert.call_args.kwargs["points"]
        expected_id = QdrantStore.generate_point_id(sample_tool.tool_id)
        assert points[0].id == expected_id


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
class TestSearch:
    def _make_hit(self, tool_id: str, server_id: str, tool_name: str, score: float) -> MagicMock:
        hit = MagicMock()
        hit.score = score
        hit.payload = {
            "tool_id": tool_id,
            "server_id": server_id,
            "tool_name": tool_name,
            "description": "A test tool",
        }
        return hit

    async def test_returns_search_results_ordered_by_rank(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = [
            self._make_hit("srv::tool_a", "srv", "tool_a", 0.9),
            self._make_hit("srv::tool_b", "srv", "tool_b", 0.7),
        ]
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        results = await store.search(np.zeros(1536), top_k=2)

        assert len(results) == 2
        assert results[0].rank == 1
        assert results[0].score == 0.9
        assert results[1].rank == 2
        assert results[1].score == 0.7

    async def test_passes_top_k_to_client(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        await store.search(np.zeros(1536), top_k=5)

        call_kwargs = mock_client.query_points.call_args.kwargs
        assert call_kwargs["limit"] == 5

    async def test_applies_server_id_filter(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        await store.search(np.zeros(1536), server_id_filter="my-server")

        call_kwargs = mock_client.query_points.call_args.kwargs
        query_filter = call_kwargs["query_filter"]
        assert query_filter is not None
        assert query_filter.must[0].key == "server_id"
        assert query_filter.must[0].match.value == "my-server"

    async def test_merges_server_id_filter_with_pool_filter(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(
            client=mock_client,
            collection_name="mcp_tools",
            pool_server_ids=["srv1", "srv2"],
        )

        await store.search(np.zeros(1536), server_id_filter="srv1")

        call_kwargs = mock_client.query_points.call_args.kwargs
        query_filter = call_kwargs["query_filter"]
        # Both server_id match and pool filter must-clauses are present
        assert len(query_filter.must) == 2

    async def test_no_filter_when_no_conditions(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        await store.search(np.zeros(1536))

        call_kwargs = mock_client.query_points.call_args.kwargs
        assert call_kwargs["query_filter"] is None

    async def test_raises_when_query_points_fails(self):
        mock_client = AsyncMock()
        mock_client.query_points = AsyncMock(side_effect=RuntimeError("search failed"))
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        with pytest.raises(RuntimeError, match="search failed"):
            await store.search(np.zeros(1536))

    async def test_merges_caller_supplied_query_filter(self):
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        extra_filter = Filter(must=[FieldCondition(key="status", match=MatchValue(value="active"))])
        await store.search(np.zeros(1536), query_filter=extra_filter)

        call_kwargs = mock_client.query_points.call_args.kwargs
        query_filter = call_kwargs["query_filter"]
        assert query_filter is not None
        assert any(c.key == "status" for c in query_filter.must)

    async def test_returns_empty_list_when_no_hits(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        results = await store.search(np.zeros(1536))

        assert results == []


# ---------------------------------------------------------------------------
# SearchServerIds — error path
# ---------------------------------------------------------------------------
class TestSearchServerIdsErrorPath:
    async def test_raises_when_query_points_fails(self):
        mock_client = AsyncMock()
        mock_client.query_points = AsyncMock(side_effect=RuntimeError("server search failed"))
        store = QdrantStore(client=mock_client, collection_name="mcp_servers")

        with pytest.raises(RuntimeError, match="server search failed"):
            await store.search_server_ids(np.zeros(1536))


# ---------------------------------------------------------------------------
# FetchToolPayloads — error path
# ---------------------------------------------------------------------------
class TestFetchToolPayloadsErrorPath:
    async def test_raises_when_retrieve_fails(self):
        mock_client = AsyncMock()
        mock_client.retrieve = AsyncMock(side_effect=RuntimeError("retrieve failed"))
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        with pytest.raises(RuntimeError, match="retrieve failed"):
            await store.fetch_tool_payloads(["srv::tool"])

    async def test_skips_points_without_tool_id_in_payload(self):
        mock_client = AsyncMock()
        mock_client.retrieve = AsyncMock(
            return_value=[
                MagicMock(payload={"description": "no tool_id"}),
                MagicMock(payload=None),
            ]
        )
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")

        payloads = await store.fetch_tool_payloads(["srv::tool"])
        assert payloads == {}


# ---------------------------------------------------------------------------
# UpsertServers
# ---------------------------------------------------------------------------
class TestUpsertServers:
    def _make_server(self, server_id: str = "test-srv"):
        from mcp_discovery.models import MCPServer

        return MCPServer(server_id=server_id, name="Test Server", description="A test server")

    async def test_upserts_server_points(self):
        mock_client = AsyncMock()
        mock_client.upsert = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_servers")
        server = self._make_server()

        await store.upsert_servers([server], [np.zeros(1536)])

        mock_client.upsert.assert_awaited_once()
        points = mock_client.upsert.call_args.kwargs["points"]
        assert len(points) == 1
        assert points[0].payload["server_id"] == "test-srv"
        assert points[0].payload["description"] == "A test server"

    async def test_raises_on_length_mismatch(self):
        mock_client = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_servers")
        server = self._make_server()

        with pytest.raises(ValueError, match="length mismatch"):
            await store.upsert_servers([server], [])

    async def test_raises_when_upsert_fails(self):
        mock_client = AsyncMock()
        mock_client.upsert = AsyncMock(side_effect=RuntimeError("upsert failed"))
        store = QdrantStore(client=mock_client, collection_name="mcp_servers")
        server = self._make_server()

        with pytest.raises(RuntimeError, match="upsert failed"):
            await store.upsert_servers([server], [np.zeros(1536)])

    async def test_point_id_is_deterministic_for_server(self):
        mock_client = AsyncMock()
        mock_client.upsert = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_servers")
        server = self._make_server("my-server")

        await store.upsert_servers([server], [np.zeros(1536)])
        points = mock_client.upsert.call_args.kwargs["points"]
        expected_id = QdrantStore.generate_point_id("my-server")
        assert points[0].id == expected_id


# ---------------------------------------------------------------------------
# EnsureHybridCollection
# ---------------------------------------------------------------------------
class TestEnsureHybridCollection:
    async def test_creates_hybrid_collection_when_not_existing(self):
        mock_client = AsyncMock()
        collections_resp = MagicMock()
        collections_resp.collections = []
        mock_client.get_collections = AsyncMock(return_value=collections_resp)
        mock_client.create_collection = AsyncMock()

        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")
        await store.ensure_hybrid_collection(dense_dimension=1536)

        mock_client.create_collection.assert_awaited_once()
        call_kwargs = mock_client.create_collection.call_args.kwargs
        assert "dense" in call_kwargs["vectors_config"]
        assert "sparse" in call_kwargs["sparse_vectors_config"]

    async def test_skips_creation_when_hybrid_collection_exists(self):
        mock_client = AsyncMock()
        collections_resp = MagicMock()
        coll = MagicMock()
        coll.name = "mcp_hybrid"
        collections_resp.collections = [coll]
        mock_client.get_collections = AsyncMock(return_value=collections_resp)

        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")
        await store.ensure_hybrid_collection(dense_dimension=1536)

        mock_client.create_collection.assert_not_awaited()

    async def test_raises_when_get_collections_fails(self):
        mock_client = AsyncMock()
        mock_client.get_collections = AsyncMock(side_effect=RuntimeError("network error"))

        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")
        with pytest.raises(RuntimeError, match="network error"):
            await store.ensure_hybrid_collection(dense_dimension=1536)

    async def test_raises_when_create_hybrid_collection_fails(self):
        mock_client = AsyncMock()
        collections_resp = MagicMock()
        collections_resp.collections = []
        mock_client.get_collections = AsyncMock(return_value=collections_resp)
        mock_client.create_collection = AsyncMock(side_effect=RuntimeError("create failed"))

        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")
        with pytest.raises(RuntimeError, match="create failed"):
            await store.ensure_hybrid_collection(dense_dimension=1536)


# ---------------------------------------------------------------------------
# UpsertToolsHybrid
# ---------------------------------------------------------------------------
class TestUpsertToolsHybrid:
    def _make_sparse(self):
        from mcp_discovery.embedding.sparse_embedder import SparseVector

        return SparseVector(indices=[0, 1, 2], values=[0.1, 0.2, 0.3])

    async def test_upserts_hybrid_points_with_dense_and_sparse_vectors(self, sample_tool):
        mock_client = AsyncMock()
        mock_client.upsert = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")

        await store.upsert_tools_hybrid([sample_tool], [np.zeros(1536)], [self._make_sparse()])

        mock_client.upsert.assert_awaited_once()
        points = mock_client.upsert.call_args.kwargs["points"]
        assert len(points) == 1
        assert "dense" in points[0].vector
        assert "sparse" in points[0].vector

    async def test_raises_on_tools_dense_length_mismatch(self, sample_tool):
        mock_client = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")

        with pytest.raises(ValueError, match="Length mismatch"):
            await store.upsert_tools_hybrid([sample_tool], [], [self._make_sparse()])

    async def test_raises_on_tools_sparse_length_mismatch(self, sample_tool):
        mock_client = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")

        with pytest.raises(ValueError, match="Length mismatch"):
            await store.upsert_tools_hybrid([sample_tool], [np.zeros(1536)], [])

    async def test_raises_when_upsert_fails(self, sample_tool):
        mock_client = AsyncMock()
        mock_client.upsert = AsyncMock(side_effect=RuntimeError("hybrid upsert failed"))
        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")

        with pytest.raises(RuntimeError, match="hybrid upsert failed"):
            await store.upsert_tools_hybrid([sample_tool], [np.zeros(1536)], [self._make_sparse()])


# ---------------------------------------------------------------------------
# HybridSearch
# ---------------------------------------------------------------------------
class TestHybridSearch:
    def _make_hit(self, tool_id: str, server_id: str, tool_name: str, score: float) -> MagicMock:
        hit = MagicMock()
        hit.score = score
        hit.payload = {
            "tool_id": tool_id,
            "server_id": server_id,
            "tool_name": tool_name,
            "description": "Hybrid result",
        }
        return hit

    def _make_sparse(self):
        from mcp_discovery.embedding.sparse_embedder import SparseVector

        return SparseVector(indices=[0, 1], values=[0.5, 0.5])

    async def test_returns_ranked_results_from_hybrid_search(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = [
            self._make_hit("srv::tool_a", "srv", "tool_a", 0.95),
            self._make_hit("srv::tool_b", "srv", "tool_b", 0.80),
        ]
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")

        results = await store.hybrid_search(np.zeros(1536), self._make_sparse(), top_k=2)

        assert len(results) == 2
        assert results[0].rank == 1
        assert results[0].score == 0.95
        assert results[1].rank == 2

    async def test_passes_top_k_as_limit(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")

        await store.hybrid_search(np.zeros(1536), self._make_sparse(), top_k=7)

        call_kwargs = mock_client.query_points.call_args.kwargs
        assert call_kwargs["limit"] == 7

    async def test_applies_pool_filter_to_both_prefetch_queries(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(
            client=mock_client,
            collection_name="mcp_hybrid",
            pool_server_ids=["srv1", "srv2"],
        )

        await store.hybrid_search(np.zeros(1536), self._make_sparse())

        call_kwargs = mock_client.query_points.call_args.kwargs
        prefetch = call_kwargs["prefetch"]
        assert len(prefetch) == 2
        for pf in prefetch:
            assert pf.filter is not None

    async def test_raises_when_hybrid_search_fails(self):
        mock_client = AsyncMock()
        mock_client.query_points = AsyncMock(side_effect=RuntimeError("hybrid search failed"))
        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")

        with pytest.raises(RuntimeError, match="hybrid search failed"):
            await store.hybrid_search(np.zeros(1536), self._make_sparse())

    async def test_returns_empty_list_when_no_hits(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points = AsyncMock(return_value=mock_response)
        store = QdrantStore(client=mock_client, collection_name="mcp_hybrid")

        results = await store.hybrid_search(np.zeros(1536), self._make_sparse())
        assert results == []


# ---------------------------------------------------------------------------
# BuildServerText
# ---------------------------------------------------------------------------
class TestBuildServerText:
    def test_returns_name_and_description_when_description_present(self):
        from mcp_discovery.models import MCPServer

        server = MCPServer(server_id="github", name="GitHub", description="Source code hosting")
        assert QdrantStore.build_server_text(server) == "GitHub: Source code hosting"

    def test_returns_name_only_when_description_is_none(self):
        from mcp_discovery.models import MCPServer

        server = MCPServer(server_id="github", name="GitHub", description=None)
        assert QdrantStore.build_server_text(server) == "GitHub"


# ---------------------------------------------------------------------------
# PoolFilter construction
# ---------------------------------------------------------------------------
class TestPoolFilter:
    def test_pool_filter_is_none_when_no_pool_server_ids(self):
        mock_client = AsyncMock()
        store = QdrantStore(client=mock_client, collection_name="mcp_tools")
        assert store._pool_filter is None

    def test_pool_filter_is_set_when_pool_server_ids_provided(self):
        mock_client = AsyncMock()
        store = QdrantStore(
            client=mock_client,
            collection_name="mcp_tools",
            pool_server_ids=["srv1", "srv2"],
        )
        assert store._pool_filter is not None
        assert store._pool_filter.must[0].match.any == ["srv1", "srv2"]
