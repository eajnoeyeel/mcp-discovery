"""Tests for statistical analysis functions."""

import pytest

from mcp_discovery.analytics.statistical import mcnemar_test


class TestMcNemarTest:
    def test_significant_improvement(self) -> None:
        """20 discordant pairs (control wrong → treatment right) vs 2 reverse → p < 0.05."""
        n = 50
        # 20 pairs: control=False, treatment=True
        # 2 pairs: control=True, treatment=False
        # 28 pairs: concordant (both same)
        control = [False] * 20 + [True] * 2 + [True] * 14 + [False] * 14
        treatment = [True] * 20 + [False] * 2 + [True] * 14 + [False] * 14
        assert len(control) == n
        assert len(treatment) == n

        stat, p_value, b, c = mcnemar_test(control, treatment)
        assert b == 20
        assert c == 2
        assert p_value < 0.05

    def test_no_difference(self) -> None:
        """Identical results → p >= 0.05, b=0, c=0."""
        correct = [True, False, True, True, False]
        stat, p_value, b, c = mcnemar_test(correct, correct)
        assert b == 0
        assert c == 0
        assert p_value >= 0.05

    def test_small_sample_uses_exact(self) -> None:
        """3 discordant pairs → uses binomial (b=3, c=0)."""
        # 3 pairs: control=False, treatment=True; rest concordant
        control = [False, False, False, True, True]
        treatment = [True, True, True, True, True]
        stat, p_value, b, c = mcnemar_test(control, treatment)
        assert b == 3
        assert c == 0
        # Exact binomial with b=3, n=3, p=0.5 → p = 2 * (0.5^3) = 0.25
        assert p_value == pytest.approx(0.25, abs=1e-6)

    def test_mismatched_lengths_raises(self) -> None:
        """ValueError raised when list lengths differ."""
        with pytest.raises(ValueError, match="Length mismatch"):
            mcnemar_test([True, False], [True])
