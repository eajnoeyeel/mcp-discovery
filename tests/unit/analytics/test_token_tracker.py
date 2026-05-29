"""Tests for token usage tracker."""

import json
from pathlib import Path

from mcp_discovery.analytics.token_tracker import TokenTracker, TokenUsageEntry


class TestTokenUsageEntry:
    def test_cost_usd_calculation(self) -> None:
        entry = TokenUsageEntry(
            operation="variant_generation",
            model="gpt-4o-mini",
            prompt_tokens=500,
            completion_tokens=200,
            total_tokens=700,
            input_cost_per_1m=0.15,
            output_cost_per_1m=0.60,
        )
        # 500 * 0.15/1M + 200 * 0.60/1M = 0.000075 + 0.000120 = 0.000195
        assert abs(entry.cost_usd - 0.000195) < 1e-8


class TestTokenTracker:
    def test_record_and_summary(self, tmp_path: Path) -> None:
        tracker = TokenTracker(log_path=tmp_path / "tokens.jsonl")
        entry = TokenUsageEntry(
            operation="variant_generation",
            model="gpt-4o-mini",
            prompt_tokens=500,
            completion_tokens=200,
            total_tokens=700,
            input_cost_per_1m=0.15,
            output_cost_per_1m=0.60,
        )
        tracker.record(entry)

        summary = tracker.summary()
        assert summary["total_calls"] == 1
        assert summary["total_tokens"] == 700
        assert abs(summary["total_cost_usd"] - 0.000195) < 1e-8

    def test_persists_to_jsonl(self, tmp_path: Path) -> None:
        log_path = tmp_path / "tokens.jsonl"
        tracker = TokenTracker(log_path=log_path)
        tracker.record(
            TokenUsageEntry(
                operation="test",
                model="gpt-4o-mini",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                input_cost_per_1m=0.15,
                output_cost_per_1m=0.60,
            )
        )
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["total_tokens"] == 150

    def test_summary_empty(self, tmp_path: Path) -> None:
        tracker = TokenTracker(log_path=tmp_path / "tokens.jsonl")
        summary = tracker.summary()
        assert summary["total_calls"] == 0
        assert summary["total_tokens"] == 0
        assert summary["total_cost_usd"] == 0.0
