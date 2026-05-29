"""Reconciliation rules for GT↔pool alignment (ADR-0018).

Five pure functions, one per rule, applied in order R2→R1→R4→R3→R5.
All functions are side-effect-free: they accept immutable data and return
a RuleOutcome describing the proposed action.

Threshold 0.88 in rule_rename_via_fuzzy was derived from manual inspection
of 14 known rename pairs in the manual_remaps.yaml seed set; 0.88 separates
all 14 TPs from the FP cluster at 0.82–0.85. Locked by
tests/unit/data/test_reconcile_fuzzy_calibration.py.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from enum import Enum

from mcp_discovery.models.core import GroundTruthEntry

# ---------------------------------------------------------------------------
# RuleOutcome — typed result of a single rule evaluation
# ---------------------------------------------------------------------------


class OutcomeKind(str, Enum):
    """Possible outcomes from applying one reconcile rule."""

    PRESERVE = "preserve"  # R1: exact match — keep as-is
    RENAME = "rename"  # R2 / R3 / R4: replace tool_id
    DROP = "drop"  # R5: server missing, remove GT row
    REVIEW_QUEUE = "review_queue"  # R3: fuzzy 0.80–0.88 band — needs human review
    NO_MATCH = "no_match"  # Rule did not apply — try next rule


@dataclass(frozen=True)
class RuleOutcome:
    """Result of applying a single reconcile rule to a GT row.

    If kind is RENAME, new_tool_id holds the replacement.
    If kind is REVIEW_QUEUE, new_tool_id holds the candidate and confidence is set.
    If kind is NO_MATCH, downstream rules should be tried.
    """

    kind: OutcomeKind
    query_id: str
    old_tool_id: str
    new_tool_id: str | None = None
    confidence: float | None = None
    rule: str = ""
    reason: str = ""
    probe_sha: str | None = None


# ---------------------------------------------------------------------------
# Name normalisation helper (shared by fuzzy rule)
# ---------------------------------------------------------------------------

_NON_ALPHANUM_RE = re.compile(r"[_\-\s]+")


def _normalize_tool_name(name: str) -> str:
    """Lower-case and strip underscores/hyphens for fuzzy comparison."""
    # Extract just the tool_name part if a full tool_id is supplied
    if "::" in name:
        name = name.split("::")[-1]
    return _NON_ALPHANUM_RE.sub("", name.lower())


# ---------------------------------------------------------------------------
# Rule R2 — manual_remap (highest priority)
# ---------------------------------------------------------------------------


def rule_manual_remap(
    gt_row: GroundTruthEntry,
    manual_remaps: dict[str, str],
) -> RuleOutcome:
    """R2: Apply an explicit tool_id remap from manual_remaps.yaml.

    manual_remaps maps old_tool_id → new_tool_id.  If the GT row's
    correct_tool_id is present in the map, the rename is applied unconditionally.
    Manual always wins (highest priority in R2→R1→R4→R3→R5 ordering).

    Args:
        gt_row: The GT entry to evaluate.
        manual_remaps: Mapping of old_tool_id → new_tool_id from manual_remaps.yaml.

    Returns:
        RENAME outcome if a mapping exists, NO_MATCH otherwise.
    """
    old_id = gt_row.correct_tool_id
    new_id = manual_remaps.get(old_id)
    if new_id is not None:
        return RuleOutcome(
            kind=OutcomeKind.RENAME,
            query_id=gt_row.query_id,
            old_tool_id=old_id,
            new_tool_id=new_id,
            rule="R2",
            reason=f"manual_remap: {old_id} → {new_id}",
        )
    return RuleOutcome(
        kind=OutcomeKind.NO_MATCH,
        query_id=gt_row.query_id,
        old_tool_id=old_id,
        rule="R2",
        reason="no manual remap entry",
    )


# ---------------------------------------------------------------------------
# Rule R1 — exact_id_match
# ---------------------------------------------------------------------------


def rule_exact_id_match(
    gt_row: GroundTruthEntry,
    pool_tool_ids: set[str],
) -> RuleOutcome:
    """R1: Preserve a GT row when its correct_tool_id exactly matches a pool tool.

    Args:
        gt_row: The GT entry to evaluate.
        pool_tool_ids: Set of tool_id strings currently in the pool.

    Returns:
        PRESERVE outcome if the tool_id is in the pool, NO_MATCH otherwise.
    """
    old_id = gt_row.correct_tool_id
    if old_id in pool_tool_ids:
        return RuleOutcome(
            kind=OutcomeKind.PRESERVE,
            query_id=gt_row.query_id,
            old_tool_id=old_id,
            new_tool_id=old_id,
            rule="R1",
            reason="exact match in pool",
        )
    return RuleOutcome(
        kind=OutcomeKind.NO_MATCH,
        query_id=gt_row.query_id,
        old_tool_id=old_id,
        rule="R1",
        reason="tool_id not found in pool",
    )


# ---------------------------------------------------------------------------
# Rule R4 — server_renamed
# ---------------------------------------------------------------------------


def rule_server_renamed(
    gt_row: GroundTruthEntry,
    server_remaps: dict[str, str],
    pool_tool_ids: set[str],
) -> RuleOutcome:
    """R4: Apply a server-level rename from manual_remaps.yaml server remaps.

    If the GT row's correct_server_id appears in server_remaps, the tool_id
    is rewritten to use the new server_id. The rewritten tool_id must exist
    in the pool to be accepted; otherwise NO_MATCH is returned.

    Args:
        gt_row: The GT entry to evaluate.
        server_remaps: Mapping of old_server_id → new_server_id.
        pool_tool_ids: Set of tool_id strings currently in the pool.

    Returns:
        RENAME outcome if the server remap produces a valid pool match, NO_MATCH otherwise.
    """
    old_id = gt_row.correct_tool_id
    old_server = gt_row.correct_server_id
    new_server = server_remaps.get(old_server)
    if new_server is None:
        return RuleOutcome(
            kind=OutcomeKind.NO_MATCH,
            query_id=gt_row.query_id,
            old_tool_id=old_id,
            rule="R4",
            reason="no server remap entry",
        )
    tool_name = old_id.split("::", 1)[-1] if "::" in old_id else old_id
    candidate_id = f"{new_server}::{tool_name}"
    if candidate_id in pool_tool_ids:
        return RuleOutcome(
            kind=OutcomeKind.RENAME,
            query_id=gt_row.query_id,
            old_tool_id=old_id,
            new_tool_id=candidate_id,
            rule="R4",
            reason=(
                f"server_renamed: {old_server} → {new_server}, tool {tool_name} verified in pool"
            ),
        )
    return RuleOutcome(
        kind=OutcomeKind.NO_MATCH,
        query_id=gt_row.query_id,
        old_tool_id=old_id,
        rule="R4",
        reason=(
            f"server remap {old_server} → {new_server} found, "
            f"but candidate {candidate_id} not in pool"
        ),
    )


# ---------------------------------------------------------------------------
# Rule R3 — rename_via_fuzzy
# ---------------------------------------------------------------------------


def rule_rename_via_fuzzy(
    gt_row: GroundTruthEntry,
    pool_tool_ids: set[str],
    threshold: float = 0.88,
    review_band_low: float = 0.80,
) -> RuleOutcome:
    """R3: Fuzzy-match the GT tool name against pool tools on the same server.

    Uses difflib.SequenceMatcher.ratio() on normalised names (lowercased,
    stripped underscores/hyphens).

    Threshold 0.88 was derived from manual inspection of 14 known rename pairs;
    0.88 separates all 14 TPs from the FP cluster at 0.82–0.85.
    Locked by tests/unit/data/test_reconcile_fuzzy_calibration.py.

    - ratio ≥ threshold  → RENAME (auto-apply)
    - review_band_low ≤ ratio < threshold → REVIEW_QUEUE (human review required)
    - ratio < review_band_low → NO_MATCH

    Args:
        gt_row: The GT entry to evaluate.
        pool_tool_ids: Set of tool_id strings currently in the pool.
        threshold: Minimum SequenceMatcher ratio for auto-rename (default 0.88).
        review_band_low: Lower bound of the review band (default 0.80).

    Returns:
        RENAME, REVIEW_QUEUE, or NO_MATCH outcome.
    """
    old_id = gt_row.correct_tool_id
    old_server = gt_row.correct_server_id
    old_tool_name = old_id.split("::", 1)[-1] if "::" in old_id else old_id
    norm_old = _normalize_tool_name(old_tool_name)

    # Only consider tools on the same server (server_id prefix match)
    same_server_tools = [tid for tid in pool_tool_ids if tid.startswith(f"{old_server}::")]

    best_ratio = 0.0
    best_candidate: str | None = None

    for candidate_id in same_server_tools:
        candidate_name = candidate_id.split("::", 1)[-1]
        norm_candidate = _normalize_tool_name(candidate_name)
        ratio = difflib.SequenceMatcher(None, norm_old, norm_candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_candidate = candidate_id

    if best_candidate is None or best_ratio < review_band_low:
        return RuleOutcome(
            kind=OutcomeKind.NO_MATCH,
            query_id=gt_row.query_id,
            old_tool_id=old_id,
            rule="R3",
            reason=f"no fuzzy match above band floor {review_band_low:.2f}",
        )

    if best_ratio >= threshold:
        return RuleOutcome(
            kind=OutcomeKind.RENAME,
            query_id=gt_row.query_id,
            old_tool_id=old_id,
            new_tool_id=best_candidate,
            confidence=best_ratio,
            rule="R3",
            reason=f"fuzzy rename: ratio={best_ratio:.4f} ≥ {threshold:.2f}",
        )

    # review_band_low ≤ ratio < threshold
    return RuleOutcome(
        kind=OutcomeKind.REVIEW_QUEUE,
        query_id=gt_row.query_id,
        old_tool_id=old_id,
        new_tool_id=best_candidate,
        confidence=best_ratio,
        rule="R3",
        reason=(
            f"fuzzy review: ratio={best_ratio:.4f} in [{review_band_low:.2f}, {threshold:.2f}) "
            "— requires human review before application"
        ),
    )


# ---------------------------------------------------------------------------
# Rule R5 — drop_if_server_missing
# ---------------------------------------------------------------------------


def rule_drop_if_server_missing(
    gt_row: GroundTruthEntry,
    live_server_ids: set[str],
    reason: str,
    probe_sha: str | None = None,
) -> RuleOutcome:
    """R5: Drop a GT row when the referenced server is absent from the pool.

    This is the terminal rule.  If the server is not in the pool AND the probe
    failed or was not attempted, the GT row should be dropped to eliminate
    dangling references that break the CI alignment validator.

    Args:
        gt_row: The GT entry to evaluate.
        live_server_ids: Set of server_ids currently in the pool.
        reason: Human-readable explanation (e.g. probe error kind or "not_in_pool").
        probe_sha: Optional spec_hash of the ProbeResult that informed this drop.

    Returns:
        DROP outcome if the server is absent, PRESERVE if it is present.
    """
    old_id = gt_row.correct_tool_id
    server = gt_row.correct_server_id
    if server not in live_server_ids:
        sha_suffix = f" sha={probe_sha}" if probe_sha else ""
        drop_note = f"[reconcile: {reason}{sha_suffix}]"
        return RuleOutcome(
            kind=OutcomeKind.DROP,
            query_id=gt_row.query_id,
            old_tool_id=old_id,
            rule="R5",
            reason=drop_note,
            probe_sha=probe_sha,
        )
    return RuleOutcome(
        kind=OutcomeKind.PRESERVE,
        query_id=gt_row.query_id,
        old_tool_id=old_id,
        new_tool_id=old_id,
        rule="R5",
        reason="server present in pool — preserving by default",
    )
