"""Tests for ground truth loading and utility functions."""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_discovery.data.ground_truth import (
    QualityGate,
    QualityGateError,
    load_ground_truth,
    merge_ground_truth,
    parse_queries,
    save,
    split_by_difficulty,
)
from mcp_discovery.models import Category, Difficulty, GroundTruthEntry, MCPTool


def make_entry(
    query_id: str = "gt-gen-001",
    difficulty: str = "easy",
    category: str = "general",
    ambiguity: str = "low",
    source: str = "manual_seed",
    manually_verified: bool = True,
    alternative_tools: list[str] | None = None,
) -> GroundTruthEntry:
    return GroundTruthEntry(
        query_id=query_id,
        query=f"test query {query_id}",
        correct_server_id="EthanHenrickson/math-mcp",
        correct_tool_id="EthanHenrickson/math-mcp::add",
        difficulty=difficulty,
        category=category,
        ambiguity=ambiguity,
        source=source,
        manually_verified=manually_verified,
        author="test",
        created_at="2026-03-24",
        alternative_tools=alternative_tools,
    )


def write_jsonl(entries: list[GroundTruthEntry], path: Path) -> None:
    with open(path, "w") as f:
        for e in entries:
            f.write(e.model_dump_json() + "\n")


class TestLoadGroundTruth:
    def test_loads_all_entries(self, tmp_path):
        entries = [make_entry("gt-001"), make_entry("gt-002")]
        p = tmp_path / "gt.jsonl"
        write_jsonl(entries, p)
        loaded = load_ground_truth(p)
        assert len(loaded) == 2

    def test_returns_ground_truth_entry_objects(self, tmp_path):
        p = tmp_path / "gt.jsonl"
        write_jsonl([make_entry()], p)
        loaded = load_ground_truth(p)
        assert isinstance(loaded[0], GroundTruthEntry)

    def test_filter_by_difficulty(self, tmp_path):
        entries = [
            make_entry("gt-001", difficulty="easy"),
            make_entry("gt-002", difficulty="medium"),
            make_entry("gt-003", difficulty="easy"),
        ]
        p = tmp_path / "gt.jsonl"
        write_jsonl(entries, p)
        loaded = load_ground_truth(p, difficulty=Difficulty.EASY)
        assert len(loaded) == 2
        assert all(e.difficulty == Difficulty.EASY for e in loaded)

    def test_filter_by_category(self, tmp_path):
        entries = [
            make_entry("gt-001", category="general"),
            make_entry("gt-002", category="code"),
        ]
        p = tmp_path / "gt.jsonl"
        write_jsonl(entries, p)
        loaded = load_ground_truth(p, category=Category.GENERAL)
        assert len(loaded) == 1
        assert loaded[0].category == Category.GENERAL

    def test_filter_only_verified(self, tmp_path):
        entries = [
            make_entry("gt-001", source="manual_seed", manually_verified=True),
            make_entry("gt-002", source="llm_synthetic", manually_verified=False),
        ]
        p = tmp_path / "gt.jsonl"
        write_jsonl(entries, p)
        loaded = load_ground_truth(p, only_verified=True)
        assert len(loaded) == 1
        assert loaded[0].manually_verified is True

    def test_raises_if_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_ground_truth(Path("/nonexistent/path.jsonl"))

    def test_skips_blank_lines(self, tmp_path):
        p = tmp_path / "gt.jsonl"
        entry = make_entry()
        p.write_text(entry.model_dump_json() + "\n\n")
        loaded = load_ground_truth(p)
        assert len(loaded) == 1


class TestMergeGroundTruth:
    def test_merges_two_files(self, tmp_path):
        p1 = tmp_path / "a.jsonl"
        p2 = tmp_path / "b.jsonl"
        write_jsonl([make_entry("gt-001")], p1)
        write_jsonl([make_entry("gt-002")], p2)
        merged = merge_ground_truth(p1, p2)
        assert len(merged) == 2

    def test_raises_on_duplicate_query_id(self, tmp_path):
        p1 = tmp_path / "a.jsonl"
        p2 = tmp_path / "b.jsonl"
        write_jsonl([make_entry("gt-001")], p1)
        write_jsonl([make_entry("gt-001")], p2)  # duplicate
        with pytest.raises(ValueError, match="duplicate query_id"):
            merge_ground_truth(p1, p2)


