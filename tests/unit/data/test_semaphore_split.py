"""Unit tests for split semaphore (stdio=2, http=8) in pool_prober (AC23)."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from mcp_discovery.data.pool_prober import (
    _HTTP_CONCURRENCY,
    _STDIO_CONCURRENCY,
    ProberRegistry,
    probe_server,
)
from mcp_discovery.data.probers.base import Prober
from mcp_discovery.models.probe import ProbeErrorKind, ProbeResult, TransportSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestSemaphoreConstants:
    def test_stdio_concurrency_is_2(self) -> None:
        assert _STDIO_CONCURRENCY == 2

    def test_http_concurrency_is_8(self) -> None:
        assert _HTTP_CONCURRENCY == 8


# ---------------------------------------------------------------------------
# Semaphore selection test
# ---------------------------------------------------------------------------


class TestSemaphoreSelection:
    """Verify that the correct semaphore is used for each transport type."""

    async def test_http_probe_uses_http_semaphore(self, tmp_path: Path) -> None:
        """HTTP probes must acquire http_sem, not stdio_sem."""
        spec = TransportSpec(transport="http", server_id="test")
        spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()

        fast_result = ProbeResult(
            server_id="test",
            success=False,
            spec_hash=spec_hash,
            error_kind=ProbeErrorKind.TRANSPORT_UNSUPPORTED,
        )

        mock_prober = AsyncMock(spec=Prober)
        mock_prober.supports.return_value = True
        mock_prober.probe.return_value = fast_result

        reg = ProberRegistry()
        reg.register("http", mock_prober)

        http_sem = asyncio.Semaphore(_HTTP_CONCURRENCY)
        stdio_sem = asyncio.Semaphore(_STDIO_CONCURRENCY)

        # Track which semaphore was acquired
        http_acquired = []
        stdio_acquired = []

        original_http_acquire = http_sem.acquire
        original_stdio_acquire = stdio_sem.acquire

        async def track_http_acquire() -> Any:
            http_acquired.append(True)
            return await original_http_acquire()

        async def track_stdio_acquire() -> Any:
            stdio_acquired.append(True)
            return await original_stdio_acquire()

        http_sem.acquire = track_http_acquire  # type: ignore[method-assign]
        stdio_sem.acquire = track_stdio_acquire  # type: ignore[method-assign]

        await probe_server(
            "test", spec, registry=reg, stdio_sem=stdio_sem, http_sem=http_sem, cache_dir=tmp_path
        )

        assert len(http_acquired) == 1, "http_sem must be acquired for HTTP transport"
        assert len(stdio_acquired) == 0, "stdio_sem must NOT be acquired for HTTP transport"

    async def test_stdio_probe_uses_stdio_semaphore(self, tmp_path: Path) -> None:
        """Stdio probes must acquire stdio_sem, not http_sem."""
        spec = TransportSpec(transport="stdio", server_id="test")
        spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()

        fast_result = ProbeResult(
            server_id="test",
            success=False,
            spec_hash=spec_hash,
            error_kind=ProbeErrorKind.TRANSPORT_UNSUPPORTED,
        )

        mock_prober = AsyncMock(spec=Prober)
        mock_prober.supports.return_value = True
        mock_prober.probe.return_value = fast_result

        reg = ProberRegistry()
        reg.register("stdio", mock_prober)

        http_sem = asyncio.Semaphore(_HTTP_CONCURRENCY)
        stdio_sem = asyncio.Semaphore(_STDIO_CONCURRENCY)

        http_acquired = []
        stdio_acquired = []

        original_http_acquire = http_sem.acquire
        original_stdio_acquire = stdio_sem.acquire

        async def track_http() -> Any:
            http_acquired.append(True)
            return await original_http_acquire()

        async def track_stdio() -> Any:
            stdio_acquired.append(True)
            return await original_stdio_acquire()

        http_sem.acquire = track_http  # type: ignore[method-assign]
        stdio_sem.acquire = track_stdio  # type: ignore[method-assign]

        await probe_server(
            "test", spec, registry=reg, stdio_sem=stdio_sem, http_sem=http_sem, cache_dir=tmp_path
        )

        assert len(stdio_acquired) == 1, "stdio_sem must be acquired for stdio transport"
        assert len(http_acquired) == 0, "http_sem must NOT be acquired for stdio transport"

    async def test_script_probe_uses_stdio_semaphore(self, tmp_path: Path) -> None:
        """Script probes use stdio_sem (same capacity as stdio)."""
        spec = TransportSpec(transport="script", server_id="test")
        spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()

        fast_result = ProbeResult(
            server_id="test",
            success=False,
            spec_hash=spec_hash,
            error_kind=ProbeErrorKind.TRANSPORT_UNSUPPORTED,
        )

        mock_prober = AsyncMock(spec=Prober)
        mock_prober.supports.return_value = True
        mock_prober.probe.return_value = fast_result

        reg = ProberRegistry()
        reg.register("script", mock_prober)

        http_sem = asyncio.Semaphore(_HTTP_CONCURRENCY)
        stdio_sem = asyncio.Semaphore(_STDIO_CONCURRENCY)

        http_acquired = []
        stdio_acquired = []

        original_http_acquire = http_sem.acquire
        original_stdio_acquire = stdio_sem.acquire

        async def track_http() -> Any:
            http_acquired.append(True)
            return await original_http_acquire()

        async def track_stdio() -> Any:
            stdio_acquired.append(True)
            return await original_stdio_acquire()

        http_sem.acquire = track_http  # type: ignore[method-assign]
        stdio_sem.acquire = track_stdio  # type: ignore[method-assign]

        await probe_server(
            "test", spec, registry=reg, stdio_sem=stdio_sem, http_sem=http_sem, cache_dir=tmp_path
        )

        assert len(stdio_acquired) == 1, "script transport must use stdio_sem"
        assert len(http_acquired) == 0, "script transport must NOT use http_sem"
