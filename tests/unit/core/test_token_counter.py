"""Tests for token counter utility."""

from mcp_discovery.analytics.token_counter import TokenStats, count_tokens


class TestCountTokens:
    def test_basic_count(self) -> None:
        count = count_tokens("Hello world")
        assert isinstance(count, int)
        assert count >= 2

    def test_empty_string(self) -> None:
        assert count_tokens("") == 0

    def test_none_returns_zero(self) -> None:
        assert count_tokens(None) == 0


class TestTokenStats:
    def test_from_descriptions(self) -> None:
        stats = TokenStats.from_descriptions(
            raw="Search repositories on GitHub",
            enriched=(
                "search_repositories repo repository github Search GitHub repositories by topic"
            ),
        )
        assert stats.raw_tokens > 0
        assert stats.enriched_tokens > 0
        assert isinstance(stats.ratio, float)

    def test_ratio_calculation(self) -> None:
        stats = TokenStats(raw_tokens=100, enriched_tokens=50, pool_median=80)
        assert stats.ratio == 0.5

    def test_ratio_zero_raw(self) -> None:
        stats = TokenStats(raw_tokens=0, enriched_tokens=50, pool_median=80)
        assert stats.ratio == 0.0
