"""Confusion matrix builder — per-tool selection/runner-up summary."""

from __future__ import annotations

from pydantic import BaseModel

from mcp_discovery.analytics.aggregator import ToolStats


class ConfusionEntry(BaseModel):
    """One row of the confusion matrix."""

    tool_id: str
    selections: int
    runner_up: int
    win_rate: float
    lost_to_top5: list[tuple[str, int]]


def build_confusion_matrix(
    stats: dict[str, ToolStats],
) -> list[ConfusionEntry]:
    """Build a confusion matrix sorted by selection count (descending).

    ``lost_to_top5`` contains up to 5 tools this tool most frequently lost to.
    """
    if not stats:
        return []

    entries: list[ConfusionEntry] = []
    for tool_stats in stats.values():
        sorted_lost = sorted(
            tool_stats.lost_to.items(),
            key=lambda pair: pair[1],
            reverse=True,
        )[:5]

        entries.append(
            ConfusionEntry(
                tool_id=tool_stats.tool_id,
                selections=tool_stats.selection_count,
                runner_up=tool_stats.runner_up_count,
                win_rate=tool_stats.win_rate,
                lost_to_top5=sorted_lost,
            )
        )

    entries.sort(key=lambda e: e.selections, reverse=True)
    return entries
