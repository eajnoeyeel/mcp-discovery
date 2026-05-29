"""FastEmbed SPLADE sparse embedder implementation."""

from fastembed import SparseTextEmbedding
from loguru import logger

from mcp_discovery.embedding.sparse_embedder import SparseEmbedder, SparseVector

_DEFAULT_MODEL = "prithivida/Splade_PP_en_v1"


class FastEmbedSparseEmbedder(SparseEmbedder):
    """Sparse embedder using FastEmbed's SPLADE model.

    First instantiation downloads ~532MB model to cache.
    Subsequent uses load from cache.
    """

    def __init__(self, model: str = _DEFAULT_MODEL) -> None:
        self.model = model
        logger.info(f"Loading sparse embedding model: {model}")
        self._model = SparseTextEmbedding(model_name=model)
        logger.info(f"Sparse embedding model loaded: {model}")

    def embed_one(self, text: str) -> SparseVector:
        """Embed a single text into a sparse vector."""
        try:
            results = list(self._model.embed([text]))
        except Exception as e:
            logger.error(f"FastEmbed sparse embed_one failed: {e}")
            raise
        sparse = results[0]
        return SparseVector(
            indices=sparse.indices.tolist(),
            values=sparse.values.tolist(),
        )

    def embed_batch(self, texts: list[str]) -> list[SparseVector]:
        """Embed a batch of texts into sparse vectors."""
        try:
            results = list(self._model.embed(texts))
        except Exception as e:
            logger.error(f"FastEmbed sparse embed_batch failed: {e}")
            raise
        return [
            SparseVector(
                indices=sparse.indices.tolist(),
                values=sparse.values.tolist(),
            )
            for sparse in results
        ]
