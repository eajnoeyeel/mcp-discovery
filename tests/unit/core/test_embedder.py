"""Tests for Embedder ABC and OpenAIEmbedder."""

import inspect
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from mcp_discovery.embedding.base import Embedder
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder


class TestEmbedderABC:
    def test_is_abstract(self):
        assert inspect.isabstract(Embedder)

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Embedder()

    def test_has_embed_one(self):
        assert hasattr(Embedder, "embed_one")

    def test_has_embed_batch(self):
        assert hasattr(Embedder, "embed_batch")


class TestOpenAIEmbedder:
    def test_model_and_dimension(self):
        embedder = OpenAIEmbedder(api_key="fake-key")
        assert embedder.model == "text-embedding-3-small"
        assert embedder.dimension == 1536

    def test_custom_model(self):
        embedder = OpenAIEmbedder(
            api_key="fake-key",
            model="text-embedding-3-large",
            dimension=3072,
        )
        assert embedder.model == "text-embedding-3-large"
        assert embedder.dimension == 3072

    def test_is_embedder_subclass(self):
        assert issubclass(OpenAIEmbedder, Embedder)

    async def test_embed_one(self):
        embedder = OpenAIEmbedder(api_key="fake-key")
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
        embedder._client.embeddings.create = AsyncMock(return_value=mock_response)

        result = await embedder.embed_one("test text")
        assert isinstance(result, np.ndarray)
        assert result.shape == (1536,)

    async def test_embed_batch(self):
        embedder = OpenAIEmbedder(api_key="fake-key")
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[0.1] * 1536),
            MagicMock(embedding=[0.2] * 1536),
        ]
        embedder._client.embeddings.create = AsyncMock(return_value=mock_response)

        results = await embedder.embed_batch(["text1", "text2"], batch_size=10)
        assert len(results) == 2
        assert all(isinstance(r, np.ndarray) for r in results)

    async def test_embed_batch_chunking(self):
        embedder = OpenAIEmbedder(api_key="fake-key")
        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            texts = kwargs["input"]
            mock_resp = MagicMock()
            mock_resp.data = [MagicMock(embedding=[0.1] * 1536) for _ in texts]
            return mock_resp

        embedder._client.embeddings.create = mock_create

        results = await embedder.embed_batch(["t"] * 5, batch_size=2)
        assert len(results) == 5
        assert call_count == 3  # ceil(5/2) = 3 batches


class TestOpenAIEmbedderErrors:
    """Cover lines 30-32 and 45-47: error paths in embed_one and embed_batch."""

    async def test_embed_one_raises_on_api_error(self):
        """embed_one should log and re-raise when OpenAI API fails."""
        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._client.embeddings.create = AsyncMock(
            side_effect=RuntimeError("API rate limit exceeded")
        )

        with pytest.raises(RuntimeError, match="API rate limit exceeded"):
            await embedder.embed_one("test text")

    async def test_embed_batch_raises_on_api_error(self):
        """embed_batch should log and re-raise when OpenAI API fails."""
        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._client.embeddings.create = AsyncMock(
            side_effect=ConnectionError("network timeout")
        )

        with pytest.raises(ConnectionError, match="network timeout"):
            await embedder.embed_batch(["text1", "text2"], batch_size=10)

    async def test_embed_batch_raises_on_second_batch(self):
        """embed_batch should raise if a later batch fails (not just the first)."""
        embedder = OpenAIEmbedder(api_key="fake-key")
        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("second batch failed")
            mock_resp = MagicMock()
            mock_resp.data = [MagicMock(embedding=[0.1] * 1536) for _ in kwargs["input"]]
            return mock_resp

        embedder._client.embeddings.create = mock_create

        with pytest.raises(RuntimeError, match="second batch failed"):
            await embedder.embed_batch(["a", "b", "c"], batch_size=2)
