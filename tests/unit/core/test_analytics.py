"""Tests for QueryLogger and LogAggregator (Phase 9 — Task 9.1)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcp_discovery.analytics.aggregator import LogAggregator, ToolStats
from mcp_discovery.analytics.logger import QueryLogEntry, QueryLogger

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture()
def logger(log_dir: Path) -> QueryLogger:
    return QueryLogger(log_dir=log_dir)


def _make_entry(**overrides: object) -> QueryLogEntry:
    defaults: dict = {
        "query": "find a tool for searching papers",
        "selected_tool_id": "arxiv::search_papers",
        "server_id": "arxiv",
        "confidence": 0.85,
        "disambiguation_needed": False,
        "strategy": "sequential",
        "latency_ms": 120.5,
        "alternatives": ["semantic-scholar::search", "google-scholar::search"],
    }
    defaults.update(overrides)
    return QueryLogEntry(**defaults)


# ===========================================================================
# QueryLogEntry model
# ===========================================================================


class TestQueryLogEntry:
    def test_required_fields(self) -> None:
        entry = _make_entry()
        assert entry.query == "find a tool for searching papers"
        assert entry.recommended_tool_id == "arxiv::search_papers"
        assert entry.server_id == "arxiv"
        assert entry.confidence == 0.85
        assert entry.disambiguation_needed is False
        assert entry.strategy == "sequential"
        assert entry.latency_ms == 120.5
        assert entry.alternatives == ["semantic-scholar::search", "google-scholar::search"]

    def test_timestamp_auto_set(self) -> None:
        entry = _make_entry()
        assert entry.timestamp is not None
        dt = datetime.fromisoformat(entry.timestamp)
        assert dt.tzinfo is not None

    def test_serialization_roundtrip(self) -> None:
        entry = _make_entry()
        data = json.loads(entry.model_dump_json())
        restored = QueryLogEntry(**data)
        assert restored == entry

    def test_candidates_field(self) -> None:
        entry = _make_entry(
            candidates=[
                {
                    "tool_id": "arxiv::search",
                    "score": 0.85,
                    "dense_score": 0.80,
                    "sparse_score": 0.90,
                },
                {
                    "tool_id": "scholar::search",
                    "score": 0.72,
                    "dense_score": 0.75,
                    "sparse_score": 0.68,
                },
            ]
        )
        assert len(entry.candidates) == 2
        assert entry.candidates[0].tool_id == "arxiv::search"
        assert entry.candidates[0].dense_score == 0.80

    def test_candidates_default_empty(self) -> None:
        entry = _make_entry()
        assert entry.candidates == []

    def test_alias_backward_compat(self) -> None:
        """selected_tool_id alias must be accepted as input field name."""
        entry = QueryLogEntry.model_validate(
            {
                "query": "find papers",
                "selected_tool_id": "arxiv::search_papers",
                "server_id": "arxiv",
                "confidence": 0.9,
                "disambiguation_needed": False,
                "strategy": "flat",
                "latency_ms": 100.0,
            }
        )
        assert entry.recommended_tool_id == "arxiv::search_papers"

    def test_serialization_with_candidates(self) -> None:
        entry = _make_entry(
            candidates=[
                {"tool_id": "A", "score": 0.9, "dense_score": 0.8, "sparse_score": 0.7},
            ]
        )
        data = json.loads(entry.model_dump_json())
        restored = QueryLogEntry(**data)
        assert len(restored.candidates) == 1
        assert restored.candidates[0].tool_id == "A"


# ===========================================================================
# QueryLogger (async)
# ===========================================================================


class TestQueryLogger:
    async def test_creates_log_dir(self, logger: QueryLogger, log_dir: Path) -> None:
        assert not log_dir.exists()
        await logger.log(_make_entry())
        assert log_dir.exists()

    async def test_daily_file_naming(self, logger: QueryLogger, log_dir: Path) -> None:
        await logger.log(_make_entry())
        today = datetime.now(timezone.utc).date().isoformat()
        expected_file = log_dir / f"queries-{today}.jsonl"
        assert expected_file.exists()

    async def test_appends_jsonl(self, logger: QueryLogger, log_dir: Path) -> None:
        await logger.log(_make_entry(query="q1"))
        await logger.log(_make_entry(query="q2"))
        await logger.log(_make_entry(query="q3"))

        today = datetime.now(timezone.utc).date().isoformat()
        lines = (log_dir / f"queries-{today}.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3

        parsed = [json.loads(line) for line in lines]
        assert parsed[0]["query"] == "q1"
        assert parsed[2]["query"] == "q3"

    async def test_each_line_is_valid_json(self, logger: QueryLogger, log_dir: Path) -> None:
        await logger.log(_make_entry())
        today = datetime.now(timezone.utc).date().isoformat()
        line = (log_dir / f"queries-{today}.jsonl").read_text().strip()
        data = json.loads(line)
        assert "timestamp" in data
        assert "query" in data
        assert "recommended_tool_id" in data
        assert "server_id" in data
        assert "confidence" in data
        assert "disambiguation_needed" in data
        assert "strategy" in data
        assert "latency_ms" in data
        assert "alternatives" in data

    async def test_log_returns_entry(self, logger: QueryLogger) -> None:
        entry = _make_entry()
        result = await logger.log(entry)
        assert result == entry

    async def test_read_logs_returns_entries(self, logger: QueryLogger) -> None:
        await logger.log(_make_entry(query="q1"))
        await logger.log(_make_entry(query="q2"))

        entries = await logger.read_logs()
        assert len(entries) == 2
        assert entries[0].query == "q1"
        assert entries[1].query == "q2"

    async def test_read_logs_empty_dir(self, log_dir: Path) -> None:
        fresh_logger = QueryLogger(log_dir=log_dir)
        entries = await fresh_logger.read_logs()
        assert entries == []

    async def test_read_logs_date_filter(self, logger: QueryLogger) -> None:
        await logger.log(_make_entry(query="today"))
        entries = await logger.read_logs(days=1)
        assert len(entries) == 1

    async def test_read_logs_skips_malformed_line(self, logger: QueryLogger, log_dir: Path) -> None:
        await logger.log(_make_entry(query="good"))
        today = datetime.now(timezone.utc).date().isoformat()
        path = log_dir / f"queries-{today}.jsonl"
        with path.open("a") as f:
            f.write("{bad json}\n")
        await logger.log(_make_entry(query="also_good"))

        entries = await logger.read_logs()
        assert len(entries) == 2
        assert entries[0].query == "good"
        assert entries[1].query == "also_good"


# ===========================================================================
# LogAggregator + ToolStats
# ===========================================================================


class TestToolStats:
    def test_default_values(self) -> None:
        stats = ToolStats(tool_id="arxiv::search_papers")
        assert stats.tool_id == "arxiv::search_papers"
        assert stats.selection_count == 0
        assert stats.runner_up_count == 0
        assert stats.lost_to == {}

    def test_win_rate_no_selections(self) -> None:
        stats = ToolStats(tool_id="t1")
        assert stats.win_rate == 0.0

    def test_win_rate_calculation(self) -> None:
        stats = ToolStats(
            tool_id="t1",
            selection_count=3,
            runner_up_count=7,
        )
        assert stats.win_rate == pytest.approx(0.3)


class TestLogAggregator:
    async def test_aggregate_empty(self, log_dir: Path) -> None:
        aggregator = LogAggregator(log_dir=log_dir)
        result = await aggregator.aggregate()
        assert result == {}

    async def test_aggregate_single_entry(self, log_dir: Path) -> None:
        qlogger = QueryLogger(log_dir=log_dir)
        await qlogger.log(
            _make_entry(
                selected_tool_id="arxiv::search",
                alternatives=["scholar::search"],
            )
        )

        aggregator = LogAggregator(log_dir=log_dir)
        result = await aggregator.aggregate()

        assert "arxiv::search" in result
        assert result["arxiv::search"].selection_count == 1

        assert "scholar::search" in result
        assert result["scholar::search"].runner_up_count == 1
        assert result["scholar::search"].lost_to == {"arxiv::search": 1}

    async def test_aggregate_multiple_entries(self, log_dir: Path) -> None:
        qlogger = QueryLogger(log_dir=log_dir)
        await qlogger.log(_make_entry(selected_tool_id="A", alternatives=["B", "C"]))
        await qlogger.log(_make_entry(selected_tool_id="A", alternatives=["B"]))
        await qlogger.log(_make_entry(selected_tool_id="B", alternatives=["A"]))

        aggregator = LogAggregator(log_dir=log_dir)
        result = await aggregator.aggregate()

        assert result["A"].selection_count == 2
        assert result["A"].runner_up_count == 1
        assert result["A"].lost_to == {"B": 1}

        assert result["B"].selection_count == 1
        assert result["B"].runner_up_count == 2
        assert result["B"].lost_to == {"A": 2}

    async def test_aggregate_days_filter(self, log_dir: Path) -> None:
        qlogger = QueryLogger(log_dir=log_dir)
        await qlogger.log(_make_entry(selected_tool_id="A", alternatives=[]))

        aggregator = LogAggregator(log_dir=log_dir)
        result = await aggregator.aggregate(days=7)
        assert "A" in result

    async def test_aggregate_by_server(self, log_dir: Path) -> None:
        qlogger = QueryLogger(log_dir=log_dir)
        await qlogger.log(
            _make_entry(selected_tool_id="arxiv::s", server_id="arxiv", alternatives=[])
        )
        await qlogger.log(_make_entry(selected_tool_id="gh::s", server_id="gh", alternatives=[]))

        aggregator = LogAggregator(log_dir=log_dir)
        result = await aggregator.aggregate(server_id="arxiv")
        assert "arxiv::s" in result
        assert "gh::s" not in result
