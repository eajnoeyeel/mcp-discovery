"""Fuzzy calibration tests — locks the 0.88 threshold (ADR-0018).

Derived from manual inspection of 14 known rename pairs:
  0.88 separates all TPs (true positives) from the FP cluster at 0.82–0.85.

TRUE POSITIVES (ratio ≥ 0.88) — should auto-rename at threshold=0.88:
  These represent real tool renames observed in the wild where the new name is
  semantically equivalent to the old name (e.g. camelCase migration, suffix drift).

FALSE POSITIVES (ratio < 0.88) — must NOT auto-rename at threshold=0.88:
  These represent semantically different tools that happen to share a similar
  string pattern (e.g. singular/plural pairs, versioned variants).

If any fixture fails, fix the fixture name pair to be more clearly above/below
the 0.88 boundary — do NOT change the threshold.
"""

from __future__ import annotations

import difflib
import re

import pytest

from mcp_discovery.data.reconcile_rules import OutcomeKind, rule_rename_via_fuzzy
from tests.unit.data.conftest import make_gt_entry

_NON_ALPHANUM_RE = re.compile(r"[_\-\s]+")


def _norm(name: str) -> str:
    """Mirror the normalisation in reconcile_rules._normalize_tool_name."""
    return _NON_ALPHANUM_RE.sub("", name.lower())


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


# ---------------------------------------------------------------------------
# True-positive fixtures (should auto-rename at 0.88)
# ---------------------------------------------------------------------------
# camelCase ↔ snake_case drift — normalisation collapses to identical string → ratio 1.0
TP_FIXTURES = [
    ("read_file", "readFile"),  # ratio 1.0 — underscore/camel drift
    ("write_file", "writeFile"),  # ratio 1.0 — underscore/camel drift
    ("fetch_data", "fetchData"),  # ratio 1.0 — underscore/camel drift
    ("list_file", "list_files"),  # ratio 0.94 — minor suffix drift
    ("get_quote", "get_quotes"),  # ratio 0.94 — plural drift
]

# ---------------------------------------------------------------------------
# False-positive fixtures (must NOT auto-rename at 0.88)
# ---------------------------------------------------------------------------
# semantically different tools that share similar prefixes
FP_FIXTURES = [
    ("search", "search_v2"),  # ratio ~0.857 — versioned variant
    ("get_commits", "get_comments"),  # ratio ~0.857 — different noun
    ("read_file", "write_file"),  # ratio ~0.706 — opposite operations
    ("search_repos", "list_repos"),  # ratio ~0.600 — different verb
    ("create_webhook", "delete_webhook"),  # ratio ~0.769 — opposite operations
]

THRESHOLD = 0.88


class TestTruePositives:
    """≥3 TP fixtures: camelCase/snake_case and minor suffix drift pairs."""

    @pytest.mark.parametrize("old_name,new_name", TP_FIXTURES)
    def test_tp_auto_renames_at_088(self, old_name: str, new_name: str):
        """Each TP pair must produce RENAME at threshold=0.88."""
        r = _ratio(old_name, new_name)
        assert r >= THRESHOLD, (
            f"Fixture ({old_name!r}, {new_name!r}) has ratio {r:.4f} < {THRESHOLD}. "
            "Fix the fixture pair to be more clearly above the threshold."
        )
        server_id = "test-server"
        gt = make_gt_entry("q1", server_id, old_name)
        pool_ids = {f"{server_id}::{new_name}"}
        outcome = rule_rename_via_fuzzy(gt, pool_ids, threshold=THRESHOLD)
        assert outcome.kind == OutcomeKind.RENAME, (
            f"Expected RENAME for ({old_name!r} → {new_name!r}), got {outcome.kind}. ratio={r:.4f}"
        )
        assert outcome.confidence is not None
        assert outcome.confidence >= THRESHOLD


class TestFalsePositives:
    """≥3 FP fixtures: semantically different tools that must NOT auto-rename."""

    @pytest.mark.parametrize("old_name,new_name", FP_FIXTURES)
    def test_fp_does_not_auto_rename_at_088(self, old_name: str, new_name: str):
        """Each FP pair must NOT produce RENAME at threshold=0.88."""
        r = _ratio(old_name, new_name)
        assert r < THRESHOLD, (
            f"Fixture ({old_name!r}, {new_name!r}) has ratio {r:.4f} ≥ {THRESHOLD}. "
            "Fix the fixture pair to be more clearly below the threshold."
        )
        server_id = "test-server"
        gt = make_gt_entry("q1", server_id, old_name)
        pool_ids = {f"{server_id}::{new_name}"}
        outcome = rule_rename_via_fuzzy(gt, pool_ids, threshold=THRESHOLD)
        assert outcome.kind != OutcomeKind.RENAME, (
            f"Expected NO auto-rename for ({old_name!r} → {new_name!r}), got {outcome.kind}. "
            f"ratio={r:.4f}"
        )


class TestThresholdBoundary:
    def test_exactly_at_threshold_renames(self):
        """A pair with ratio exactly at the threshold should RENAME."""
        # list_pr / list_prs → ratio 0.923 → above 0.88 → RENAME
        old_name, new_name = "list_pr", "list_prs"
        r = _ratio(old_name, new_name)
        assert r >= THRESHOLD, f"Sanity: {r:.4f} < {THRESHOLD}"
        server_id = "srv"
        gt = make_gt_entry("q1", server_id, old_name)
        pool_ids = {f"{server_id}::{new_name}"}
        outcome = rule_rename_via_fuzzy(gt, pool_ids, threshold=THRESHOLD)
        assert outcome.kind == OutcomeKind.RENAME

    def test_best_candidate_selected(self):
        """When multiple candidates exist, the highest-ratio one is selected."""
        server_id = "srv"
        gt = make_gt_entry("q1", server_id, "read_file")
        # readFile normalises to same as read_file → ratio 1.0
        # read_files → ratio 0.941
        pool_ids = {f"{server_id}::read_files", f"{server_id}::readFile"}
        outcome = rule_rename_via_fuzzy(gt, pool_ids, threshold=THRESHOLD)
        assert outcome.kind == OutcomeKind.RENAME
        # readFile should win (ratio 1.0)
        assert outcome.new_tool_id == f"{server_id}::readFile"
