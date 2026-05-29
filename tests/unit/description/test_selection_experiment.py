"""Tests for selection experiment logic (not LLM calls)."""

from mcp_discovery.description.base import VendorStyle
from mcp_discovery.scripts_helpers.selection_experiment import (
    ExperimentConfig,
    TrialResult,
    compute_experiment_summary,
    compute_mcnemar_summary,
    compute_per_tool_summary,
    compute_selection_rate,
)


class TestExperimentConfig:
    def test_default_config(self) -> None:
        config = ExperimentConfig()
        assert config.vendors == [VendorStyle.GEMINI, VendorStyle.CLAUDE, VendorStyle.GPT]
        assert config.repetitions == 3
        assert config.temperature == 0.1
        assert config.top_k == 5

    def test_total_trials(self) -> None:
        config = ExperimentConfig(repetitions=3)
        # 3 vendors × 3 reps × 2 conditions (control/treatment) = 18 per query
        assert config.trials_per_query == 18


class TestComputeSelectionRate:
    def test_all_correct(self) -> None:
        trials = [
            TrialResult(
                query_id="q1",
                selected_tool_id="t1",
                target_tool_id="t1",
                vendor="gpt",
                condition="control",
                rep=1,
            ),
            TrialResult(
                query_id="q2",
                selected_tool_id="t1",
                target_tool_id="t1",
                vendor="gpt",
                condition="control",
                rep=2,
            ),
        ]
        assert compute_selection_rate(trials) == 1.0

    def test_none_correct(self) -> None:
        trials = [
            TrialResult(
                query_id="q1",
                selected_tool_id="t2",
                target_tool_id="t1",
                vendor="gpt",
                condition="control",
                rep=1,
            ),
        ]
        assert compute_selection_rate(trials) == 0.0

    def test_partial(self) -> None:
        trials = [
            TrialResult(
                selected_tool_id="t1",
                target_tool_id="t1",
                query_id="q1",
                vendor="gpt",
                condition="treatment",
                rep=1,
            ),
            TrialResult(
                selected_tool_id="t2",
                target_tool_id="t1",
                query_id="q2",
                vendor="gpt",
                condition="treatment",
                rep=2,
            ),
            TrialResult(
                selected_tool_id="t1",
                target_tool_id="t1",
                query_id="q3",
                vendor="gpt",
                condition="treatment",
                rep=3,
            ),
        ]
        assert abs(compute_selection_rate(trials) - 2 / 3) < 1e-6


class TestComputeExperimentSummary:
    def test_summary_groups_by_vendor_and_condition(self) -> None:
        trials = [
            TrialResult(
                query_id="q1",
                selected_tool_id="t1",
                target_tool_id="t1",
                vendor="gpt",
                condition="control",
                rep=1,
            ),
            TrialResult(
                query_id="q2",
                selected_tool_id="t2",
                target_tool_id="t1",
                vendor="gpt",
                condition="control",
                rep=2,
            ),
            TrialResult(
                selected_tool_id="t1",
                target_tool_id="t1",
                query_id="q1",
                vendor="gpt",
                condition="treatment",
                rep=1,
            ),
            TrialResult(
                selected_tool_id="t1",
                target_tool_id="t1",
                query_id="q2",
                vendor="gpt",
                condition="treatment",
                rep=2,
            ),
        ]
        summary = compute_experiment_summary(trials)
        assert summary["gpt"]["control"]["selection_rate"] == 0.5
        assert summary["gpt"]["treatment"]["selection_rate"] == 1.0
        assert summary["gpt"]["improvement"] == 0.5

    def test_empty_trials(self) -> None:
        summary = compute_experiment_summary([])
        assert summary == {}


class TestComputePerToolSummary:
    def test_groups_by_tool(self) -> None:
        trials = [
            TrialResult(
                query_id="q1",
                selected_tool_id="t1",
                target_tool_id="t1",
                vendor="gpt",
                condition="control",
                rep=1,
            ),
            TrialResult(
                selected_tool_id="t2",
                target_tool_id="t1",
                query_id="q1",
                vendor="gpt",
                condition="treatment",
                rep=1,
            ),
            TrialResult(
                query_id="q2",
                selected_tool_id="t1",
                target_tool_id="t2",
                vendor="gpt",
                condition="control",
                rep=1,
            ),
            TrialResult(
                selected_tool_id="t2",
                target_tool_id="t2",
                query_id="q2",
                vendor="gpt",
                condition="treatment",
                rep=1,
            ),
        ]
        summary = compute_per_tool_summary(trials)
        assert "t1" in summary
        assert "t2" in summary
        assert summary["t1"]["control"]["selection_rate"] == 1.0
        assert summary["t1"]["treatment"]["selection_rate"] == 0.0
        assert summary["t2"]["control"]["selection_rate"] == 0.0
        assert summary["t2"]["treatment"]["selection_rate"] == 1.0


class TestComputeMcNemarSummary:
    def test_pairs_by_query_id_tool_vendor_and_rep(self) -> None:
        trials = [
            TrialResult(
                query_id="q1",
                selected_tool_id="other::tool",
                target_tool_id="target::tool",
                vendor="gpt",
                condition="control",
                rep=1,
            ),
            TrialResult(
                query_id="q1",
                selected_tool_id="target::tool",
                target_tool_id="target::tool",
                vendor="gpt",
                condition="treatment",
                rep=1,
            ),
            TrialResult(
                query_id="q2",
                selected_tool_id="target::tool",
                target_tool_id="target::tool",
                vendor="gpt",
                condition="control",
                rep=1,
            ),
            TrialResult(
                query_id="q2",
                selected_tool_id="other::tool",
                target_tool_id="target::tool",
                vendor="gpt",
                condition="treatment",
                rep=1,
            ),
        ]

        summary = compute_mcnemar_summary(trials)

        assert summary is not None
        assert summary["b"] == 1
        assert summary["c"] == 1
