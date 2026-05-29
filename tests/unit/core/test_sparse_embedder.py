"""Tests for SparseEmbedder ABC and FastEmbedSparseEmbedder implementation."""

from unittest.mock import MagicMock, patch

import pytest

from mcp_discovery.embedding.fastembed_sparse import FastEmbedSparseEmbedder
from mcp_discovery.embedding.sparse_embedder import SparseEmbedder, SparseVector


class _ArrayLike(list):
    def tolist(self) -> list:
        return list(self)


def _make_sparse_result(indices: list[int], values: list[float]) -> MagicMock:
    result = MagicMock()
    result.indices = _ArrayLike(indices)
    result.values = _ArrayLike(values)
    return result


def _make_embedder_with_results(*results: MagicMock) -> FastEmbedSparseEmbedder:
    model = MagicMock()
    model.embed.return_value = iter(results)
    with patch("mcp_discovery.embedding.fastembed_sparse.SparseTextEmbedding", return_value=model):
        return FastEmbedSparseEmbedder()


class TestSparseVector:
    def test_frozen_dataclass(self) -> None:
        sv = SparseVector(indices=[1, 5, 10], values=[0.5, 0.3, 0.1])
        assert sv.indices == [1, 5, 10]
        with pytest.raises(AttributeError):
            sv.indices = [2]  # type: ignore[misc]

    def test_values_accessible(self) -> None:
        sv = SparseVector(indices=[0, 3], values=[1.0, 0.7])
        assert sv.values == [1.0, 0.7]

    def test_empty_sparse_vector(self) -> None:
        sv = SparseVector(indices=[], values=[])
        assert sv.indices == []
        assert sv.values == []


class TestSparseEmbedderABC:
    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            SparseEmbedder()  # type: ignore[abstract]


class TestFastEmbedSparseEmbedder:
    def test_embed_one_returns_sparse_vector(self) -> None:
        embedder = _make_embedder_with_results(_make_sparse_result([1, 5], [0.9, 0.4]))
        result = embedder.embed_one("search GitHub repositories")
        assert isinstance(result, SparseVector)
        assert len(result.indices) > 0
        assert len(result.indices) == len(result.values)

    def test_embed_one_values_are_floats(self) -> None:
        embedder = _make_embedder_with_results(_make_sparse_result([2, 8], [0.8, 0.3]))
        result = embedder.embed_one("list files in directory")
        assert all(isinstance(v, float) for v in result.values)
        assert all(isinstance(i, int) for i in result.indices)

    def test_embed_batch(self) -> None:
        embedder = _make_embedder_with_results(
            _make_sparse_result([1], [0.9]),
            _make_sparse_result([2], [0.7]),
        )
        results = embedder.embed_batch(["search repos", "list bases"])
        assert len(results) == 2
        assert all(isinstance(r, SparseVector) for r in results)

    def test_embed_batch_each_has_indices(self) -> None:
        embedder = _make_embedder_with_results(
            _make_sparse_result([1, 4], [0.9, 0.2]),
            _make_sparse_result([2, 6], [0.7, 0.5]),
        )
        results = embedder.embed_batch(["create a file", "read a document"])
        for r in results:
            assert len(r.indices) > 0
            assert len(r.indices) == len(r.values)

    def test_embed_batch_single_item(self) -> None:
        embedder = _make_embedder_with_results(_make_sparse_result([7], [0.6]))
        results = embedder.embed_batch(["single query"])
        assert len(results) == 1
        assert isinstance(results[0], SparseVector)

    def test_model_name_attribute(self) -> None:
        with patch("mcp_discovery.embedding.fastembed_sparse.SparseTextEmbedding"):
            embedder = FastEmbedSparseEmbedder()
        assert hasattr(embedder, "model")
        assert "Splade" in embedder.model or "splade" in embedder.model.lower()


class TestFastEmbedSparseEmbedderInit:
    """Cover lines 28-30 and 41-43: __init__ with mock, error paths."""

    def test_init_loads_model(self) -> None:
        """Verify __init__ creates SparseTextEmbedding with the given model name."""
        with patch("mcp_discovery.embedding.fastembed_sparse.SparseTextEmbedding") as mock_cls:
            embedder = FastEmbedSparseEmbedder(model="test-model")
            mock_cls.assert_called_once_with(model_name="test-model")
            assert embedder.model == "test-model"

    def test_init_default_model(self) -> None:
        with patch("mcp_discovery.embedding.fastembed_sparse.SparseTextEmbedding") as mock_cls:
            embedder = FastEmbedSparseEmbedder()
            mock_cls.assert_called_once_with(model_name="prithivida/Splade_PP_en_v1")
            assert embedder.model == "prithivida/Splade_PP_en_v1"


class TestFastEmbedSparseEmbedderErrors:
    """Cover error paths in embed_one and embed_batch."""

    def test_embed_one_raises_on_model_error(self) -> None:
        """embed_one should log and re-raise when the underlying model fails."""
        with patch("mcp_discovery.embedding.fastembed_sparse.SparseTextEmbedding") as mock_cls:
            mock_model = MagicMock()
            mock_cls.return_value = mock_model
            embedder = FastEmbedSparseEmbedder()

            mock_model.embed.side_effect = RuntimeError("model crashed")
            with pytest.raises(RuntimeError, match="model crashed"):
                embedder.embed_one("test text")

    def test_embed_batch_raises_on_model_error(self) -> None:
        """embed_batch should log and re-raise when the underlying model fails."""
        with patch("mcp_discovery.embedding.fastembed_sparse.SparseTextEmbedding") as mock_cls:
            mock_model = MagicMock()
            mock_cls.return_value = mock_model
            embedder = FastEmbedSparseEmbedder()

            mock_model.embed.side_effect = ValueError("bad input")
            with pytest.raises(ValueError, match="bad input"):
                embedder.embed_batch(["text1", "text2"])
