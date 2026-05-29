"""Unit tests for src/mcp_discovery/data/reconcile_rules.py — one test per rule."""

from __future__ import annotations

from mcp_discovery.data.reconcile_rules import (
    OutcomeKind,
    rule_drop_if_server_missing,
    rule_exact_id_match,
    rule_manual_remap,
    rule_rename_via_fuzzy,
    rule_server_renamed,
)
from tests.unit.data.conftest import make_gt_entry


class TestR2ManualRemap:
    def test_manual_remap_wins(self):
        """R2 should override any fuzzy match when a manual entry exists."""
        gt = make_gt_entry("q1", "foo", "old_tool")
        remaps = {"foo::old_tool": "foo::new_tool"}
        outcome = rule_manual_remap(gt, remaps)
        assert outcome.kind == OutcomeKind.RENAME
        assert outcome.new_tool_id == "foo::new_tool"
        assert outcome.rule == "R2"

    def test_no_manual_entry_returns_no_match(self):
        gt = make_gt_entry("q1", "foo", "some_tool")
        outcome = rule_manual_remap(gt, {})
        assert outcome.kind == OutcomeKind.NO_MATCH

    def test_manual_remap_unrelated_key_no_match(self):
        gt = make_gt_entry("q1", "foo", "tool_a")
        remaps = {"bar::tool_b": "bar::tool_c"}
        outcome = rule_manual_remap(gt, remaps)
        assert outcome.kind == OutcomeKind.NO_MATCH

    def test_manual_remap_wins_over_fuzzy(self):
        """Even when fuzzy match would apply, R2 should take priority."""
        # fuzzy would rename 'get_file' -> 'get_files', but manual says 'get_file' -> 'fetch_file'
        gt = make_gt_entry("q1", "srv", "get_file")
        remaps = {"srv::get_file": "srv::fetch_file"}
        outcome = rule_manual_remap(gt, remaps)
        assert outcome.kind == OutcomeKind.RENAME
        assert outcome.new_tool_id == "srv::fetch_file"


class TestR1ExactIdMatch:
    def test_exact_match_preserves(self):
        gt = make_gt_entry("q1", "github", "list_commits")
        pool_ids = {"github::list_commits", "github::create_issue"}
        outcome = rule_exact_id_match(gt, pool_ids)
        assert outcome.kind == OutcomeKind.PRESERVE
        assert outcome.new_tool_id == "github::list_commits"
        assert outcome.rule == "R1"

    def test_no_match_returns_no_match(self):
        gt = make_gt_entry("q1", "github", "get_commit")
        pool_ids = {"github::list_commits", "github::create_issue"}
        outcome = rule_exact_id_match(gt, pool_ids)
        assert outcome.kind == OutcomeKind.NO_MATCH

    def test_cross_server_not_a_match(self):
        gt = make_gt_entry("q1", "github", "list_repos")
        pool_ids = {"gitlab::list_repos"}  # different server
        outcome = rule_exact_id_match(gt, pool_ids)
        assert outcome.kind == OutcomeKind.NO_MATCH


class TestR4ServerRenamed:
    def test_server_renamed_maps_tool(self):
        gt = make_gt_entry("q1", "old-server", "some_tool")
        server_remaps = {"old-server": "new-server"}
        pool_ids = {"new-server::some_tool"}
        outcome = rule_server_renamed(gt, server_remaps, pool_ids)
        assert outcome.kind == OutcomeKind.RENAME
        assert outcome.new_tool_id == "new-server::some_tool"
        assert outcome.rule == "R4"

    def test_no_server_remap_no_match(self):
        gt = make_gt_entry("q1", "old-server", "some_tool")
        outcome = rule_server_renamed(gt, {}, {"old-server::some_tool"})
        assert outcome.kind == OutcomeKind.NO_MATCH

    def test_server_remap_but_tool_absent_in_pool(self):
        gt = make_gt_entry("q1", "old-server", "missing_tool")
        server_remaps = {"old-server": "new-server"}
        pool_ids = {"new-server::other_tool"}  # missing_tool not present
        outcome = rule_server_renamed(gt, server_remaps, pool_ids)
        assert outcome.kind == OutcomeKind.NO_MATCH

    def test_server_renamed_maps_all_tools_per_server(self):
        """All GT rows pointing to old_server should be remapped via R4."""
        entries = [make_gt_entry(f"q{i}", "old-server", f"tool_{i}") for i in range(3)]
        server_remaps = {"old-server": "new-server"}
        pool_ids = {f"new-server::tool_{i}" for i in range(3)}
        outcomes = [rule_server_renamed(e, server_remaps, pool_ids) for e in entries]
        assert all(o.kind == OutcomeKind.RENAME for o in outcomes)
        assert [o.new_tool_id for o in outcomes] == [f"new-server::tool_{i}" for i in range(3)]


