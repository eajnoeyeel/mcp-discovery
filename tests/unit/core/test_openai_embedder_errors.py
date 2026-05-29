"""Unit tests covering error paths in src/embedding/openai_embedder.py (lines 30-32, 45-47)."""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder


class TestOpenAIEmbedderErrorPaths:
    async def test_embed_one_raises_on_api_failure(self):
        """embed_one re-raises when OpenAI call fails (line 30-32)."""
        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._client.embeddings.create = AsyncMock(side_effect=Exception("openai api error"))
        with pytest.raises(Exception, match="openai api error"):
            await embedder.embed_one("test text")

    async def test_embed_one_does_not_swallow_exception(self):
        """embed_one must propagate, not swallow, any exception."""
        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._client.embeddings.create = AsyncMock(side_effect=RuntimeError("timeout"))
        with pytest.raises(RuntimeError):
            await embedder.embed_one("any text")

    async def test_embed_batch_raises_on_api_failure(self):
        """embed_batch re-raises when OpenAI call fails mid-batch (lines 45-47)."""
        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._client.embeddings.create = AsyncMock(side_effect=Exception("batch api error"))
        with pytest.raises(Exception, match="batch api error"):
            await embedder.embed_batch(["text1", "text2"])

    async def test_embed_batch_raises_on_second_batch_failure(self):
        """embed_batch raises if a later batch (not the first) fails."""
        embedder = OpenAIEmbedder(api_key="fake-key")
        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First batch succeeds
                resp = MagicMock()
                resp.data = [MagicMock(embedding=[0.1] * 1536) for _ in kwargs["input"]]
                return resp
            raise Exception("second batch failed")

        embedder._client.embeddings.create = mock_create

        with pytest.raises(Exception, match="second batch failed"):
            await embedder.embed_batch(["t1", "t2", "t3"], batch_size=1)

    async def test_embed_one_returns_float32_array(self):
        """Verify dtype is float32 on success path (regression guard)."""
        embedder = OpenAIEmbedder(api_key="fake-key")
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.5] * 1536)]
        embedder._client.embeddings.create = AsyncMock(return_value=mock_response)
        result = await embedder.embed_one("text")
        assert result.dtype == np.float32

    async def test_embed_batch_empty_input_returns_empty_list(self):
        """embed_batch with empty input list returns empty list without API call."""
        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._client.embeddings.create = AsyncMock()
        result = await embedder.embed_batch([])
        assert result == []
        embedder._client.embeddings.create.assert_not_awaited()

    async def test_embed_batch_passes_correct_model_and_dimension(self):
        """embed_batch sends the configured model and dimension parameters."""
        embedder = OpenAIEmbedder(
            api_key="fake-key",
            model="text-embedding-3-large",
            dimension=3072,
        )
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 3072)]
        embedder._client.embeddings.create = AsyncMock(return_value=mock_response)

        await embedder.embed_batch(["text"], batch_size=50)
        call_kwargs = embedder._client.embeddings.create.call_args[1]
        assert call_kwargs["model"] == "text-embedding-3-large"
        assert call_kwargs["dimensions"] == 3072
