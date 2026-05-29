"""Evaluator ABC — abstract base class for evaluation strategies.

Concrete implementations define how a pipeline strategy is evaluated
against ground truth queries. Business logic depends on this ABC only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mcp_discovery.evaluation.metrics import EvalResult
from mcp_discovery.models import GroundTruthEntry
from mcp_discovery.pipeline.strategy import PipelineStrategy


class Evaluator(ABC):
    """Abstract base class for evaluation strategies.

    Implementations define the evaluation loop: how queries are dispatched,
    how per-query results are collected, and how aggregate metrics are computed.
    """

    @abstractmethod
    async def evaluate(
        self,
        strategy: PipelineStrategy,
        queries: list[GroundTruthEntry],
        top_k: int = 10,
    ) -> EvalResult:
        """Run strategy against ground truth queries and return aggregated metrics.

        Args:
            strategy: Pipeline strategy to evaluate.
            queries: Ground truth entries to evaluate against.
            top_k: Number of results to retrieve per query.

        Returns:
            EvalResult with all metrics computed over the query set.
        """