class TestR3FuzzyRename:
    def test_auto_rename_above_threshold(self):
        """readFile and read_file normalise identically → ratio = 1.0 → RENAME."""
        gt = make_gt_entry("q1", "fs", "read_file")
        pool_ids = {"fs::readFile"}
        outcome = rule_rename_via_fuzzy(gt, pool_ids, threshold=0.88)
        assert outcome.kind == OutcomeKind.RENAME
        assert outcome.new_tool_id == "fs::readFile"
        assert outcome.confidence is not None
        assert outcome.confidence >= 0.88

    def test_review_queue_in_band(self):
        """search vs search_v2 → ratio 0.857 → in (0.80, 0.88) band → REVIEW_QUEUE."""
        gt = make_gt_entry("q1", "api", "search")
        pool_ids = {"api::search_v2"}
        outcome = rule_rename_via_fuzzy(gt, pool_ids, threshold=0.88, review_band_low=0.80)
        assert outcome.kind == OutcomeKind.REVIEW_QUEUE
        assert outcome.confidence is not None
        assert 0.80 <= outcome.confidence < 0.88

    def test_below_band_no_match(self):
        """Completely dissimilar names → NO_MATCH."""
        gt = make_gt_entry("q1", "api", "create_user")
        pool_ids = {"api::delete_repository"}
        outcome = rule_rename_via_fuzzy(gt, pool_ids, threshold=0.88)
        assert outcome.kind == OutcomeKind.NO_MATCH

    def test_only_considers_same_server(self):
        """Fuzzy match should not cross server boundaries."""
        gt = make_gt_entry("q1", "server_a", "get_user")
        pool_ids = {"server_b::getUser"}  # same name but different server
        outcome = rule_rename_via_fuzzy(gt, pool_ids, threshold=0.88)
        assert outcome.kind == OutcomeKind.NO_MATCH

    def test_empty_pool_no_match(self):
        gt = make_gt_entry("q1", "srv", "some_tool")
        outcome = rule_rename_via_fuzzy(gt, set(), threshold=0.88)
        assert outcome.kind == OutcomeKind.NO_MATCH

    def test_r3_fuzzy_review_band_080_to_088(self):
        """get_commits vs get_comments → 0.857 → REVIEW_QUEUE."""
        gt = make_gt_entry("q1", "gh", "get_commits")
        pool_ids = {"gh::get_comments"}
        outcome = rule_rename_via_fuzzy(gt, pool_ids, threshold=0.88, review_band_low=0.80)
        assert outcome.kind == OutcomeKind.REVIEW_QUEUE


class TestR5DropIfServerMissing:
    def test_drops_when_server_absent(self):
        gt = make_gt_entry("q1", "yahoo-finance", "get_price")
        live_ids: set[str] = {"github", "gitlab"}
        outcome = rule_drop_if_server_missing(gt, live_ids, "UNREACHABLE", probe_sha="abc123")
        assert outcome.kind == OutcomeKind.DROP
        assert outcome.rule == "R5"
        assert "UNREACHABLE" in outcome.reason
        assert "abc123" in outcome.reason

    def test_preserves_when_server_present(self):
        gt = make_gt_entry("q1", "github", "list_commits")
        live_ids = {"github"}
        outcome = rule_drop_if_server_missing(gt, live_ids, "whatever")
        assert outcome.kind == OutcomeKind.PRESERVE

    def test_notes_suffix_format(self):
        """Drop note format: [reconcile: <reason> sha=<sha>]."""
        gt = make_gt_entry("q1", "missing-server", "a_tool")
        outcome = rule_drop_if_server_missing(gt, set(), "not_probed", probe_sha="deadbeef")
        assert "[reconcile: not_probed sha=deadbeef]" == outcome.reason

    def test_notes_without_sha(self):
        """Without probe_sha, the note should still be formatted correctly."""
        gt = make_gt_entry("q1", "missing-server", "a_tool")
        outcome = rule_drop_if_server_missing(gt, set(), "not_probed")
        assert "[reconcile: not_probed]" == outcome.reason
        assert "sha=" not in outcome.reason


class TestRuleOrdering:
    def test_ordering_r2_then_r1_then_r4_then_r3_then_r5(self):
        """Verify rule application ordering from gt_reconciler perspective."""
        # GT row that could match R1 (exact) and has a manual remap (R2)
        # R2 must win.
        from mcp_discovery.data.gt_reconciler import _apply_rules

        gt = make_gt_entry("q1", "srv", "old_tool")
        pool_ids = {"srv::old_tool", "srv::old_tool_v2"}  # R1 would preserve
        manual_remaps = {"srv::old_tool": "srv::manual_remap"}  # R2 must win
        live_ids = {"srv"}

        outcome = _apply_rules(
            gt_row=gt,
            pool_tool_ids=pool_ids,
            live_server_ids=live_ids,
            manual_remaps=manual_remaps,
            server_remaps={},
            probes=[],
        )
        assert outcome.rule == "R2"
        assert outcome.new_tool_id == "srv::manual_remap"

    def test_r1_fires_when_no_manual_remap(self):
        """When no manual remap, exact match (R1) should fire."""
        from mcp_discovery.data.gt_reconciler import _apply_rules

        gt = make_gt_entry("q1", "srv", "exact_tool")
        pool_ids = {"srv::exact_tool"}
        outcome = _apply_rules(
            gt_row=gt,
            pool_tool_ids=pool_ids,
            live_server_ids={"srv"},
            manual_remaps={},
            server_remaps={},
            probes=[],
        )
        assert outcome.rule == "R1"
        assert outcome.kind == OutcomeKind.PRESERVE

    def test_r5_fires_as_last_resort(self):
        """When no rule matches and server is absent, R5 fires."""
        from mcp_discovery.data.gt_reconciler import _apply_rules

        gt = make_gt_entry("q1", "missing-srv", "some_tool")
        outcome = _apply_rules(
            gt_row=gt,
            pool_tool_ids=set(),
            live_server_ids=set(),
            manual_remaps={},
            server_remaps={},
            probes=[],
        )
        assert outcome.rule == "R5"
        assert outcome.kind == OutcomeKind.DROP
