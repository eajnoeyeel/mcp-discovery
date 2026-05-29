"""Voyage dense embedder implementation for benchmark experiments."""

import asyncio
import hashlib
import time
from collections import deque
from importlib import import_module
from types import ModuleType
from typing import Literal

import numpy as np
from loguru import logger

from mcp_discovery.embedding.base import Embedder

VoyageInputType = Literal["query", "document"] | None


def _load_voyageai() -> ModuleType:
    return import_module("voyageai")


def _estimate_tokens(text: str) -> int:
    # Conservative English-ish approximation for enforcing reduced Voyage TPM budgets.
    return max(1, (len(text) + 2) // 3)


def _estimate_batch_tokens(texts: list[str]) -> int:
    return sum(_estimate_tokens(text) for text in texts)


class AsyncRequestRateLimiter:
    """Process-local async limiter for low-RPM embedding benchmark accounts."""

    def __init__(
        self,
        requests_per_minute: float | None,
        tokens_per_minute: int | None,
    ) -> None:
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self._lock = asyncio.Lock()
        self._next_allowed_at = 0.0
        self._token_events: deque[tuple[float, int]] = deque()
        self._token_total = 0

    def _prune_token_events(self, now: float) -> None:
        while self._token_events and now - self._token_events[0][0] >= 60.0:
            _, tokens = self._token_events.popleft()
            self._token_total -= tokens

    async def wait(self, estimated_tokens: int = 0) -> None:
        has_request_limit = bool(self.requests_per_minute and self.requests_per_minute > 0)
        has_token_limit = bool(self.tokens_per_minute and self.tokens_per_minute > 0)
        if not has_request_limit and not has_token_limit:
            return

        interval = 60.0 / self.requests_per_minute if has_request_limit else 0.0
        charged_tokens = max(0, estimated_tokens)
        if has_token_limit:
            charged_tokens = min(charged_tokens, int(self.tokens_per_minute or 0))

        async with self._lock:
            while True:
                now = time.monotonic()
                self._prune_token_events(now)
                wait_seconds = 0.0
                if has_request_limit:
                    wait_seconds = max(wait_seconds, self._next_allowed_at - now)
                if (
                    has_token_limit
                    and charged_tokens > 0
                    and self._token_total + charged_tokens > int(self.tokens_per_minute or 0)
                    and self._token_events
                ):
                    token_wait = 60.0 - (now - self._token_events[0][0]) + 0.1
                    wait_seconds = max(wait_seconds, token_wait)
                if wait_seconds <= 0:
                    break
                logger.info(
                    "Voyage rate limiter sleeping "
                    f"{wait_seconds:.1f}s "
                    f"(limit={self.requests_per_minute or 'unbounded'} RPM, "
                    f"{self.tokens_per_minute or 'unbounded'} TPM, "
                    f"estimated_tokens={estimated_tokens})"
                )
                await asyncio.sleep(wait_seconds)

            now = time.monotonic()
            self._prune_token_events(now)
            if has_request_limit:
                self._next_allowed_at = max(now, self._next_allowed_at) + interval
            if has_token_limit and charged_tokens > 0:
                self._token_events.append((now, charged_tokens))
                self._token_total += charged_tokens


_RATE_LIMITERS: dict[str, AsyncRequestRateLimiter] = {}


def _shared_rate_limiter(
    *,
    api_key: str | None,
    requests_per_minute: float | None,
    tokens_per_minute: int | None,
) -> AsyncRequestRateLimiter | None:
    if (not requests_per_minute or requests_per_minute <= 0) and (
        not tokens_per_minute or tokens_per_minute <= 0
    ):
        return None
    # Share across Voyage models for the same account because the observed limit is account-wide.
    key = (
        hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        if api_key
        else "__default_voyage_account__"
    )
    limiter = _RATE_LIMITERS.get(key)
    if (
        limiter is None
        or limiter.requests_per_minute != requests_per_minute
        or limiter.tokens_per_minute != tokens_per_minute
    ):
        limiter = AsyncRequestRateLimiter(requests_per_minute, tokens_per_minute)
        _RATE_LIMITERS[key] = limiter
    return limiter


class VoyageEmbedder(Embedder):
    """Dense embedder backed by the official Voyage Python client.

    The shared ``Embedder`` abstraction does not distinguish between query and
    document roles, so ``input_type`` defaults to ``None`` to avoid silently
    applying the wrong retrieval prompt when one embedder instance is reused for
    both indexing and search.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "voyage-4",
        dimension: int = 1024,
        *,
        input_type: VoyageInputType = None,
        truncation: bool = True,
        max_retries: int = 0,
        timeout: int | None = None,
        requests_per_minute: float | None = None,
        tokens_per_minute: int | None = None,
        max_tokens_per_request: int | None = None,
    ) -> None:
        self.model = model
        self.dimension = dimension
        self.input_type = input_type
        self.truncation = truncation
        self.max_tokens_per_request = max_tokens_per_request
        self._rate_limiter = _shared_rate_limiter(
            api_key=api_key,
            requests_per_minute=requests_per_minute,
            tokens_per_minute=tokens_per_minute,
        )
        voyageai = _load_voyageai()
        self._client = voyageai.Client(
            api_key=api_key,
            max_retries=max_retries,
            timeout=timeout,
        )

    async def embed_one(self, text: str) -> np.ndarray:
        vectors = await self._embed_texts([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str], batch_size: int = 50) -> list[np.ndarray]:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if not texts:
            return []

        all_vectors: list[np.ndarray] = []
        for batch in self._iter_batches(texts, batch_size):
            vectors = await self._embed_texts(batch)
            all_vectors.extend(vectors)
        return all_vectors

    def _iter_batches(self, texts: list[str], batch_size: int) -> list[list[str]]:
        batches: list[list[str]] = []
        current: list[str] = []
        current_tokens = 0
        token_limit = self.max_tokens_per_request

        for text in texts:
            text_tokens = _estimate_tokens(text)
            would_exceed_size = len(current) >= batch_size
            would_exceed_tokens = (
                token_limit is not None and current and current_tokens + text_tokens > token_limit
            )
            if would_exceed_size or would_exceed_tokens:
                batches.append(current)
                current = []
                current_tokens = 0
            current.append(text)
            current_tokens += text_tokens

        if current:
            batches.append(current)
        return batches

    async def _embed_texts(self, texts: list[str]) -> list[np.ndarray]:
        try:
            if self._rate_limiter is not None:
                await self._rate_limiter.wait(_estimate_batch_tokens(texts))
            result = await asyncio.to_thread(
                self._client.embed,
                texts,
                model=self.model,
                input_type=self.input_type,
                truncation=self.truncation,
                output_dimension=self.dimension,
            )
        except Exception as exc:
            logger.error(
                f"Voyage embed failed (model={self.model}, batch_size={len(texts)}): {exc}"
            )
            raise

        return [np.array(embedding, dtype=np.float32) for embedding in result.embeddings]
