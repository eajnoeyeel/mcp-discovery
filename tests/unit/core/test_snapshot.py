"""Tests for weekly snapshot store."""

from pathlib import Path

import pytest

from mcp_discovery.analytics.snapshot import SnapshotStore, WeeklySnapshot


@pytest.fixture()
def snapshot_dir(tmp_path: Path) -> Path:
    return tmp_path / "snapshots"


class TestWeeklySnapshot:
    def test_create_snapshot(self) -> None:
        snap = WeeklySnapshot(
            week_id="2026-W15",
            tool_id="github::search_repositories",
            selection_count=35,
            runner_up_count=12,
            win_rate=0.745,
            geo_total=0.65,
            token_count=847,
        )
        assert snap.week_id == "2026-W15"
        assert snap.win_rate == pytest.approx(0.745)


class TestSnapshotStore:
    async def test_save_and_load(self, snapshot_dir: Path) -> None:
        store = SnapshotStore(snapshot_dir=snapshot_dir)
        snap = WeeklySnapshot(
            week_id="2026-W15",
            tool_id="github::search_repositories",
            selection_count=35,
            runner_up_count=12,
            win_rate=0.745,
            geo_total=0.65,
            token_count=847,
        )
        await store.save(snap)

        loaded = await store.load(tool_id="github::search_repositories")
        assert len(loaded) == 1
        assert loaded[0].week_id == "2026-W15"

    async def test_load_empty(self, snapshot_dir: Path) -> None:
        store = SnapshotStore(snapshot_dir=snapshot_dir)
        loaded = await store.load(tool_id="nonexistent")
        assert loaded == []

    async def test_multiple_weeks(self, snapshot_dir: Path) -> None:
        store = SnapshotStore(snapshot_dir=snapshot_dir)
        for week in ("2026-W14", "2026-W15", "2026-W16"):
            await store.save(
                WeeklySnapshot(
                    week_id=week,
                    tool_id="t1",
                    selection_count=10,
                    runner_up_count=5,
                    win_rate=0.67,
                    geo_total=0.5,
                    token_count=100,
                )
            )
        loaded = await store.load(tool_id="t1")
        assert len(loaded) == 3
        assert loaded[0].week_id == "2026-W14"

    async def test_deduplicates_same_week(self, snapshot_dir: Path) -> None:
        store = SnapshotStore(snapshot_dir=snapshot_dir)
        await store.save(
            WeeklySnapshot(
                week_id="2026-W15",
                tool_id="t1",
                selection_count=10,
                runner_up_count=5,
                win_rate=0.67,
                geo_total=0.5,
                token_count=100,
            )
        )
        await store.save(
            WeeklySnapshot(
                week_id="2026-W15",
                tool_id="t1",
                selection_count=20,
                runner_up_count=8,
                win_rate=0.71,
                geo_total=0.6,
                token_count=90,
            )
        )
        loaded = await store.load(tool_id="t1")
        assert len(loaded) == 1
        assert loaded[0].selection_count == 20
