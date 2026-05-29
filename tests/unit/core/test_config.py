"""Tests for Settings configuration."""

import pytest

from mcp_discovery.config import Settings


@pytest.fixture
def clean_settings_env(monkeypatch):
    for key in [
        "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSION",
        "QDRANT_URL",
        "QDRANT_COLLECTION_NAME",
        "OPENAI_API_KEY",
        "QDRANT_URL",
        "QDRANT_API_KEY",
        "ENABLE_RERANKER",
        "RERANK_PROVIDER",
        "RERANK_MODEL",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)


class TestSettings:
    def test_default_qdrant_url(self, clean_settings_env):
        settings = Settings(_env_file=None)
        assert settings.qdrant_url == "http://localhost:6333"

    def test_default_confidence_gap_threshold(self, clean_settings_env):
        settings = Settings(_env_file=None)
        assert settings.confidence_gap_threshold == 0.15

    def test_default_top_k_retrieval(self, clean_settings_env):
        settings = Settings(_env_file=None)
        assert settings.top_k_retrieval == 10

    def test_default_embedding_model(self, clean_settings_env):
        settings = Settings(_env_file=None)
        assert settings.embedding_model == "text-embedding-3-large"

    def test_default_embedding_dimension(self, clean_settings_env):
        settings = Settings(_env_file=None)
        assert settings.embedding_dimension == 3072

    def test_default_smithery_api_base_url(self, clean_settings_env):
        settings = Settings(_env_file=None)
        assert settings.smithery_api_base_url == "https://registry.smithery.ai"

    def test_default_qdrant_collection_name(self, clean_settings_env):
        settings = Settings(_env_file=None)
        assert settings.qdrant_collection_name == "mcp_tools"

    def test_optional_fields_default_none(self, monkeypatch, clean_settings_env):
        settings = Settings(_env_file=None)
        assert settings.openai_api_key is None
        assert settings.qdrant_api_key is None
        assert settings.langfuse_public_key is None
        assert settings.langfuse_secret_key is None

    def test_reranker_disabled_by_default(self, clean_settings_env):
        settings = Settings(_env_file=None)
        assert settings.enable_reranker is False
        assert settings.rerank_provider == "none"
        assert settings.rerank_model == "none"
