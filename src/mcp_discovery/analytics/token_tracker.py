"""Token usage tracker — per-call cost logging for LLM generation pipelines."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, computed_field


class TokenUsageEntry(BaseModel):
    """A single LLM API call's token usage."""

    operation: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    input_cost_per_1m: float
    output_cost_per_1m: float
    tool_id: str | None = None

    @computed_field
    @property
    def cost_usd(self) -> float:
        return (
            self.prompt_tokens * self.input_cost_per_1m / 1_000_000
            + self.completion_tokens * self.output_cost_per_1m / 1_000_000
        )


class TokenTracker:
    """Append token usage entries to a JSONL file and provide summaries."""

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path
        self._entries: list[TokenUsageEntry] = []

    def record(self, entry: TokenUsageEntry) -> None:
        """Record a token usage entry (in-memory + disk)."""
        self._entries.append(entry)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def summary(self) -> dict:
        """Return aggregate summary of all recorded entries."""
        if not self._entries:
            return {"total_calls": 0, "total_tokens": 0, "total_cost_usd": 0.0}
        return {
            "total_calls": len(self._entries),
            "total_tokens": sum(e.total_tokens for e in self._entries),
            "total_cost_usd": sum(e.cost_usd for e in self._entries),
            "by_model": self._group_by_model(),
        }

    def _group_by_model(self) -> dict[str, dict]:
        groups: dict[str, list[TokenUsageEntry]] = {}
        for e in self._entries:
            groups.setdefault(e.model, []).append(e)
        return {
            model: {
                "calls": len(entries),
                "tokens": sum(e.total_tokens for e in entries),
                "cost_usd": sum(e.cost_usd for e in entries),
            }
            for model, entries in groups.items()
        }
