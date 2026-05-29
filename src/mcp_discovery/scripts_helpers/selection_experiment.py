"""Pure logic for per-client description selection experiments.

Contains data models and computation functions with no I/O.
The actual experiment runner script imports these.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mcp_discovery.description.base import VendorStyle


class ExperimentConfig(BaseModel):
    """Configuration for selection experiment."""

    vendors: list[VendorStyle] = Field(
        default_factory=lambda: [VendorStyle.GEMINI, VendorStyle.CLAUDE, VendorStyle.GPT]
    )
    repetitions: int = 3
    temperature: float = 0.1
    top_k: int = 5

    @property
    def trials_per_query(self) -> int:
        # vendors × reps × 2 conditions (control/treatment)
        return len(self.vendors) * self.repetitions * 2


class TrialResult(BaseModel):
    """Result of a single LLM tool selection trial."""

    query_id: str
    selected_tool_id: str
    target_tool_id: str
    vendor: str
    condition: str  # "control" or "treatment"
    rep: int
    latency_ms: float = 0.0
    token_usage: int = 0


class ExperimentResult(BaseModel):
    """Full experiment result for one tool across all trials."""

    tool_id: str
    query: str
    trials: list[TrialResult]


def compute_selection_rate(trials: list[TrialResult]) -> float:
    """Compute selection rate: fraction of trials where selected == target."""
    if not trials:
        return 0.0
    correct = sum(1 for t in trials if t.selected_tool_id == t.target_tool_id)
    return correct / len(trials)


def compute_experiment_summary(trials: list[TrialResult]) -> dict:
    """Group trials by vendor + condition and compute selection rates.

    Returns:
        {
            "gpt": {
                "control": {"selection_rate": 0.5, "n": 2},
                "treatment": {"selection_rate": 1.0, "n": 2},
                "improvement": 0.5,
            },
            ...
        }
    """
    groups: dict[str, dict[str, list[TrialResult]]] = {}
    for t in trials:
        groups.setdefault(t.vendor, {}).setdefault(t.condition, []).append(t)

    summary: dict = {}
    for vendor, conditions in groups.items():
        vendor_summary: dict = {}
        for condition, cond_trials in conditions.items():
            vendor_summary[condition] = {
                "selection_rate": compute_selection_rate(cond_trials),
                "n": len(cond_trials),
            }
        control_rate = vendor_summary.get("control", {}).get("selection_rate", 0.0)
        treatment_rate = vendor_summary.get("treatment", {}).get("selection_rate", 0.0)
        vendor_summary["improvement"] = treatment_rate - control_rate
        summary[vendor] = vendor_summary

    return summary


def compute_per_tool_summary(trials: list[TrialResult]) -> dict:
    """Group trials by target_tool_id + condition and compute selection rates.

    Returns:
        {
            "tool_id_1": {
                "control": {"selection_rate": 0.5, "n": 2},
                "treatment": {"selection_rate": 1.0, "n": 2},
                "improvement": 0.5,
            },
            ...
        }
    """
    groups: dict[str, dict[str, list[TrialResult]]] = {}
    for t in trials:
        groups.setdefault(t.target_tool_id, {}).setdefault(t.condition, []).append(t)

    summary: dict = {}
    for tool_id, conditions in groups.items():
        tool_summary: dict = {}
        for condition, cond_trials in conditions.items():
            tool_summary[condition] = {
                "selection_rate": compute_selection_rate(cond_trials),
                "n": len(cond_trials),
            }
        control_rate = tool_summary.get("control", {}).get("selection_rate", 0.0)
        treatment_rate = tool_summary.get("treatment", {}).get("selection_rate", 0.0)
        tool_summary["improvement"] = treatment_rate - control_rate
        summary[tool_id] = tool_summary

    return summary


def compute_mcnemar_summary(trials: list[TrialResult]) -> dict | None:
    """Compute paired McNemar summary across control/treatment trials.

    Pairing identity is query_id + target_tool_id + vendor + rep. All four
    fields are needed: target_tool_id alone can have multiple GT queries.
    """
    from mcp_discovery.analytics.statistical import mcnemar_test

    control_by_key: dict[tuple[str, str, str, int], bool] = {}
    treatment_by_key: dict[tuple[str, str, str, int], bool] = {}
    for trial in trials:
        key = (trial.query_id, trial.target_tool_id, trial.vendor, trial.rep)
        correct = trial.selected_tool_id == trial.target_tool_id
        if trial.condition == "control":
            control_by_key[key] = correct
        elif trial.condition == "treatment":
            treatment_by_key[key] = correct

    common_keys = sorted(set(control_by_key) & set(treatment_by_key))
    if not common_keys:
        return None

    control_correct = [control_by_key[key] for key in common_keys]
    treatment_correct = [treatment_by_key[key] for key in common_keys]
    statistic, p_value, b, c = mcnemar_test(control_correct, treatment_correct)
    return {"statistic": float(statistic), "p_value": float(p_value), "b": b, "c": c}
