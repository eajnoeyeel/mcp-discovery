"""Log aggregator — per-tool statistics from query logs."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, computed_field

from mcp_discovery.analytics.logger import QueryLogEntry, QueryLogger


class ToolStats(BaseModel):
    """Aggregated statistics for a single tool."""

    tool_id: str
    selection_count: int = 0
    runner_up_count: int = 0
    lost_to: dict[str, int] = Field(default_factory=dict)

    @computed_field
    @property
    def win_rate(self) -> float:
        total = self.selection_count + self.runner_up_count
        if total == 0:
            return 0.0
        return self.selection_count / total


class LogAggregator:
    """Build per-tool :class:`ToolStats` from query log entries."""

    def __init__(self, log_dir: Path) -> None:
        self._logger = QueryLogger(log_dir=log_dir)

    async def aggregate(
        self,
        days: int | None = None,
        server_id: str | None = None,
    ) -> dict[str, ToolStats]:
        entries = await self._logger.read_logs(days=days)
        if server_id is not None:
            entries = [e for e in entries if e.server_id == server_id]
        return self._build_stats(entries)

    @staticmethod
    def _build_stats(entries: list[QueryLogEntry]) -> dict[str, ToolStats]:
        selections: dict[str, int] = {}
        runner_ups: dict[str, int] = {}
        lost_to: dict[str, dict[str, int]] = {}

        for entry in entries:
            winner = entry.recommended_tool_id
            selections[winner] = selections.get(winner, 0) + 1

            for alt in entry.alternatives:
                runner_ups[alt] = runner_ups.get(alt, 0) + 1
                tool_lost = lost_to.setdefault(alt, {})
                tool_lost[winner] = tool_lost.get(winner, 0) + 1

        all_tools = set(selections) | set(runner_ups)
        return {
            tool_id: ToolStats(
                tool_id=tool_id,
                selection_count=selections.get(tool_id, 0),
                runner_up_count=runner_ups.get(tool_id, 0),
                lost_to=lost_to.get(tool_id, {}),
            )
            for tool_id in all_tools
        }
