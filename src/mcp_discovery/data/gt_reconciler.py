"""GT reconciler — builds and applies ReconcilePlans (ADR-0018).

Orchestrates the 5 reconcile rules in the mandatory order R2→R1→R4→R3→R5
and produces a ReconcilePlan suitable for apply_gt_reconcile.py to consume.

Idempotence invariant: `build_reconcile_plan(reconcile(x)) == build_reconcile_plan(x)`
when manual_remaps is stable — i.e. applying the same plan twice produces
bit-identical output.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from mcp_discovery.data.reconcile_rules import (
    OutcomeKind,
    RuleOutcome,
    rule_drop_if_server_missing,
    rule_exact_id_match,
    rule_manual_remap,
    rule_rename_via_fuzzy,
    rule_server_renamed,
)
from mcp_discovery.models.core import GroundTruthEntry, MCPServer
from mcp_discovery.models.probe import ProbeResult, ReconcileAction, ReconcilePlan

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_pool_tool_ids(pool: list[MCPServer]) -> set[str]:
    """Return the flat set of all tool_ids in the pool."""
    ids: set[str] = set()
    for server in pool:
        for tool in server.tools:
            ids.add(tool.tool_id)
    return ids


def _build_pool_server_ids(pool: list[MCPServer]) -> set[str]:
    """Return the set of server_ids in the pool."""
    return {s.server_id for s in pool}


def _build_live_server_ids(pool: list[MCPServer], probes: list[ProbeResult]) -> set[str]:
    """Return server_ids that are either in the pool OR probed successfully."""
    ids = _build_pool_server_ids(pool)
    for pr in probes:
        if pr.success:
            ids.add(pr.server_id)
    return ids


def _probe_sha_for_server(probes: list[ProbeResult], server_id: str) -> str | None:
    """Return the spec_hash from the most recent probe for a given server_id."""
    for pr in reversed(probes):
        if pr.server_id == server_id:
            return pr.spec_hash
    return None


def _probe_failure_reason(probes: list[ProbeResult], server_id: str) -> str:
    """Return a short reason string from the probe failure, or 'not_probed'."""
    for pr in reversed(probes):
        if pr.server_id == server_id:
            if pr.error_kind is not None:
                return pr.error_kind.value
            return "probe_failed"
    return "not_probed"


def _outcome_to_action(outcome: RuleOutcome) -> ReconcileAction:
    """Convert a RuleOutcome to a ReconcileAction for inclusion in the plan."""
    return ReconcileAction(
        rule=outcome.rule,  # type: ignore[arg-type]
        query_id=outcome.query_id,
        old_tool_id=outcome.old_tool_id,
        new_tool_id=outcome.new_tool_id,
        confidence=outcome.confidence,
        notes=outcome.reason,
        probe_sha=outcome.probe_sha,
    )


def _compute_plan_hash(actions: list[ReconcileAction]) -> str:
    """Compute a stable SHA-256 hash over the serialised action list."""
    payload = json.dumps(
        [a.model_dump(mode="json") for a in actions],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Primary reconcile function
# ---------------------------------------------------------------------------


def build_reconcile_plan(
    pool: list[MCPServer],
    probes: list[ProbeResult],
    gt_entries: list[GroundTruthEntry],
    manual_remaps: dict[str, str],
    server_remaps: dict[str, str] | None = None,
) -> ReconcilePlan:
    """Build a ReconcilePlan by applying rules R2→R1→R4→R3→R5 to every GT entry.

    Rules are applied in priority order; the first matching rule wins.

    Args:
        pool:          List of MCPServer objects currently in the pool.
        probes:        List of ProbeResult objects from the probe run (may be empty).
        gt_entries:    List of GroundTruthEntry objects to reconcile.
        manual_remaps: dict mapping old_tool_id → new_tool_id (R2 tool-level remaps).
        server_remaps: dict mapping old_server_id → new_server_id (R4 server-level remaps).
                       If None, R4 is skipped.

    Returns:
        A ReconcilePlan containing all proposed actions and a review_queue for
        fuzzy matches in the 0.80–0.88 band.
    """
    if server_remaps is None:
        server_remaps = {}

    pool_tool_ids = _build_pool_tool_ids(pool)
    live_server_ids = _build_live_server_ids(pool, probes)

    actions: list[ReconcileAction] = []
    review_queue: list[ReconcileAction] = []
    probe_results_map: dict[str, str] = {pr.server_id: pr.spec_hash for pr in probes}

    for gt_row in gt_entries:
        outcome = _apply_rules(
            gt_row=gt_row,
            pool_tool_ids=pool_tool_ids,
            live_server_ids=live_server_ids,
            manual_remaps=manual_remaps,
            server_remaps=server_remaps,
            probes=probes,
        )

        if outcome.kind == OutcomeKind.REVIEW_QUEUE:
            review_queue.append(_outcome_to_action(outcome))
            logger.info(
                f"[R3 review] {gt_row.query_id}: {outcome.old_tool_id} → {outcome.new_tool_id} "
                f"(confidence={outcome.confidence:.4f})"
            )
        elif outcome.kind != OutcomeKind.PRESERVE:
            actions.append(_outcome_to_action(outcome))
            logger.info(
                f"[{outcome.rule}] {gt_row.query_id}: {outcome.kind.value} "
                f"{outcome.old_tool_id} → {outcome.new_tool_id}"
            )

    plan_hash = _compute_plan_hash(actions)
    return ReconcilePlan(
        plan_hash=plan_hash,
        created_at=datetime.now(tz=timezone.utc),
        actions=actions,
        review_queue=review_queue,
        probe_results=probe_results_map,
    )


def _apply_rules(
    gt_row: GroundTruthEntry,
    pool_tool_ids: set[str],
    live_server_ids: set[str],
    manual_remaps: dict[str, str],
    server_remaps: dict[str, str],
    probes: list[ProbeResult],
) -> RuleOutcome:
    """Apply rules R2→R1→R4→R3→R5 in priority order; return the first match."""
    # R2: manual remap (highest priority)
    outcome = rule_manual_remap(gt_row, manual_remaps)
    if outcome.kind != OutcomeKind.NO_MATCH:
        return outcome

    # R1: exact match
    outcome = rule_exact_id_match(gt_row, pool_tool_ids)
    if outcome.kind != OutcomeKind.NO_MATCH:
        return outcome

    # R4: server renamed
    outcome = rule_server_renamed(gt_row, server_remaps, pool_tool_ids)
    if outcome.kind != OutcomeKind.NO_MATCH:
        return outcome

    # R3: fuzzy rename
    outcome = rule_rename_via_fuzzy(gt_row, pool_tool_ids)
    if outcome.kind != OutcomeKind.NO_MATCH:
        return outcome

    # R5: drop if server missing
    probe_sha = _probe_sha_for_server(probes, gt_row.correct_server_id)
    reason = _probe_failure_reason(probes, gt_row.correct_server_id)
    return rule_drop_if_server_missing(gt_row, live_server_ids, reason, probe_sha)


# ---------------------------------------------------------------------------
# Plan application helpers
# ---------------------------------------------------------------------------


def apply_plan_to_gt(
    plan: ReconcilePlan,
    gt_paths: list[Path],
) -> list[Path]:
    """Apply a ReconcilePlan to GT JSONL files in-place.

    Writes `*.bak-pre-reconcile-<plan_hash>` backups BEFORE modifying each file.
    The backup naming follows the ADR-0013 precedent (mcp_atlas.jsonl.bak-pre-filter).

    Idempotence: if the plan contains no actions for a file, the file is not modified.
    Applying the same plan twice produces bit-identical output because:
      - R1 preserves already-exact rows
      - R2/R4 remaps are idempotent when manual_remaps is stable
      - R3 fuzzy matches converge after the first application

    Args:
        plan:     The ReconcilePlan to apply.
        gt_paths: List of GT JSONL file paths to modify.

    Returns:
        List of modified file paths (only files that were actually changed).
    """
    action_by_query_id: dict[str, ReconcileAction] = {a.query_id: a for a in plan.actions}
    modified: list[Path] = []

    for gt_path in gt_paths:
        if not gt_path.exists():
            logger.warning(f"apply_plan_to_gt: {gt_path} does not exist — skipping")
            continue

        raw_lines = gt_path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines: list[str] = []
        changed = False

        for line in raw_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            try:
                row_dict = json.loads(stripped)
            except json.JSONDecodeError:
                new_lines.append(line)
                continue

            query_id = row_dict.get("query_id", "")
            action = action_by_query_id.get(query_id)

            if action is None:
                new_lines.append(line)
                continue

            if action.rule == "R5":
                # Drop the row — do not append to new_lines
                changed = True
                logger.info(f"apply_plan_to_gt: dropping {query_id} ({action.notes})")
                continue

            # Rename / server-rename
            if action.new_tool_id and action.new_tool_id != row_dict.get("correct_tool_id"):
                row_dict["correct_tool_id"] = action.new_tool_id
                # Update correct_server_id from the new tool_id prefix
                new_server = action.new_tool_id.split("::", 1)[0]
                row_dict["correct_server_id"] = new_server
                if action.notes:
                    existing_notes = row_dict.get("notes") or ""
                    row_dict["notes"] = (existing_notes + " " + action.notes).strip()
                new_lines.append(json.dumps(row_dict, ensure_ascii=False) + "\n")
                changed = True
                logger.info(
                    f"apply_plan_to_gt: renamed {query_id}: "
                    f"{action.old_tool_id} → {action.new_tool_id}"
                )
            else:
                new_lines.append(line)

        if changed:
            # Write backup before modifying
            backup_path = gt_path.with_name(
                f"{gt_path.name}.bak-pre-reconcile-{plan.plan_hash[:12]}"
            )
            backup_path.write_text(gt_path.read_text(encoding="utf-8"), encoding="utf-8")
            gt_path.write_text("".join(new_lines), encoding="utf-8")
            modified.append(gt_path)
            logger.info(f"apply_plan_to_gt: wrote {gt_path} (backup at {backup_path})")

    return modified


def serialize_plan_report(plan: ReconcilePlan, out_path: Path) -> None:
    """Write a human-readable markdown summary of the ReconcilePlan.

    Args:
        plan:     The plan to report.
        out_path: Destination path (e.g. data/probes/reconcile_report.md).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    action_counts: dict[str, int] = {}
    for action in plan.actions:
        action_counts[action.rule] = action_counts.get(action.rule, 0) + 1

    lines: list[str] = [
        "# Reconcile Plan Report",
        "",
        f"**Plan hash**: `{plan.plan_hash}`",
        f"**Created**: {plan.created_at.isoformat()}",
        f"**Schema version**: {plan.schema_version}",
        "",
        "## Summary",
        "",
        "| Rule | Count |",
        "|------|-------|",
    ]
    for rule, count in sorted(action_counts.items()):
        lines.append(f"| {rule} | {count} |")
    lines.append(f"| **Review queue** | {len(plan.review_queue)} |")
    lines.append(f"| **Total actions** | {len(plan.actions)} |")
    lines += [
        "",
        "## Actions",
        "",
    ]
    for action in plan.actions:
        new_id = action.new_tool_id or "(drop)"
        lines.append(
            f"- [{action.rule}] `{action.query_id}`: "
            f"`{action.old_tool_id}` → `{new_id}`"
            + (f"  *(conf={action.confidence:.4f})*" if action.confidence else "")
        )

    if plan.review_queue:
        lines += ["", "## Review Queue (manual action required)", ""]
        for action in plan.review_queue:
            lines.append(
                f"- [{action.rule}] `{action.query_id}`: "
                f"`{action.old_tool_id}` → `{action.new_tool_id}` "
                f"*(conf={action.confidence:.4f})*"
            )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"serialize_plan_report: wrote {out_path}")
