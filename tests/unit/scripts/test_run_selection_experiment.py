"""Tests for selection experiment runner helpers."""

import pytest
from run_selection_experiment import (
    _match_response_to_tool_id,
    _prepare_candidate_prompt,
    _stable_shuffle_seed,
    run_experiment,
)

from mcp_discovery.description.base import VendorStyle
from mcp_discovery.scripts_helpers.selection_experiment import ExperimentConfig


def test_stable_shuffle_seed_is_repeatable() -> None:
    first = _stable_shuffle_seed("q1", "gpt", "control", 1)
    second = _stable_shuffle_seed("q1", "gpt", "control", 1)
    different_query = _stable_shuffle_seed("q2", "gpt", "control", 1)

    assert first == second
    assert first != different_query


def test_numbered_response_matches_shuffled_candidate_order() -> None:
    candidates = [
        {"tool_id": "a::one", "description": "first"},
        {"tool_id": "b::two", "description": "second"},
        {"tool_id": "c::three", "description": "third"},
    ]

    for seed in range(20):
        prompt_text, ordered_candidates = _prepare_candidate_prompt(
            candidates,
            condition="control",
            vendor=VendorStyle.GPT,
            variant_map={},
            shuffle_seed=seed,
        )
        if ordered_candidates[0]["tool_id"] != candidates[0]["tool_id"]:
            break
    else:
        raise AssertionError("test seeds did not produce a changed candidate order")

    assert "1. **" in prompt_text
    assert _match_response_to_tool_id("1", ordered_candidates) == ordered_candidates[0]["tool_id"]
    assert ordered_candidates[0]["tool_id"] != candidates[0]["tool_id"]


async def test_missing_vendor_dependency_stops_experiment(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing_dependency(*_args: object, **_kwargs: object) -> tuple[str, int]:
        raise ImportError("No module named 'anthropic'")

    class EmptyVariantStore:
        def load_all(self) -> list:
            return []

    monkeypatch.setattr("run_selection_experiment._call_vendor_llm", missing_dependency)
    queries = [
        {
            "query_id": "q1",
            "query": "search",
            "target_tool_id": "a::one",
            "candidates": [{"tool_id": "a::one", "description": "first"}],
        }
    ]

    with pytest.raises(RuntimeError, match="uv run --group experiment"):
        await run_experiment(
            queries,
            ExperimentConfig(vendors=[VendorStyle.CLAUDE], repetitions=1),
            EmptyVariantStore(),
            settings=object(),
        )
