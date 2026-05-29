"""Integration tests for OpenAIEmbedder — runs against real OpenAI API."""

import os

import numpy as np
import pytest

from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="requires OPENAI_API_KEY",
)


@pytest.fixture
def embedder():
    return OpenAIEmbedder(api_key=os.environ["OPENAI_API_KEY"])


class TestEmbedOne:
    async def test_returns_numpy_array(self, embedder):
        result = await embedder.embed_one("hello world")
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32

    async def test_returns_correct_dimension(self, embedder):
        result = await embedder.embed_one("test query")
        assert result.shape == (1536,)

    async def test_different_texts_give_different_vectors(self, embedder):
        v1 = await embedder.embed_one("search GitHub issues")
        v2 = await embedder.embed_one("cook pasta recipe")
        # Cosine similarity should be low for unrelated texts
        similarity = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
        assert similarity < 0.9  # not identical


class TestEmbedBatch:
    async def test_returns_list_of_arrays(self, embedder):
        texts = ["hello", "world", "test"]
        results = await embedder.embed_batch(texts)
        assert len(results) == 3
        assert all(isinstance(v, np.ndarray) for v in results)

    async def test_batch_matches_individual(self, embedder):
        texts = ["search issues", "create PR"]
        batch_results = await embedder.embed_batch(texts)
        individual_results = [await embedder.embed_one(t) for t in texts]

        for batch_v, indiv_v in zip(batch_results, individual_results):
            # OpenAI API is non-deterministic across calls; verify vectors
            # are functionally equivalent via high cosine similarity
            similarity = np.dot(batch_v, indiv_v) / (
                np.linalg.norm(batch_v) * np.linalg.norm(indiv_v)
            )
            assert similarity > 0.999
