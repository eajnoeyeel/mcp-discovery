"""Unit tests covering error paths in src/embedding/fastembed_sparse.py (lines 28-30, 41-43)."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from mcp_discovery.embedding.sparse_embedder import SparseVector


def _make_sparse_result(indices: list[int], values: list[float]) -> MagicMock:
    result = MagicMock()
    result.indices = np.array(indices)
    result.values = np.array(values)
    return result


class TestFastEmbedSparseEmbedder:
    def _make_embedder(self, model_mock: MagicMock | None = None):
        """Create a FastEmbedSparseEmbedder with a mocked underlying model."""
        from mcp_discovery.embedding.fastembed_sparse import FastEmbedSparseEmbedder

        with patch("mcp_discovery.embedding.fastembed_sparse.SparseTextEmbedding") as mock_model:
            if model_mock is not None:
                mock_model.return_value = model_mock
            else:
                mock_model.return_value = MagicMock()
            embedder = FastEmbedSparseEmbedder()
        return embedder

    def test_embed_one_raises_on_model_failure(self):
        """embed_one re-raises when the underlying model fails (lines 28-30)."""
        model_mock = MagicMock()
        model_mock.embed.side_effect = RuntimeError("model load failed")
        embedder = self._make_embedder(model_mock)

        with pytest.raises(RuntimeError, match="model load failed"):
            embedder.embed_one("test text")

    def test_embed_one_does_not_swallow_exception(self):
        """embed_one must propagate all exceptions."""
        model_mock = MagicMock()
        model_mock.embed.side_effect = ValueError("bad input")
        embedder = self._make_embedder(model_mock)

        with pytest.raises(ValueError):
            embedder.embed_one("text")

    def test_embed_one_returns_sparse_vector_on_success(self):
        """embed_one wraps model output in SparseVector correctly."""
        sparse_result = _make_sparse_result([0, 5, 10], [0.9, 0.7, 0.5])
        model_mock = MagicMock()
        model_mock.embed.return_value = iter([sparse_result])
        embedder = self._make_embedder(model_mock)

        result = embedder.embed_one("test text")
        assert isinstance(result, SparseVector)
        assert result.indices == [0, 5, 10]
        assert result.values == [0.9, 0.7, 0.5]

    def test_embed_one_calls_model_with_list_input(self):
        """embed_one wraps single text in a list before calling model.embed."""
        sparse_result = _make_sparse_result([1], [0.8])
        model_mock = MagicMock()
        model_mock.embed.return_value = iter([sparse_result])
        embedder = self._make_embedder(model_mock)

        embedder.embed_one("my text")
        model_mock.embed.assert_called_once_with(["my text"])

    def test_embed_batch_raises_on_model_failure(self):
        """embed_batch re-raises when the underlying model fails (lines 41-43)."""
        model_mock = MagicMock()
        model_mock.embed.side_effect = Exception("batch embed error")
        embedder = self._make_embedder(model_mock)

        with pytest.raises(Exception, match="batch embed error"):
            embedder.embed_batch(["text1", "text2"])

    def test_embed_batch_does_not_swallow_exception(self):
        """embed_batch must propagate all exceptions."""
        model_mock = MagicMock()
        model_mock.embed.side_effect = MemoryError("OOM")
        embedder = self._make_embedder(model_mock)

        with pytest.raises(MemoryError):
            embedder.embed_batch(["t1"])

    def test_embed_batch_returns_list_of_sparse_vectors(self):
        """embed_batch converts all results to SparseVector."""
        results = [
            _make_sparse_result([0, 3], [0.9, 0.4]),
            _make_sparse_result([1, 7], [0.8, 0.6]),
        ]
        model_mock = MagicMock()
        model_mock.embed.return_value = iter(results)
        embedder = self._make_embedder(model_mock)

        batch = embedder.embed_batch(["text1", "text2"])
        assert len(batch) == 2
        assert all(isinstance(v, SparseVector) for v in batch)
        assert batch[0].indices == [0, 3]
        assert batch[1].values == [0.8, 0.6]

    def test_embed_batch_empty_input_calls_model_with_empty_list(self):
        """embed_batch with empty list still calls model.embed([])."""
        model_mock = MagicMock()
        model_mock.embed.return_value = iter([])
        embedder = self._make_embedder(model_mock)

        result = embedder.embed_batch([])
        assert result == []
        model_mock.embed.assert_called_once_with([])

    def test_default_model_name(self):
        """FastEmbedSparseEmbedder uses the SPLADE default model name."""
        from mcp_discovery.embedding.fastembed_sparse import _DEFAULT_MODEL, FastEmbedSparseEmbedder

        with patch("mcp_discovery.embedding.fastembed_sparse.SparseTextEmbedding") as mock_model:
            mock_model.return_value = MagicMock()
            embedder = FastEmbedSparseEmbedder()
        assert embedder.model == _DEFAULT_MODEL

    def test_custom_model_name(self):
        """FastEmbedSparseEmbedder accepts a custom model name."""
        from mcp_discovery.embedding.fastembed_sparse import FastEmbedSparseEmbedder

        with patch("mcp_discovery.embedding.fastembed_sparse.SparseTextEmbedding") as mock_model:
            mock_model.return_value = MagicMock()
            embedder = FastEmbedSparseEmbedder(model="custom/model")
        assert embedder.model == "custom/model"
