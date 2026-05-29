"""Tests for scripts/build_experiment_queries.py — pure helper functions."""

from build_experiment_queries import (
    CONFUSION_CLUSTERS,
    TARGET_TOOLS,
    build_candidate_set,
    select_queries_for_tool,
)


class TestConfusionClusters:
    """Validate CONFUSION_CLUSTERS structure invariants."""

    def test_has_airtable_cluster(self) -> None:
        assert "airtable" in CONFUSION_CLUSTERS

    def test_airtable_cluster_has_four_tools(self) -> None:
        assert len(CONFUSION_CLUSTERS["airtable"]) == 4

    def test_has_web_search_cluster(self) -> None:
        assert "web_search" in CONFUSION_CLUSTERS

    def test_web_search_cluster_has_three_or_more_tools(self) -> None:
        assert len(CONFUSION_CLUSTERS["web_search"]) >= 3

    def test_all_tool_ids_contain_separator(self) -> None:
        for cluster_tools in CONFUSION_CLUSTERS.values():
            for tool_id in cluster_tools:
                assert "::" in tool_id, f"tool_id missing '::' separator: {tool_id}"

    def test_target_tools_all_in_clusters(self) -> None:
        all_cluster_tools = {t for tools in CONFUSION_CLUSTERS.values() for t in tools}
        for tool_id in TARGET_TOOLS:
            assert tool_id in all_cluster_tools, f"{tool_id} not in any cluster"


class TestBuildCandidateSet:
    """Tests for build_candidate_set() pure function."""

    def _make_tool_map(self) -> dict[str, str]:
        return {
            "airtable::search_records": "Search records in a table",
            "airtable::list_records": "List all records from a table",
            "airtable::list_bases": "List all bases in workspace",
            "airtable::list_tables": "List tables in a base",
        }

    def test_returns_all_cluster_tools(self) -> None:
        tool_descriptions = self._make_tool_map()
        candidates = build_candidate_set("airtable", CONFUSION_CLUSTERS, tool_descriptions)
        returned_ids = {c["tool_id"] for c in candidates}
        expected_ids = set(CONFUSION_CLUSTERS["airtable"])
        assert returned_ids == expected_ids

    def test_each_candidate_has_tool_id_and_description(self) -> None:
        tool_descriptions = self._make_tool_map()
        candidates = build_candidate_set("airtable", CONFUSION_CLUSTERS, tool_descriptions)
        for c in candidates:
            assert "tool_id" in c
            assert "description" in c

    def test_descriptions_match_tool_map(self) -> None:
        tool_descriptions = self._make_tool_map()
        candidates = build_candidate_set("airtable", CONFUSION_CLUSTERS, tool_descriptions)
        for c in candidates:
            assert c["description"] == tool_descriptions[c["tool_id"]]

    def test_missing_tool_description_uses_empty_string(self) -> None:
        # Only provide descriptions for 2 of 4 tools
        partial_map = {
            "airtable::search_records": "Search records",
            "airtable::list_records": "List records",
        }
        candidates = build_candidate_set("airtable", CONFUSION_CLUSTERS, partial_map)
        missing = [c for c in candidates if c["tool_id"] not in partial_map]
        for c in missing:
            assert c["description"] == ""


class TestSelectQueriesForTool:
    """Tests for select_queries_for_tool() pure function."""

    def _make_gt_entries(self) -> list[dict]:
        return [
            {
                "query_id": f"gt-atlas-00{i}-s00",
                "query": f"Query about airtable search {i}",
                "correct_tool_id": "airtable::search_records",
                "correct_server_id": "airtable",
            }
            for i in range(10)
        ] + [
            {
                "query_id": "gt-atlas-999-s00",
                "query": "Unrelated query",
                "correct_tool_id": "github::search_repositories",
                "correct_server_id": "github",
            }
        ]

    def test_returns_only_matching_tool_queries(self) -> None:
        entries = self._make_gt_entries()
        selected = select_queries_for_tool("airtable::search_records", entries, n=10, seed=42)
        for entry in selected:
            assert entry["correct_tool_id"] == "airtable::search_records"

    def test_respects_n_limit(self) -> None:
        entries = self._make_gt_entries()
        selected = select_queries_for_tool("airtable::search_records", entries, n=5, seed=42)
        assert len(selected) <= 5

    def test_is_deterministic_with_same_seed(self) -> None:
        entries = self._make_gt_entries()
        first = select_queries_for_tool("airtable::search_records", entries, n=5, seed=42)
        second = select_queries_for_tool("airtable::search_records", entries, n=5, seed=42)
        assert [e["query_id"] for e in first] == [e["query_id"] for e in second]

    def test_returns_empty_for_no_matching_tool(self) -> None:
        entries = self._make_gt_entries()
        selected = select_queries_for_tool("nonexistent::tool", entries, n=5, seed=42)
        assert selected == []

    def test_returns_all_when_fewer_than_n(self) -> None:
        # Only 10 matching entries but n=20
        entries = self._make_gt_entries()
        selected = select_queries_for_tool("airtable::search_records", entries, n=20, seed=42)
        assert len(selected) == 10
