"""Tests for server selection and filtering logic."""

import pytest

from mcp_discovery.data.server_selector import (
    filter_deployed,
    load_curated_list,
    select_servers,
    sort_by_popularity,
)
from mcp_discovery.models import MCPServerSummary


@pytest.fixture
def sample_summaries() -> list[MCPServerSummary]:
    return [
        MCPServerSummary(
            qualified_name="@a/deployed-popular",
            display_name="A",
            use_count=1000,
            is_deployed=True,
        ),
        MCPServerSummary(
            qualified_name="@b/deployed-less",
            display_name="B",
            use_count=500,
            is_deployed=True,
        ),
        MCPServerSummary(
            qualified_name="@c/not-deployed",
            display_name="C",
            use_count=2000,
            is_deployed=False,
        ),
        MCPServerSummary(
            qualified_name="@d/deployed-least",
            display_name="D",
            use_count=100,
            is_deployed=True,
        ),
    ]


class TestFilterDeployed:
    def test_filters_non_deployed(self, sample_summaries):
        result = filter_deployed(sample_summaries)
        assert len(result) == 3
        assert all(s.is_deployed for s in result)

    def test_empty_input(self):
        assert filter_deployed([]) == []


class TestSortByPopularity:
    def test_sorts_descending(self, sample_summaries):
        result = sort_by_popularity(sample_summaries)
        use_counts = [s.use_count for s in result]
        assert use_counts == sorted(use_counts, reverse=True)


class TestLoadCuratedList:
    def test_loads_from_file(self, tmp_path):
        f = tmp_path / "servers.txt"
        f.write_text("@a/server\n@b/server\n\n# comment\n  \n@c/server\n")
        result = load_curated_list(f)
        assert result == ["@a/server", "@b/server", "@c/server"]

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        assert load_curated_list(f) == []


class TestSelectServers:
    def test_default_filters_and_sorts(self, sample_summaries):
        result = select_servers(sample_summaries, max_servers=2)
        assert len(result) == 2
        assert result[0].qualified_name == "@a/deployed-popular"
        assert result[1].qualified_name == "@b/deployed-less"

    def test_curated_list_overrides(self, sample_summaries, tmp_path):
        f = tmp_path / "curated.txt"
        f.write_text("@d/deployed-least\n@c/not-deployed\n")
        result = select_servers(sample_summaries, curated_list=f)
        names = [s.qualified_name for s in result]
        assert "@d/deployed-least" in names
        assert "@c/not-deployed" in names

    def test_max_servers_limit(self, sample_summaries):
        result = select_servers(sample_summaries, max_servers=1)
        assert len(result) == 1

    def test_skip_deployed_filter(self, sample_summaries):
        result = select_servers(sample_summaries, require_deployed=False, max_servers=10)
        assert len(result) == 4
