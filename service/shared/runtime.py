"""Shared search runtime factory for MLP handlers."""

import os
from dataclasses import dataclass

from loguru import logger
from qdrant_client import AsyncQdrantClient

from mcp_discovery.config import Settings
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder
from mcp_discovery.pipeline.flat import FlatStrategy
from mcp_discovery.pipeline.strategy import PipelineStrategy
from mcp_discovery.retrieval.qdrant_store import QdrantStore
from service.shared.settings import MLPSettings

_SPARSE_SINGLETON = None


def _get_sparse_embedder() -> object | None:
    """Return a cached FastEmbedSparseEmbedder (provides .embed_one/.embed_batch)."""
    global _SPARSE_SINGLETON
    if _SPARSE_SINGLETON is None:
        try:
            from mcp_discovery.embedding.fastembed_sparse import FastEmbedSparseEmbedder

            _SPARSE_SINGLETON = FastEmbedSparseEmbedder()
        except ImportError:
            logger.warning("fastembed not installed — sparse embedder disabled")
    return _SPARSE_SINGLETON


@dataclass
class SearchRuntime:
    settings: Settings
    mlp_settings: MLPSettings
    tool_store: QdrantStore
    server_store: QdrantStore
    strategy: PipelineStrategy
    operability_cache: object | None = None


def build_search_runtime() -> SearchRuntime:
    settings = Settings()
    mlp_settings = MLPSettings()

    if not settings.openai_api_key:
        raise ValueError("OpenAI API key is required to build the search runtime.")

    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=10)
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )
    qdrant_collection = os.environ.get("QDRANT_COLLECTION_NAME", settings.qdrant_collection_name)
    tool_store = QdrantStore(client=client, collection_name=qdrant_collection)
    server_store = QdrantStore(
        client=client,
        collection_name=mlp_settings.server_collection_name,
    )

    strategy = FlatStrategy(
        embedder=embedder,
        tool_store=tool_store,
        reranker=None,
        sparse_embedder=_get_sparse_embedder(),
    )

    from mcp_discovery.operability.cache import OperabilityCache

    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "")
    operability_cache = (
        OperabilityCache(supabase_url=supabase_url, supabase_key=supabase_key)
        if supabase_url and supabase_key
        else None
    )

    return SearchRuntime(
        settings=settings,
        mlp_settings=mlp_settings,
        tool_store=tool_store,
        server_store=server_store,
        strategy=strategy,
        operability_cache=operability_cache,
    )
