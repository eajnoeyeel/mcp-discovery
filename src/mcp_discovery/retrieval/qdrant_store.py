"""Qdrant Cloud vector store wrapper."""

import uuid

import numpy as np
from loguru import logger
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchAny,
    MatchValue,
    PointStruct,
    Prefetch,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)
from qdrant_client.models import (
    SparseVector as QdrantSparseVector,
)

from mcp_discovery.embedding.sparse_embedder import SparseVector
from mcp_discovery.models import MCPServer, MCPTool, SearchResult

MCP_DISCOVERY_NAMESPACE = uuid.UUID("7f1b3d4e-2a5c-4b8f-9e6d-1c0a3f5b7d9e")


class QdrantStore:
    """Qdrant Cloud wrapper for MCP tool vectors."""

    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str = "mcp_tools",
        pool_server_ids: list[str] | None = None,
    ) -> None:
        self.client = client
        self.collection_name = collection_name
        # Optional pool filter: restricts all searches to these server IDs.
        # Used for E5 pool-scale sweep — ensures Qdrant results respect the active pool.
        self._pool_filter: Filter | None = (
            Filter(must=[FieldCondition(key="server_id", match=MatchAny(any=pool_server_ids))])
            if pool_server_ids
            else None
        )

    async def ensure_collection(self, dimension: int) -> None:
        try:
            collections = await self.client.get_collections()
        except Exception as e:
            logger.error(f"Qdrant get_collections failed: {e}")
            raise
        existing = [c.name for c in collections.collections]
        if self.collection_name in existing:
            # Validate existing collection schema matches expected dimension/distance
            try:
                info = await self.client.get_collection(self.collection_name)
                config = info.config.params.vectors
                if isinstance(config, VectorParams):
                    existing_dim = config.size
                    existing_dist = config.distance
                elif isinstance(config, dict) and "" in config:
                    existing_dim = config[""].size
                    existing_dist = config[""].distance
                else:
                    logger.warning(
                        f"Collection '{self.collection_name}' has unexpected vector config type. "
                        "Skipping schema validation."
                    )
                    return
                if existing_dim != dimension:
                    raise ValueError(
                        f"Collection '{self.collection_name}' dimension mismatch: "
                        f"expected {dimension}, found {existing_dim}. "
                        "Delete the collection or use matching embedding_dimension."
                    )
                if existing_dist != Distance.COSINE:
                    raise ValueError(
                        f"Collection '{self.collection_name}' distance mismatch: "
                        f"expected COSINE, found {existing_dist}."
                    )
            except ValueError:
                raise
            except Exception as e:
                logger.warning(f"Could not validate collection schema: {e}")
            logger.info(f"Collection '{self.collection_name}' already exists (dim={dimension} OK)")
            return
        try:
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )
        except Exception as e:
            logger.error(f"Qdrant create_collection failed: {e}")
            raise
        logger.info(f"Created collection '{self.collection_name}' (dim={dimension})")

    async def upsert_tools(self, tools: list[MCPTool], vectors: list[np.ndarray]) -> None:
        if len(tools) != len(vectors):
            raise ValueError(
                f"tools/vectors length mismatch: {len(tools)} tools vs {len(vectors)} vectors"
            )
        points = [
            PointStruct(
                id=self.generate_point_id(tool.tool_id),
                vector=vector.tolist(),
                payload=self.tool_to_payload(tool),
            )
            for tool, vector in zip(tools, vectors)
        ]
        try:
            await self.client.upsert(collection_name=self.collection_name, points=points)
        except Exception as e:
            logger.error(f"Qdrant upsert failed ({len(points)} points): {e}")
            raise
        logger.info(f"Upserted {len(points)} points to '{self.collection_name}'")

    async def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        server_id_filter: str | None = None,
        query_filter: Filter | None = None,
    ) -> list[SearchResult]:
        """Search the collection for nearest neighbours.

        Filter precedence (all must-clauses are ANDed by Qdrant):
        - server_id_filter: restrict to a single server (used by SequentialStrategy Layer 2)
        - query_filter: arbitrary additional filter (caller-supplied)
        - _pool_filter: pool-level restriction set at construction time (E5 sweep)
        """
        must_conditions = []
        if server_id_filter:
            must_conditions.append(
                FieldCondition(key="server_id", match=MatchValue(value=server_id_filter))
            )
        # Merge explicit query_filter must-clauses
        if query_filter is not None and query_filter.must:
            must_conditions.extend(query_filter.must)
        # Merge pool-level filter must-clauses
        if self._pool_filter is not None and self._pool_filter.must:
            must_conditions.extend(self._pool_filter.must)
        combined_filter = Filter(must=must_conditions) if must_conditions else None
        try:
            response = await self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector.tolist(),
                limit=top_k,
                query_filter=combined_filter,
            )
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}")
            raise
        return [
            SearchResult(
                tool=self.payload_to_tool(hit.payload),
                score=hit.score,
                rank=i + 1,
            )
            for i, hit in enumerate(response.points)
        ]

    async def search_server_ids(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
    ) -> list[str]:
        """Search collection and extract server_id from each hit's payload.

        Use with mcp_servers collection. Payloads must contain 'server_id'.
        Hits without 'server_id' in payload are silently skipped.

        Args:
            query_vector: Embedded query vector.
            top_k: Maximum number of servers to return.

        Returns:
            List of server_id strings, ordered by relevance score.
        """
        query_filter = self._pool_filter if self._pool_filter is not None else None
        try:
            response = await self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector.tolist(),
                limit=top_k,
                query_filter=query_filter,
            )
        except Exception as e:
            logger.error(f"Qdrant server search failed: {e}")
            raise
        server_ids = []
        for hit in response.points:
            if hit.payload and (sid := hit.payload.get("server_id")):
                server_ids.append(sid)
        return server_ids

    async def fetch_tool_payloads(self, tool_ids: list[str]) -> dict[str, dict]:
        if not tool_ids:
            return {}

        point_ids = [self.generate_point_id(tool_id) for tool_id in tool_ids]
        try:
            points = await self.client.retrieve(
                collection_name=self.collection_name,
                ids=point_ids,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as e:
            logger.error(f"Qdrant retrieve failed ({len(point_ids)} points): {e}")
            raise

        payloads: dict[str, dict] = {}
        for point in points:
            payload = point.payload or {}
            tool_id = payload.get("tool_id")
            if tool_id:
                payloads[tool_id] = payload
        return payloads

    async def upsert_servers(self, servers: list[MCPServer], vectors: list[np.ndarray]) -> None:
        """Upsert server-level embeddings into the server collection (mcp_servers)."""
        if len(servers) != len(vectors):
            raise ValueError(
                f"servers/vectors length mismatch: {len(servers)} servers vs {len(vectors)} vectors"
            )
        points = [
            PointStruct(
                id=self.generate_point_id(server.server_id),
                vector=vector.tolist(),
                payload={"server_id": server.server_id, "description": server.description},
            )
            for server, vector in zip(servers, vectors)
        ]
        try:
            await self.client.upsert(collection_name=self.collection_name, points=points)
        except Exception as e:
            logger.error(f"Qdrant server upsert failed ({len(points)} points): {e}")
            raise
        logger.info(f"Upserted {len(points)} server points to '{self.collection_name}'")

    async def ensure_hybrid_collection(self, dense_dimension: int) -> None:
        """Create a collection with named dense + sparse vectors (hybrid search support).

        Uses named vectors_config (dict) so both 'dense' and 'sparse' vector
        spaces coexist in the same collection. Skips creation if the collection
        already exists.
        """
        try:
            collections = await self.client.get_collections()
        except Exception as e:
            logger.error(f"Qdrant get_collections failed: {e}")
            raise
        existing = [c.name for c in collections.collections]
        if self.collection_name in existing:
            logger.info(
                f"Collection '{self.collection_name}' already exists — skipping hybrid creation"
            )
            return
        try:
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "dense": VectorParams(size=dense_dimension, distance=Distance.COSINE)
                },
                sparse_vectors_config={"sparse": SparseVectorParams(index=SparseIndexParams())},
            )
        except Exception as e:
            logger.error(f"Qdrant create_collection (hybrid) failed: {e}")
            raise
        try:
            from qdrant_client.models import PayloadSchemaType

            await self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="server_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as e:
            logger.warning(f"Failed to create server_id payload index: {e}")
        logger.info(
            f"Created hybrid collection '{self.collection_name}' (dense_dim={dense_dimension})"
        )

    async def upsert_tools_hybrid(
        self,
        tools: list[MCPTool],
        dense_vectors: list[np.ndarray],
        sparse_vectors: list[SparseVector],
        extra_payloads: list[dict] | None = None,
    ) -> None:
        """Upsert tools with both dense and sparse vectors into a hybrid collection.

        Args:
            tools: MCPTool objects to index.
            dense_vectors: Dense embedding arrays (one per tool).
            sparse_vectors: Sparse vectors (one per tool).
            extra_payloads: Optional list of dicts merged into each point's payload.
                Must have the same length as ``tools`` when provided.
        """
        if len(tools) != len(dense_vectors) or len(tools) != len(sparse_vectors):
            raise ValueError(
                f"Length mismatch: tools={len(tools)}, dense_vectors={len(dense_vectors)}, "
                f"sparse_vectors={len(sparse_vectors)}"
            )
        if extra_payloads is not None and len(extra_payloads) != len(tools):
            raise ValueError(
                f"extra_payloads length ({len(extra_payloads)}) must match "
                f"tools length ({len(tools)})"
            )
        points = [
            PointStruct(
                id=self.generate_point_id(tool.tool_id),
                vector={
                    "dense": dense.tolist(),
                    "sparse": QdrantSparseVector(indices=sparse.indices, values=sparse.values),
                },
                payload={
                    **self.tool_to_payload(tool),
                    **(extra_payloads[i] if extra_payloads is not None else {}),
                },
            )
            for i, (tool, dense, sparse) in enumerate(zip(tools, dense_vectors, sparse_vectors))
        ]
        try:
            await self.client.upsert(collection_name=self.collection_name, points=points)
        except Exception as e:
            logger.error(f"Qdrant hybrid upsert failed ({len(points)} points): {e}")
            raise
        logger.info(f"Upserted {len(points)} hybrid points to '{self.collection_name}'")

    async def hybrid_search(
        self,
        dense_vector: np.ndarray,
        sparse_vector: SparseVector,
        top_k: int = 10,
        prefetch_limit: int = 20,
    ) -> list[SearchResult]:
        """Hybrid search using dense + sparse prefetch with RRF score fusion.

        Applies pool_server_ids filter (E5 sweep) to both prefetch queries
        when configured at construction time.
        """
        combined_filter = self._pool_filter
        try:
            response = await self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    Prefetch(
                        query=dense_vector.tolist(),
                        using="dense",
                        limit=prefetch_limit,
                        filter=combined_filter,
                    ),
                    Prefetch(
                        query=QdrantSparseVector(
                            indices=sparse_vector.indices,
                            values=sparse_vector.values,
                        ),
                        using="sparse",
                        limit=prefetch_limit,
                        filter=combined_filter,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=top_k,
            )
        except Exception as e:
            logger.error(f"Qdrant hybrid search failed: {e}")
            raise
        return [
            SearchResult(
                tool=self.payload_to_tool(hit.payload),
                score=hit.score,
                rank=i + 1,
            )
            for i, hit in enumerate(response.points)
        ]

    @staticmethod
    def build_server_text(server: MCPServer) -> str:
        if server.description:
            return f"{server.name}: {server.description}"
        return server.name

    @staticmethod
    def build_tool_text(tool: MCPTool) -> str:
        if tool.description:
            return f"{tool.tool_name}: {tool.description}"
        return tool.tool_name

    @staticmethod
    def tool_to_payload(tool: MCPTool) -> dict:
        payload: dict = {
            "tool_id": tool.tool_id,
            "server_id": tool.server_id,
            "tool_name": tool.tool_name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        if tool.selection_description is not None:
            payload["selection_description"] = tool.selection_description
        return payload

    @staticmethod
    def payload_to_tool(payload: dict) -> MCPTool:
        try:
            return MCPTool(
                server_id=payload["server_id"],
                tool_name=payload["tool_name"],
                tool_id=payload["tool_id"],
                description=payload.get("description"),
                selection_description=payload.get("selection_description"),
                input_schema=payload.get("input_schema"),
            )
        except (KeyError, Exception) as e:
            logger.error(
                f"Failed to reconstruct MCPTool from payload: {e}. "
                f"Payload keys: {list(payload.keys())}"
            )
            raise

    @staticmethod
    def generate_point_id(tool_id: str) -> str:
        return str(uuid.uuid5(MCP_DISCOVERY_NAMESPACE, tool_id))