class TestSplitByDifficulty:
    def test_splits_into_three_groups(self):
        entries = [
            make_entry("gt-001", difficulty="easy"),
            make_entry(
                "gt-002",
                difficulty="medium",
                ambiguity="medium",
                alternative_tools=["EthanHenrickson/math-mcp::subtract"],
            ),
            make_entry(
                "gt-003",
                difficulty="hard",
                ambiguity="medium",
                alternative_tools=["EthanHenrickson/math-mcp::subtract"],
            ),
        ]
        groups = split_by_difficulty(entries)
        assert len(groups[Difficulty.EASY]) == 1
        assert len(groups[Difficulty.MEDIUM]) == 1
        assert len(groups[Difficulty.HARD]) == 1

    def test_missing_difficulty_returns_empty_list(self):
        entries = [make_entry("gt-001", difficulty="easy")]
        groups = split_by_difficulty(entries)
        assert groups[Difficulty.MEDIUM] == []
        assert groups[Difficulty.HARD] == []

    def test_returns_all_three_keys(self):
        groups = split_by_difficulty([])
        assert set(groups.keys()) == {Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD}


class TestQualityGate:
    def _make_entries_with_distribution(
        self, n_easy: int, n_medium: int, n_hard: int
    ) -> list[GroundTruthEntry]:
        entries = []
        for i in range(n_easy):
            entries.append(make_entry(f"e-{i}", difficulty="easy"))
        for i in range(n_medium):
            entries.append(
                make_entry(
                    f"m-{i}",
                    difficulty="medium",
                    ambiguity="medium",
                    alternative_tools=["EthanHenrickson/math-mcp::subtract"],
                )
            )
        for i in range(n_hard):
            entries.append(
                make_entry(
                    f"h-{i}",
                    difficulty="hard",
                    ambiguity="medium",
                    alternative_tools=["EthanHenrickson/math-mcp::subtract"],
                )
            )
        return entries

    def test_passes_when_distribution_matches_seed(self):
        # seed: 4 easy, 4 medium, 2 hard (40/40/20)
        seed = self._make_entries_with_distribution(4, 4, 2)
        # synthetic matches exactly
        synthetic = self._make_entries_with_distribution(8, 8, 4)
        gate = QualityGate()
        gate.check_difficulty_distribution(synthetic, seed)  # must not raise

    def test_fails_when_distribution_deviates_too_much(self):
        seed = self._make_entries_with_distribution(4, 4, 2)  # 40/40/20
        # synthetic: all easy (100/0/0) — far from seed
        synthetic = self._make_entries_with_distribution(20, 0, 0)
        gate = QualityGate()
        with pytest.raises(QualityGateError, match="difficulty distribution"):
            gate.check_difficulty_distribution(synthetic, seed)

    def test_fails_on_empty_synthetic(self):
        seed = self._make_entries_with_distribution(4, 4, 2)
        gate = QualityGate()
        with pytest.raises(QualityGateError):
            gate.check_difficulty_distribution([], seed)

    def test_no_tool_name_leakage_passes_when_clean(self):
        entries = [
            make_entry(
                "m-1",
                difficulty="medium",
                ambiguity="medium",
                alternative_tools=["EthanHenrickson/math-mcp::subtract"],
            ),
        ]
        # Manually set query that doesn't contain tool name
        entries[0] = entries[0].model_copy(update={"query": "find the middle value"})
        gate = QualityGate()
        gate.check_no_tool_name_leakage(
            entries, tool_names=["add", "subtract", "median"]
        )  # no raise

    def test_easy_entries_are_skipped_in_leakage_check(self):
        """Easy difficulty entries should be allowed to contain tool names."""
        entry = make_entry("e-1", difficulty="easy")
        entry = entry.model_copy(update={"query": "use the add function"})
        gate = QualityGate()
        # Should NOT raise — easy queries are exempt
        gate.check_no_tool_name_leakage([entry], tool_names=["add", "subtract"])

    def test_tool_name_leakage_fails_for_medium(self):
        entry = make_entry(
            "m-1",
            difficulty="medium",
            ambiguity="medium",
            alternative_tools=["EthanHenrickson/math-mcp::subtract"],
        )
        entry = entry.model_copy(update={"query": "use the add function on two numbers"})
        gate = QualityGate()
        with pytest.raises(QualityGateError, match="keyword leakage"):
            gate.check_no_tool_name_leakage([entry], tool_names=["add", "subtract"])


_SAMPLE_TOOL = MCPTool(
    server_id="EthanHenrickson/math-mcp",
    tool_name="add",
    tool_id="EthanHenrickson/math-mcp::add",
    description="Adds two numbers together",
)


