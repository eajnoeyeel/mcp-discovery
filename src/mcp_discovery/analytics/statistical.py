"""Statistical analysis for E4 description A/B experiment.

Provides:
- Tool-level P@1 aggregation from per-query results
- Wilcoxon signed-rank test (non-parametric paired test)
- Cluster bootstrap confidence interval
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class ToolLevelComparison:
    """Before/after P@1 comparison for a single tool."""

    tool_id: str
    p1_before: float  # fraction of queries with top_1_correct=True (before)
    p1_after: float  # fraction of queries with top_1_correct=True (after)
    n_queries: int  # number of GT queries for this tool


def compute_tool_level_stats(
    before_results: list[dict],
    after_results: list[dict],
) -> list[ToolLevelComparison]:
    """Aggregate per-query results to tool-level P@1 before/after.

    Args:
        before_results: list of dicts with keys: tool_id, query_id, top_1_correct
        after_results: same structure, same query_ids
    """
    # Group by tool_id
    before_by_tool: dict[str, list[bool]] = {}
    for r in before_results:
        before_by_tool.setdefault(r["tool_id"], []).append(r["top_1_correct"])

    after_by_tool: dict[str, list[bool]] = {}
    for r in after_results:
        after_by_tool.setdefault(r["tool_id"], []).append(r["top_1_correct"])

    comparisons: list[ToolLevelComparison] = []
    for tool_id in sorted(before_by_tool):
        b = before_by_tool[tool_id]
        a = after_by_tool.get(tool_id, [])
        if not a:
            continue
        comparisons.append(
            ToolLevelComparison(
                tool_id=tool_id,
                p1_before=sum(b) / len(b),
                p1_after=sum(a) / len(a),
                n_queries=len(b),
            )
        )
    return comparisons


def wilcoxon_signed_rank(
    comparisons: list[ToolLevelComparison],
) -> tuple[float, float]:
    """Wilcoxon signed-rank test on tool-level P@1 deltas.

    Returns (test_statistic, p_value). Uses alternative='two-sided'.
    Handles zero-diff pairs via 'wilcox' method.
    """
    deltas = np.array([c.p1_after - c.p1_before for c in comparisons])
    # Remove zero-diff pairs (Wilcoxon cannot handle them)
    non_zero = deltas[deltas != 0]
    if len(non_zero) < 2:
        return 0.0, 1.0  # Cannot compute
    result = stats.wilcoxon(non_zero, alternative="two-sided", method="approx")
    return float(result.statistic), float(result.pvalue)


def cluster_bootstrap_ci(
    comparisons: list[ToolLevelComparison],
    n_bootstrap: int = 5000,
    ci_level: float = 0.95,
    seed: int | None = None,
) -> tuple[float, float, float]:
    """Cluster bootstrap CI for mean P@1 delta.

    Resamples at tool (cluster) level to respect within-tool correlation.
    Returns (ci_lower, ci_upper, observed_mean_delta).
    """
    rng = np.random.default_rng(seed)
    deltas = np.array([c.p1_after - c.p1_before for c in comparisons])
    observed_mean = float(np.mean(deltas))

    n = len(deltas)
    boot_means = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        indices = rng.integers(0, n, size=n)
        boot_means[i] = np.mean(deltas[indices])

    alpha = (1 - ci_level) / 2
    ci_lower = float(np.percentile(boot_means, alpha * 100))
    ci_upper = float(np.percentile(boot_means, (1 - alpha) * 100))
    return ci_lower, ci_upper, observed_mean


def mcnemar_test(
    control_correct: list[bool],
    treatment_correct: list[bool],
) -> tuple[float, float, int, int]:
    """McNemar's test for paired binary outcomes.

    Compares control vs treatment on the same queries.
    Uses exact binomial test when discordant pairs < 25,
    chi-squared approximation otherwise.

    Args:
        control_correct: per-query boolean — was control selection correct?
        treatment_correct: per-query boolean — was treatment selection correct?

    Returns:
        (statistic, p_value, b, c) where:
        - b = discordant pairs where control wrong, treatment right
        - c = discordant pairs where control right, treatment wrong
    """
    if len(control_correct) != len(treatment_correct):
        raise ValueError(
            f"Length mismatch: control has {len(control_correct)} entries, "
            f"treatment has {len(treatment_correct)} entries"
        )

    b = sum(1 for ctrl, trt in zip(control_correct, treatment_correct) if not ctrl and trt)
    c = sum(1 for ctrl, trt in zip(control_correct, treatment_correct) if ctrl and not trt)

    discordant = b + c
    if discordant == 0:
        return 0.0, 1.0, 0, 0

    if discordant < 25:
        p_value = float(stats.binomtest(b, discordant, 0.5).pvalue)
        return float(b), p_value, b, c

    stat = (abs(b - c) - 1) ** 2 / discordant
    p_value = 1.0 - float(stats.chi2.cdf(stat, df=1))
    return float(stat), p_value, b, c
