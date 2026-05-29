"""Bounded async session pool for long-running MCP gateway transports."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol


class ClosableSession(Protocol):
    """Minimal interface required for pooled gateway sessions."""

    async def close(self) -> None:
        """Release session resources."""


class SessionLimitError(RuntimeError):
    """Raised when the gateway would exceed its configured session limit."""


class SessionPool:
    """Small keyed async session pool with explicit close semantics."""

    def __init__(
        self,
        *,
        factory: Callable[[str], Awaitable[ClosableSession]],
        max_sessions: int = 64,
    ) -> None:
        self._factory = factory
        self._max_sessions = max_sessions
        self._sessions: dict[str, ClosableSession] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> ClosableSession:
        """Return an existing session for key or create one within the bound."""
        async with self._lock:
            if key in self._sessions:
                return self._sessions[key]
            if len(self._sessions) >= self._max_sessions:
                raise SessionLimitError("gateway session limit reached")
            session = await self._factory(key)
            self._sessions[key] = session
            return session

    async def close(self, key: str) -> None:
        """Close and remove one session if it exists."""
        session = self._sessions.pop(key, None)
        if session is not None:
            await session.close()

    async def close_all(self) -> None:
        """Close every active session and empty the pool."""
        keys = list(self._sessions)
        for key in keys:
            await self.close(key)

    def status(self) -> dict[str, object]:
        """Return a non-secret operational snapshot of the pool."""
        return {"active": len(self._sessions), "keys": sorted(self._sessions)}
