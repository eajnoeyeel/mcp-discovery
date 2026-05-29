"""Feature 4: Query inflow analysis — what queries lead to this tool."""

from __future__ import annotations

import re
from collections import Counter

from mcp_discovery.analytics.metrics.base import MetricContext, MetricResult, ProviderMetric

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "and",
        "but",
        "or",
        "not",
        "no",
        "nor",
        "if",
        "then",
        "than",
        "so",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "they",
        "them",
        "what",
        "which",
        "who",
        "whom",
        "find",
        "search",
        "get",
        "use",
        "tool",
        "need",
        "want",
        "look",
    }
)


class QueryInflowMetric(ProviderMetric):
    """Analyzes which queries lead to this tool being selected or considered."""

    @property
    def name(self) -> str:
        return "query_inflow"

    def compute(self, context: MetricContext) -> MetricResult:
        tool_id = context.tool_id
        winning_queries: list[str] = []
        losing_queries: list[dict] = []
        all_query_words: list[str] = []

        for entry in context.logs:
            is_winner = entry.recommended_tool_id == tool_id
            is_runner_up = tool_id in entry.alternatives

            if is_winner:
                winning_queries.append(entry.query)
                all_query_words.extend(self._extract_keywords(entry.query))
            elif is_runner_up:
                losing_queries.append(
                    {
                        "query": entry.query,
                        "winner": entry.recommended_tool_id,
                    }
                )

        keyword_counts = Counter(all_query_words)
        top_keywords = [{"keyword": kw, "count": cnt} for kw, cnt in keyword_counts.most_common(15)]

        total = len(winning_queries) + len(losing_queries)

        return MetricResult(
            metric_name=self.name,
            value={
                "total_appearances": total,
                "won": len(winning_queries),
                "lost": len(losing_queries),
                "winning_queries": winning_queries[:20],
                "losing_queries": losing_queries[:10],
                "top_keywords": top_keywords,
            },
        )

    @staticmethod
    def _extract_keywords(query: str) -> list[str]:
        """Extract non-stopword keywords from a query."""
        words = re.findall(r"\w+", query.lower())
        return [w for w in words if w not in _STOPWORDS and len(w) > 2]
