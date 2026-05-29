"""Pipeline strategies for MCP Discovery Platform."""

from mcp_discovery.pipeline.confidence import compute_confidence
from mcp_discovery.pipeline.flat import FlatStrategy
from mcp_discovery.pipeline.parallel import ParallelStrategy
from mcp_discovery.pipeline.sequential import SequentialStrategy
from mcp_discovery.pipeline.strategy import PipelineStrategy, StrategyRegistry

__all__ = [
    "PipelineStrategy",
    "StrategyRegistry",
    "compute_confidence",
    "FlatStrategy",
    "ParallelStrategy",
    "SequentialStrategy",
]
