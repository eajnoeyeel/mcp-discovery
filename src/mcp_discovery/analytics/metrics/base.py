"""ProviderMetric ABC — pluggable analytics dimensions.

New metrics: subclass ProviderMetric, implement compute(), register via decorator.
Pattern follows PipelineStrategy ABC + StrategyRegistry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from mcp_discovery.analytics.logger import QueryLogEntry


class MetricContext(BaseModel):
    """Shared context passed to all metric compute() calls."""

    tool_id: str
    server_id: str
    logs: list[QueryLogEntry] = Field(default_factory=list)
    raw_description: str | None = None
    enriched_text: str | None = None
    input_schema: dict | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MetricResult(BaseModel):
    """Output of a single metric computation."""

    metric_name: str
    value: dict[str, Any]


class ProviderMetric(ABC):
    """Abstract base for provider analytics metrics."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique metric identifier."""

    @abstractmethod
    def compute(self, context: MetricContext) -> MetricResult:
        """Compute this metric for a given tool."""


class MetricRegistry:
    """Registry for ProviderMetric plugins. Instance-based for testability."""

    def __init__(self) -> None:
        self._registry: dict[str, type[ProviderMetric]] = {}

    def register(self, name: str):
        """Decorator: register a ProviderMetric subclass under name."""

        def decorator(klass: type[ProviderMetric]) -> type[ProviderMetric]:
            if name in self._registry:
                raise ValueError(f"Metric '{name}' is already registered.")
            self._registry[name] = klass
            return klass

        return decorator

    def get(self, name: str) -> type[ProviderMetric]:
        """Return registered metric class. Raises ValueError if not found."""
        if name not in self._registry:
            available = sorted(self._registry)
            raise ValueError(f"Unknown metric '{name}'. Available: {available}")
        return self._registry[name]

    def list_metrics(self) -> list[str]:
        """Return all registered metric names."""
        return list(self._registry.keys())
