"""Token counting utility for description efficiency analysis.

Uses tiktoken (cl100k_base) for accurate GPT-family token counts.
"""

from __future__ import annotations

import tiktoken
from pydantic import BaseModel, computed_field

_ENCODING: tiktoken.Encoding | None = None


def _get_encoding() -> tiktoken.Encoding:
    """Lazy-initialize tiktoken encoding on first use."""
    global _ENCODING
    if _ENCODING is None:
        _ENCODING = tiktoken.get_encoding("cl100k_base")
    return _ENCODING


def count_tokens(text: str | None) -> int:
    """Count tokens in text using cl100k_base encoding."""
    if not text:
        return 0
    return len(_get_encoding().encode(text))


class TokenStats(BaseModel):
    """Token efficiency comparison between raw and enriched descriptions."""

    raw_tokens: int
    enriched_tokens: int
    pool_median: int | None = None

    @computed_field
    @property
    def ratio(self) -> float:
        """Enriched/raw ratio. Less than 1 means enrichment is more concise."""
        if self.raw_tokens == 0:
            return 0.0
        return self.enriched_tokens / self.raw_tokens

    @classmethod
    def from_descriptions(
        cls,
        raw: str | None,
        enriched: str | None,
        pool_median: int | None = None,
    ) -> "TokenStats":
        return cls(
            raw_tokens=count_tokens(raw),
            enriched_tokens=count_tokens(enriched),
            pool_median=pool_median,
        )