class TestParseQueries:
    def _raw_json(self, items: list[dict]) -> str:
        return json.dumps(items)

    def _make_items(self, n: int = 3) -> list[dict]:
        return [
            {
                "query": f"test query {i}",
                "difficulty": "easy",
                "ambiguity": "low",
                "alternative_tool_names": [],
                "notes": "test",
            }
            for i in range(n)
        ]

    def test_returns_ground_truth_entries(self):
        raw = self._raw_json(self._make_items(3))
        results = parse_queries(raw, _SAMPLE_TOOL, created_at="2026-03-24")
        assert len(results) == 3
        assert all(isinstance(e, GroundTruthEntry) for e in results)
        assert all(e.correct_tool_id == _SAMPLE_TOOL.tool_id for e in results)
        assert all(e.manually_verified is False for e in results)
        assert all(e.source == "llm_synthetic" for e in results)

    def test_strips_markdown_fences(self):
        items = self._make_items(2)
        raw = "```json\n" + json.dumps(items) + "\n```"
        results = parse_queries(raw, _SAMPLE_TOOL, created_at="2026-03-24")
        assert len(results) == 2

    def test_fixes_hard_low_ambiguity(self):
        items = [
            {
                "query": "ambiguous math operation",
                "difficulty": "hard",
                "ambiguity": "low",
                "alternative_tool_names": ["subtract"],
                "notes": "should be bumped to medium",
            }
        ]
        results = parse_queries(self._raw_json(items), _SAMPLE_TOOL, created_at="2026-03-24")
        assert len(results) == 1
        assert results[0].ambiguity.value == "medium"

    def test_skips_malformed_items(self):
        items = [
            {"no_query_key": "bad"},  # missing "query"
            {
                "query": "valid query",
                "difficulty": "easy",
                "ambiguity": "low",
                "alternative_tool_names": [],
                "notes": "ok",
            },
        ]
        results = parse_queries(self._raw_json(items), _SAMPLE_TOOL, created_at="2026-03-24")
        assert len(results) == 1

    def test_empty_input_returns_empty(self):
        results = parse_queries("[]", _SAMPLE_TOOL, created_at="2026-03-24")
        assert results == []

    def test_non_json_returns_empty(self):
        results = parse_queries("this is not json", _SAMPLE_TOOL, created_at="2026-03-24")
        assert results == []

    def test_non_list_json_returns_empty(self):
        """JSON parses but is not a list (e.g. object) → empty."""
        results = parse_queries('{"query": "test"}', _SAMPLE_TOOL, created_at="2026-03-24")
        assert results == []

    def test_hard_low_ambiguity_without_alternatives_is_skipped(self):
        """hard + low ambiguity + no alternative_tool_names → skipped entirely."""
        items = [
            {
                "query": "ambiguous operation",
                "difficulty": "hard",
                "ambiguity": "low",
                "alternative_tool_names": [],
                "notes": "should be skipped",
            }
        ]
        results = parse_queries(self._raw_json(items), _SAMPLE_TOOL, created_at="2026-03-24")
        assert len(results) == 0

    def test_medium_ambiguity_without_alternatives_downgraded_to_low(self):
        """medium ambiguity but no alternative_tool_names → downgraded to low."""
        items = [
            {
                "query": "combine values together",
                "difficulty": "medium",
                "ambiguity": "medium",
                "alternative_tool_names": [],
                "notes": "no alternatives",
            }
        ]
        results = parse_queries(self._raw_json(items), _SAMPLE_TOOL, created_at="2026-03-24")
        assert len(results) == 1
        assert results[0].ambiguity.value == "low"

    def test_default_created_at_uses_today(self):
        """When created_at is not provided, defaults to today's date."""
        from datetime import date

        items = self._make_items(1)
        results = parse_queries(self._raw_json(items), _SAMPLE_TOOL)
        assert len(results) == 1
        assert results[0].created_at == date.today().isoformat()


class TestSave:
    def test_writes_jsonl(self, tmp_path):
        entries = [make_entry("gt-s-001"), make_entry("gt-s-002")]
        out = tmp_path / "out.jsonl"
        save(entries, out)
        lines = [line for line in out.read_text().splitlines() if line.strip()]
        assert len(lines) == 2
        for line in lines:
            GroundTruthEntry.model_validate_json(line)  # should not raise

    def test_creates_parent_dirs(self, tmp_path):
        entries = [make_entry("gt-s-001")]
        out = tmp_path / "nested" / "dir" / "out.jsonl"
        save(entries, out)
        assert out.exists()

    def test_returns_count(self, tmp_path):
        entries = [make_entry("gt-s-001"), make_entry("gt-s-002"), make_entry("gt-s-003")]
        out = tmp_path / "out.jsonl"
        count = save(entries, out)
        assert count == 3


