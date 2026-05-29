"""Tests for PipelineStrategy ABC and StrategyRegistry."""

import pytest

from mcp_discovery.models import MCPTool, SearchResult
from mcp_discovery.pipeline.strategy import PipelineStrategy, StrategyRegistry


def make_tool(server_id: str = "srv", tool_name: str = "tool") -> MCPTool:
    return MCPTool(
        server_id=server_id,
        tool_name=tool_name,
        tool_id=f"{server_id}::{tool_name}",
    )


class ConcreteStrategy(PipelineStrategy):
    async def search(self, query: str, top_k: int) -> list[SearchResult]:
        return [SearchResult(tool=make_tool(), score=0.9, rank=1)]


class TestPipelineStrategyABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            PipelineStrategy()

    async def test_concrete_strategy_search(self):
        strategy = ConcreteStrategy()
        results = await strategy.search("test", top_k=3)
        assert len(results) == 1
        assert results[0].score == 0.9


class TestStrategyRegistry:
    def setup_method(self):
        self._original = StrategyRegistry._registry.copy()

    def teardown_method(self):
        StrategyRegistry._registry.clear()
        StrategyRegistry._registry.update(self._original)

    def test_register_and_get(self):
        @StrategyRegistry.register("test_strat")
        class TestStrat(PipelineStrategy):
            async def search(self, query: str, top_k: int) -> list[SearchResult]:
                return []

        assert StrategyRegistry.get("test_strat") is TestStrat

    def test_get_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            StrategyRegistry.get("nonexistent_xyz_abc")

    def test_list_strategies_includes_registered(self):
        @StrategyRegistry.register("test_list_strat")
        class ListStrat(PipelineStrategy):
            async def search(self, query: str, top_k: int) -> list[SearchResult]:
                return []

        assert "test_list_strat" in StrategyRegistry.list_strategies()

    def test_register_decorator_returns_class_unchanged(self):
        @StrategyRegistry.register("test_decorator")
        class DecoratorStrat(PipelineStrategy):
            async def search(self, query: str, top_k: int) -> list[SearchResult]:
                return []

        assert DecoratorStrat.__name__ == "DecoratorStrat"

    def test_register_duplicate_raises_value_error(self):
        @StrategyRegistry.register("dup_strat")
        class DupStrat(PipelineStrategy):
            async def search(self, query: str, top_k: int) -> list[SearchResult]:
                return []

        with pytest.raises(ValueError, match="already registered"):

            @StrategyRegistry.register("dup_strat")
            class DupStrat2(PipelineStrategy):
                async def search(self, query: str, top_k: int) -> list[SearchResult]:
                    return []
