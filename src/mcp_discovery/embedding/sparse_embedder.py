"""Abstract base class for sparse embedding providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SparseVector:
    """Immutable sparse vector representation (indices + values)."""

    indices: list[int]
    values: list[float]


class SparseEmbedder(ABC):
    """ABC for sparse text embedding. Implementations are sync (CPU-only)."""

    model: str

    @abstractmethod
    def embed_one(self, text: str) -> SparseVector:
        """Embed a single text string into a sparse vector."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[SparseVector]:
        """Embed a list of texts into sparse vectors."""
