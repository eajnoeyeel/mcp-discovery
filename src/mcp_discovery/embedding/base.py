"""Abstract base class for embedding providers."""

from abc import ABC, abstractmethod

import numpy as np


class Embedder(ABC):
    """ABC for text embedding. All implementations must be async."""

    model: str
    dimension: int

    @abstractmethod
    async def embed_one(self, text: str) -> np.ndarray:
        """Embed a single text string."""

    @abstractmethod
    async def embed_batch(self, texts: list[str], batch_size: int = 50) -> list[np.ndarray]:
        """Embed a batch of texts, chunked by batch_size."""
