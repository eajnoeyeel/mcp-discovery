"""Tests for storage protocol implementations."""

from pathlib import Path

import pytest

from mcp_discovery.analytics.storage.local import LocalLogStore, LocalSnapshotBackend


@pytest.fixture()
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture()
def snap_dir(tmp_path: Path) -> Path:
    return tmp_path / "snapshots"


class TestLocalLogStore:
    async def test_append_and_read(self, log_dir: Path) -> None:
        store = LocalLogStore(log_dir=log_dir)
        await store.append("2026-04-12", '{"query": "test"}\n')
        lines = await store.read_lines("2026-04-12")
        assert len(lines) == 1
        assert "test" in lines[0]

    async def test_list_date_keys(self, log_dir: Path) -> None:
        store = LocalLogStore(log_dir=log_dir)
        await store.append("2026-04-11", '{"a": 1}\n')
        await store.append("2026-04-12", '{"b": 2}\n')
        keys = await store.list_date_keys()
        assert keys == ["2026-04-11", "2026-04-12"]

    async def test_read_empty(self, log_dir: Path) -> None:
        store = LocalLogStore(log_dir=log_dir)
        lines = await store.read_lines("2026-01-01")
        assert lines == []

    async def test_list_empty(self, log_dir: Path) -> None:
        store = LocalLogStore(log_dir=log_dir)
        assert await store.list_date_keys() == []


class TestLocalSnapshotBackend:
    async def test_save_and_load(self, snap_dir: Path) -> None:
        backend = LocalSnapshotBackend(snapshot_dir=snap_dir)
        await backend.save("t1", "2026-W15", '{"week_id":"2026-W15","tool_id":"t1"}')
        lines = await backend.load_all("t1")
        assert len(lines) == 1

    async def test_deduplicates_week(self, snap_dir: Path) -> None:
        backend = LocalSnapshotBackend(snapshot_dir=snap_dir)
        await backend.save("t1", "2026-W15", '{"week_id":"2026-W15","tool_id":"t1","v":1}')
        await backend.save("t1", "2026-W15", '{"week_id":"2026-W15","tool_id":"t1","v":2}')
        lines = await backend.load_all("t1")
        assert len(lines) == 1
        assert '"v": 2' in lines[0] or '"v":2' in lines[0]

    async def test_load_empty(self, snap_dir: Path) -> None:
        backend = LocalSnapshotBackend(snapshot_dir=snap_dir)
        assert await backend.load_all("nonexistent") == []