class TestGenerateSyntheticGT:
    async def test_generate_with_mocked_llm(self):
        from mcp_discovery.data.ground_truth import generate_synthetic_gt
        from mcp_discovery.models import MCPServer

        server = MCPServer(
            server_id="EthanHenrickson/math-mcp",
            name="Math-MCP",
            tools=[_SAMPLE_TOOL],
        )

        llm_output = json.dumps(
            [
                {
                    "query": "add two numbers",
                    "difficulty": "easy",
                    "ambiguity": "low",
                    "alternative_tool_names": [],
                    "notes": "direct keyword",
                },
                {
                    "query": "combine these values",
                    "difficulty": "medium",
                    "ambiguity": "low",
                    "alternative_tool_names": [],
                    "notes": "semantic",
                },
                {
                    "query": "do some arithmetic operation",
                    "difficulty": "hard",
                    "ambiguity": "medium",
                    "alternative_tool_names": ["subtract"],
                    "notes": "ambiguous",
                },
            ]
        )

        mock_message = MagicMock()
        mock_message.content = llm_output
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        entries = await generate_synthetic_gt([server], mock_client, created_at="2026-03-24")

        assert len(entries) == 3
        assert all(e.source == "llm_synthetic" for e in entries)
        assert all(e.manually_verified is False for e in entries)
        assert all(e.correct_tool_id == _SAMPLE_TOOL.tool_id for e in entries)
        assert all(e.correct_server_id == server.server_id for e in entries)


class TestGenerateSyntheticGTEdgeCases:
    async def test_llm_call_failure_skips_tool(self):
        """When LLM call raises, that tool is skipped and others continue."""
        from mcp_discovery.data.ground_truth import generate_synthetic_gt
        from mcp_discovery.models import MCPServer

        tool1 = MCPTool(
            server_id="srv",
            tool_name="tool1",
            tool_id="srv::tool1",
            description="First tool",
        )
        tool2 = MCPTool(
            server_id="srv",
            tool_name="tool2",
            tool_id="srv::tool2",
            description="Second tool",
        )
        server = MCPServer(server_id="srv", name="Test", tools=[tool1, tool2])

        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("API error")
            mock_msg = MagicMock()
            mock_msg.content = json.dumps(
                [
                    {
                        "query": "test",
                        "difficulty": "easy",
                        "ambiguity": "low",
                        "alternative_tool_names": [],
                        "notes": "ok",
                    }
                ]
            )
            mock_choice = MagicMock()
            mock_choice.message = mock_msg
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            return mock_resp

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

        entries = await generate_synthetic_gt([server], mock_client, created_at="2026-03-24")
        # tool1 failed, tool2 succeeded → only 1 entry
        assert len(entries) == 1
        assert entries[0].correct_tool_id == "srv::tool2"

    async def test_default_created_at_uses_today(self):
        """When created_at is None, uses date.today()."""
        from datetime import date

        from mcp_discovery.data.ground_truth import generate_synthetic_gt
        from mcp_discovery.models import MCPServer

        server = MCPServer(
            server_id="srv",
            name="Test",
            tools=[MCPTool(server_id="srv", tool_name="t", tool_id="srv::t", description="d")],
        )

        mock_msg = MagicMock()
        mock_msg.content = json.dumps(
            [
                {
                    "query": "test",
                    "difficulty": "easy",
                    "ambiguity": "low",
                    "alternative_tool_names": [],
                    "notes": "ok",
                }
            ]
        )
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        entries = await generate_synthetic_gt([server], mock_client)  # no created_at
        assert entries[0].created_at == date.today().isoformat()


@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_OPENAI_TESTS") or not os.getenv("OPENAI_API_KEY"),
    reason="requires RUN_LIVE_OPENAI_TESTS=1 and OPENAI_API_KEY",
)
async def test_generate_synthetic_gt_integration():
    """Integration test — only runs when OPENAI_API_KEY is set."""
    from openai import AsyncOpenAI

    from mcp_discovery.data.ground_truth import generate_synthetic_gt
    from mcp_discovery.models import MCPServer

    server = MCPServer(
        server_id="EthanHenrickson/math-mcp",
        name="Math-MCP",
        tools=[_SAMPLE_TOOL],
    )
    client = AsyncOpenAI()
    entries = await generate_synthetic_gt([server], client)
    assert len(entries) > 0
    assert all(e.source == "llm_synthetic" for e in entries)
