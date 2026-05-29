"""PipelineStrategy ABC and StrategyRegistry."""

from abc import ABC, abstractmethod

from mcp_discovery.models import SearchResult


class PipelineStrategy(ABC):
    """Abstract base class for all retrieval pipeline strategies.

    Implementations: FlatStrategy (1-Layer), SequentialStrategy (2-Layer),
    ParallelStrategy (RRF fusion).
    All concrete strategies must be registered via StrategyRegistry.
    """

    @abstractmethod
    async def search(self, query: str, top_k: int) -> list[SearchResult]:
        """Execute the retrieval pipeline for a query.

        Args:
            query: Natural language query from the LLM client.
            top_k: Number of results to return.

        Returns:
            Ranked list of SearchResult, highest score first.
        """


class StrategyRegistry:
    """Maps strategy names to PipelineStrategy subclasses.

    Usage:
        @StrategyRegistry.register("sequential")
        class SequentialStrategy(PipelineStrategy):
            ...

        StrategyClass = StrategyRegistry.get("sequential")
        strategy = StrategyClass(embedder=..., tool_store=...)
    """

    _registry: dict[str, type[PipelineStrategy]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator: register a PipelineStrategy subclass under name."""

        def decorator(klass: type[PipelineStrategy]) -> type[PipelineStrategy]:
            if name in cls._registry:
                raise ValueError(f"Strategy '{name}' is already registered.")
            cls._registry[name] = klass
            return klass

        return decorator

    @classmethod
    def get(cls, name: str) -> type[PipelineStrategy]:
        """Return the registered strategy class for name.

        Raises:
            ValueError: if name is not registered.
        """
        if name not in cls._registry:
            available = sorted(cls._registry)
            raise ValueError(f"Unknown strategy '{name}'. Available: {available}")
        return cls._registry[name]

    @classmethod
    def list_strategies(cls) -> list[str]:
        """Return all registered strategy names."""
        return list(cls._registry.keys())
