"""Idempotence tests for the reconciler (ADR-0018).

Invariant: reconcile(reconcile(x)) == reconcile(x) when manual_remaps is stable.
Applying the same ReconcilePlan twice must produce bit-identical output.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_discovery.data.gt_reconciler import apply_plan_to_gt, build_reconcile_plan
from mcp_discovery.models.core import MCPServer
from tests.unit.data.conftest import make_gt_entry, make_tool


def _build_pool(*server_tool_pairs: tuple[str, list[str]]) -> list[MCPServer]:
    """Build a list of MCPServer from (server_id, [tool_names]) pairs."""
    servers = []
    for server_id, tool_names in server_tool_pairs:
        tools = [make_tool(server_id, name) for name in tool_names]
        servers.append(MCPServer(server_id=server_id, name=server_id, tools=tools))
    return servers


class TestIdempotence:
    def test_same_plan_applied_twice_is_idempotent(self, tmp_path: Path):
        """Applying the same ReconcilePlan a second time should produce an empty plan."""
        gt_entries = [
            make_gt_entry("q1", "github", "get_commit"),  # → R2 manual remap
            make_gt_entry("q2", "github", "list_commits"),  # → R1 exact
        ]
        pool = _build_pool(("github", ["list_commits", "create_issue"]))
        manual_remaps = {"github::get_commit": "github::list_commits"}

        # First reconcile pass
        plan1 = build_reconcile_plan(pool, [], gt_entries, manual_remaps)
        assert len(plan1.actions) == 1  # only R2 produces an action (R1 preserves)
        assert plan1.actions[0].old_tool_id == "github::get_commit"
        assert plan1.actions[0].new_tool_id == "github::list_commits"

        # Write GT to a temp file and apply plan
        gt_file = tmp_path / "gt.jsonl"
        lines = [json.dumps(e.model_dump(mode="json")) for e in gt_entries]
        gt_file.write_text("\n".join(lines) + "\n")
        apply_plan_to_gt(plan1, [gt_file])

        # Re-read the updated GT and build a new plan
        updated_lines = [ln for ln in gt_file.read_text().splitlines() if ln.strip()]
        from mcp_discovery.models.core import GroundTruthEntry

        updated_gt = [GroundTruthEntry.model_validate(json.loads(ln)) for ln in updated_lines]

        plan2 = build_reconcile_plan(pool, [], updated_gt, manual_remaps)

        # Second plan should have no rename actions (R2 already applied → R1 now matches)
        rename_actions = [a for a in plan2.actions if a.rule in ("R2", "R3", "R4")]
        assert len(rename_actions) == 0, (
            f"Expected no renames in second plan but got: {rename_actions}"
        )

    def test_build_plan_same_inputs_deterministic(self):
        """build_reconcile_plan with identical inputs must produce the same plan_hash."""
        gt_entries = [make_gt_entry(f"q{i}", "srv", f"tool_{i}") for i in range(5)]
        pool = _build_pool(("srv", [f"tool_{i}" for i in range(5)]))

        plan_a = build_reconcile_plan(pool, [], gt_entries, {})
        plan_b = build_reconcile_plan(pool, [], gt_entries, {})
        assert plan_a.plan_hash == plan_b.plan_hash

    def test_apply_plan_twice_produces_same_file(self, tmp_path: Path):
        """Applying the same plan twice must not change the file after the first application."""
        gt_entries = [make_gt_entry("q1", "gh", "old_tool")]
        pool = _build_pool(("gh", ["new_tool"]))
        manual_remaps = {"gh::old_tool": "gh::new_tool"}

        plan = build_reconcile_plan(pool, [], gt_entries, manual_remaps)

        # Write and apply first time
        gt_file = tmp_path / "gt.jsonl"
        gt_file.write_text(
            "\n".join(json.dumps(e.model_dump(mode="json")) for e in gt_entries) + "\n"
        )
        apply_plan_to_gt(plan, [gt_file])
        content_after_first = gt_file.read_text()

        # Apply plan again to the already-modified file
        # (plan actions reference old_tool_id which no longer appears)
        apply_plan_to_gt(plan, [gt_file])
        content_after_second = gt_file.read_text()

        assert content_after_first == content_after_second, (
            "Applying the same plan twice should not change the file after the first application"
        )

    def test_preserve_actions_not_in_plan_output(self):
        """R1 PRESERVE outcomes should NOT appear in plan.actions."""
        gt_entries = [make_gt_entry("q1", "srv", "exact_match")]
        pool = _build_pool(("srv", ["exact_match"]))

        plan = build_reconcile_plan(pool, [], gt_entries, {})
        assert len(plan.actions) == 0  # preserve means no action

    def test_empty_gt_produces_empty_plan(self):
        pool = _build_pool(("srv", ["tool_a"]))
        plan = build_reconcile_plan(pool, [], [], {})
        assert plan.actions == []
        assert plan.review_queue == []
