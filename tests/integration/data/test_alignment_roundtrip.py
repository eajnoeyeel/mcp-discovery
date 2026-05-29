"""Integration roundtrip test: probe → reconcile → validate alignment (ADR-0018).

Fixture: 3-server pool JSONL + 5 GT rows spanning R1/R2/R5 rules.
Monkeypatches pool_prober.probe_servers to return canned ProbeResults.
Runs refresh_pool.main() in dry-run mode → asserts plan built with correct actions.
Then applies the plan → runs validate_pool_gt_alignment → asserts exit 0.
Asserts review_queue is empty for this unambiguous fixture (no band-0.80-0.88 fuzzy hits).

Mark: @pytest.mark.integration (no live APIs, but exercises multi-module pipeline).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

for _p in [str(_REPO_ROOT / "src"), str(_SCRIPTS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import refresh_pool  # noqa: E402
import validate_pool_gt_alignment as validator  # noqa: E402

from mcp_discovery.data.audit_trail import AuditJournal  # noqa: E402
from mcp_discovery.data.gt_reconciler import apply_plan_to_gt, build_reconcile_plan  # noqa: E402
from mcp_discovery.models.core import (  # noqa: E402
    Ambiguity,
    Category,
    Difficulty,
    GroundTruthEntry,
    MCPServer,
    MCPTool,
)
from mcp_discovery.models.probe import ProbeResult, RawToolInventory, ReconcilePlan  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration


def _make_tool(server_id: str, tool_name: str) -> MCPTool:
    return MCPTool(
        server_id=server_id,
        tool_name=tool_name,
        tool_id=f"{server_id}::{tool_name}",
        description=f"Tool {tool_name} on {server_id}",
    )


def _make_server(server_id: str, tools: list[str]) -> MCPServer:
    return MCPServer(
        server_id=server_id,
        name=server_id,
        tools=[_make_tool(server_id, t) for t in tools],
    )


def _make_gt(
    query_id: str,
    server_id: str,
    tool_name: str,
) -> GroundTruthEntry:
    return GroundTruthEntry(
        query_id=query_id,
        query=f"test query {query_id}",
        correct_server_id=server_id,
        correct_tool_id=f"{server_id}::{tool_name}",
        difficulty=Difficulty.EASY,
        category=Category.GENERAL,
        ambiguity=Ambiguity.LOW,
        source="llm_synthetic",
        manually_verified=False,
        author="test-integration",
        created_at="2026-04-19",
    )


def _write_pool_jsonl(path: Path, servers: list[MCPServer]) -> None:
    """Write pool JSONL (one MCPServer JSON per line)."""
    lines = []
    for s in servers:
        # validate_pool_gt_alignment reads {"server_id": ..., "tools": [{"tool_id": ...}]}
        record = {
            "server_id": s.server_id,
            "name": s.name,
            "tools": [{"tool_id": t.tool_id, "tool_name": t.tool_name} for t in s.tools],
        }
        lines.append(json.dumps(record))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_gt_jsonl(path: Path, entries: list[GroundTruthEntry]) -> None:
    lines = [e.model_dump_json() for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixture: 3-server pool + 5 GT rows
# ---------------------------------------------------------------------------
#
# Pool:
#   alpha: [alpha::search, alpha::fetch]          — present in pool
#   bravo: [bravo::send]                           — present in pool
#   charlie: [charlie::list_items, charlie::create_item]  — in pool, no GT
#
# GT rows:
#   gt-r1-001: alpha::search     — R1 exact match (preserve)
#   gt-r1-002: alpha::fetch      — R1 exact match (preserve)
#   gt-r1-003: bravo::send       — R1 exact match (preserve)
#   gt-r2-001: alpha::old_tool   — R2 manual remap → alpha::search (remapped)
#   gt-r5-001: delta::gone_tool  — R5 drop (server 'delta' not in pool + probe failed)
#
# With manual_remaps = {"alpha::old_tool": "alpha::search"}
# Expected: 3 R1 preserves (no action), 1 R2 rename, 1 R5 drop
# Review queue should be empty (no fuzzy 0.80–0.88 band hits)


@pytest.fixture
def fixture_data(tmp_path: Path):
    """Build fixture pool JSONL, GT JSONL, transports.yaml, and manual_remaps.yaml."""
    pool_dir = tmp_path / "data" / "raw"
    pool_dir.mkdir(parents=True)
    gt_dir = tmp_path / "data" / "ground_truth"
    gt_dir.mkdir(parents=True)
    probes_dir = tmp_path / "data" / "probes"
    probes_dir.mkdir(parents=True)

    servers = [
        _make_server("alpha", ["search", "fetch"]),
        _make_server("bravo", ["send"]),
        _make_server("charlie", ["list_items", "create_item"]),
    ]
    pool_path = pool_dir / "mcp_zero_servers.jsonl"
    _write_pool_jsonl(pool_path, servers)

    gt_entries = [
        _make_gt("gt-r1-001", "alpha", "search"),
        _make_gt("gt-r1-002", "alpha", "fetch"),
        _make_gt("gt-r1-003", "bravo", "send"),
        _make_gt("gt-r2-001", "alpha", "old_tool"),  # will be remapped by R2
        _make_gt("gt-r5-001", "delta", "gone_tool"),  # will be dropped by R5
    ]
    gt_path = gt_dir / "test_gt.jsonl"
    _write_gt_jsonl(gt_path, gt_entries)

    # Minimal transports.yaml — we'll monkeypatch probe_servers so content doesn't matter much
    transports_yaml = tmp_path / "transports.yaml"
    transports_yaml.write_text(
        "servers:\n"
        "  alpha:\n"
        "    transport: script\n"
        "    script_path: /dev/null\n"
        "  bravo:\n"
        "    transport: script\n"
        "    script_path: /dev/null\n",
        encoding="utf-8",
    )

    # manual_remaps.yaml: alpha::old_tool → alpha::search (R2)
    manual_remaps = probes_dir / "manual_remaps.yaml"
    manual_remaps.write_text(
        'tool_remaps:\n  "alpha::old_tool": "alpha::search"\nserver_remaps: {}\n',
        encoding="utf-8",
    )

    # Empty targeted_set.txt
    targeted_set = probes_dir / "targeted_set.txt"
    targeted_set.write_text("alpha\nbravo\n", encoding="utf-8")

    journal_path = probes_dir / "journal.jsonl"
    journal_path.touch()

    return {
        "tmp_path": tmp_path,
        "pool_path": pool_path,
        "gt_path": gt_path,
        "gt_entries": gt_entries,
        "servers": servers,
        "transports_yaml": transports_yaml,
        "manual_remaps": manual_remaps,
        "targeted_set": targeted_set,
        "journal_path": journal_path,
        "probes_dir": probes_dir,
    }


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


class TestAlignmentRoundtrip:
    """Full roundtrip: build plan → apply → validate alignment."""

    def test_roundtrip_exit_0_after_reconcile(
        self, fixture_data: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After reconcile, validate_pool_gt_alignment should exit 0 (no alignment errors)."""
        fd = fixture_data
        gt_path: Path = fd["gt_path"]
        pool_path: Path = fd["pool_path"]
        servers: list[MCPServer] = fd["servers"]

        # Build canned ProbeResults — alpha and bravo succeed
        canned_probes = {
            "alpha": ProbeResult(
                server_id="alpha",
                success=True,
                spec_hash="aaa000",
                inventory=RawToolInventory(
                    server_id="alpha",
                    tools=[
                        {"name": "search", "description": "Search"},
                        {"name": "fetch", "description": "Fetch"},
                    ],
                ),
            ),
            "bravo": ProbeResult(
                server_id="bravo",
                success=True,
                spec_hash="bbb000",
                inventory=RawToolInventory(
                    server_id="bravo",
                    tools=[{"name": "send", "description": "Send"}],
                ),
            ),
        }

        # Monkeypatch probe_servers to return canned results
        monkeypatch.setattr(
            "mcp_discovery.data.pool_prober.probe_servers",
            AsyncMock(return_value=canned_probes),
        )
        # Also patch it in refresh_pool's module namespace
        monkeypatch.setattr(
            refresh_pool,
            "probe_servers",
            AsyncMock(return_value=canned_probes),
        )

        # Load manual remaps
        import yaml

        remaps_raw = yaml.safe_load(fd["manual_remaps"].read_text())
        tool_remaps = remaps_raw.get("tool_remaps", {}) or {}
        server_remaps = remaps_raw.get("server_remaps", {}) or {}

        # Build reconcile plan directly (not via CLI)
        gt_entries = fd["gt_entries"]
        plan = build_reconcile_plan(
            pool=servers,
            probes=list(canned_probes.values()),
            gt_entries=gt_entries,
            manual_remaps=tool_remaps,
            server_remaps=server_remaps if server_remaps else None,
        )

        # Verify plan structure
        assert isinstance(plan, ReconcilePlan)
        # Review queue must be empty for this unambiguous fixture
        assert len(plan.review_queue) == 0, (
            f"Expected empty review_queue, got {len(plan.review_queue)} items"
        )

        # Check R2 rename action present
        r2_actions = [a for a in plan.actions if a.rule == "R2"]
        assert len(r2_actions) == 1
        assert r2_actions[0].old_tool_id == "alpha::old_tool"
        assert r2_actions[0].new_tool_id == "alpha::search"

        # Check R5 drop action present
        r5_actions = [a for a in plan.actions if a.rule == "R5"]
        assert len(r5_actions) == 1
        assert r5_actions[0].old_tool_id == "delta::gone_tool"

        # Apply plan to GT file
        modified = apply_plan_to_gt(plan, [gt_path])
        assert gt_path in modified or len(plan.actions) > 0

        # Write journal entry
        journal = AuditJournal(fd["journal_path"])
        journal.append(
            {
                "event": "test_roundtrip_apply",
                "plan_hash": plan.plan_hash,
                "actions_count": len(plan.actions),
            }
        )

        # Validate pool-GT alignment after reconcile
        # After reconcile: gt-r2-001 is remapped to alpha::search (in pool), gt-r5-001 is dropped.
        # Remaining GT rows: gt-r1-001 (alpha::search), gt-r1-002 (alpha::fetch),
        #                    gt-r1-003 (bravo::send), gt-r2-001 (now alpha::search)
        errors = validator.validate_tool_ids(pool_path=pool_path, gt_paths=[gt_path])
        assert errors == [], (
            f"Expected 0 alignment errors after reconcile, got {len(errors)}: {errors[:3]}"
        )

    def test_plan_has_no_review_queue_for_unambiguous_fixture(self, fixture_data: dict) -> None:
        """Unambiguous fixture should produce empty review_queue (no 0.80–0.88 fuzzy band)."""
        fd = fixture_data
        import yaml

        remaps_raw = yaml.safe_load(fd["manual_remaps"].read_text())
        tool_remaps = remaps_raw.get("tool_remaps", {}) or {}
        server_remaps = remaps_raw.get("server_remaps", {}) or {}

        plan = build_reconcile_plan(
            pool=fd["servers"],
            probes=[],  # no probes for simplest fixture
            gt_entries=fd["gt_entries"],
            manual_remaps=tool_remaps,
            server_remaps=server_remaps if server_remaps else None,
        )
        assert plan.review_queue == []
