"""Local EventBridge-compatible relay for invoking the index handler."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

_STOP = object()


class LocalEventBridgeRelay:
    """Queue server.registered events and invoke the index handler locally."""

    def __init__(
        self,
        index_handler: Callable[[dict[str, Any], object | None], Awaitable[dict[str, Any]]],
    ) -> None:
        self._index_handler = index_handler
        self._queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()
        self._runner: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._closing = False
        self._stopped = False

    async def start(self) -> None:
        """Start the background relay loop if it is not already running."""
        async with self._lifecycle_lock:
            if self._runner is not None and not self._runner.done():
                return
            if self._stopped:
                self._queue = asyncio.Queue()
                self._stopped = False
            self._closing = False
            self._runner = asyncio.create_task(self._run(), name="mlp-local-eventbridge-relay")

    async def stop(self) -> None:
        """Stop the background relay loop after queued work is processed."""
        async with self._lifecycle_lock:
            if self._stopped:
                return
            self._closing = True
            runner = self._runner
            queue = self._queue
            if runner is None or runner.done():
                self._queue = asyncio.Queue()
                self._runner = None
                self._stopped = True
                return
            await queue.put(_STOP)

        await runner

        async with self._lifecycle_lock:
            self._queue = asyncio.Queue()
            self._runner = None
            self._stopped = True

    async def publish_server_registered(self, server_id: str) -> None:
        """Queue a server.registered event using the production-shaped payload."""
        async with self._lifecycle_lock:
            if self._closing or self._stopped:
                raise RuntimeError("LocalEventBridgeRelay is not accepting new events")
            await self._queue.put(
                {
                    "source": "mcp-discovery",
                    "detail-type": "server.registered",
                    "detail": {"server_id": server_id},
                }
            )

    async def drain(self) -> None:
        """Wait until all currently queued events are processed."""
        await self._queue.join()

    async def drain_once(self) -> bool:
        """Process one queued event, returning False when the relay is stopping."""
        event = await self._queue.get()
        try:
            if event is _STOP:
                return False
            await self._process_event(event)
            return True
        finally:
            self._queue.task_done()

    async def _run(self) -> None:
        while await self.drain_once():
            continue

    async def _process_event(self, event: dict[str, Any]) -> None:
        try:
            await self._index_handler(event, None)
        except Exception as exc:  # pragma: no cover - behavior asserted via continued processing
            server_id = event.get("detail", {}).get("server_id")
            logger.exception(
                "LocalEventBridgeRelay failed to invoke index handler "
                f"for server_id={server_id}: {exc}"
            )
