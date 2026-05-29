"""Shared settings for MLP Lambda handlers."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class MLPSettings(BaseSettings):
    """Environment-backed settings for MLP runtime helpers."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="MLP_", extra="ignore")

    cache_ttl_seconds: int = 300
    search_top_k_default: int = 3
    warming_probe_query: str = "test"
    server_collection_name: str = "mcp_servers"
    enable_pending_freshness: bool = False
    enable_per_client_routing: bool = False
    rerank_candidate_pool_size: int = 10
    pending_freshness_limit: int = 2
    pending_freshness_timeout_ms: int = 150

    # Operability
    operability_cache_ttl: int = 60
    operability_cache_jitter: int = 10
