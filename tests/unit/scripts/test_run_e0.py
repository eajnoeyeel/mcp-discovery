"""Tests for scripts/run_e0.py — E0 experiment CLI & helpers."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from run_e0 import (
    STRATEGY_CHOICES,
    SWEEP_SIZES,
    _build_result_payload,
    _eval_result_to_dict,
    _format_results_table,
    _format_sweep_table,
    _load_pool_server_ids,
    _log_wandb_results,
    _save_json,
)

from mcp_discovery.evaluation.metrics import EvalResult


class TestLoadPoolServerIds:
    """Test GT-first pool loading from base_pool.json."""

    def _write_base_pool(self, tmp_path: Path, server_ids: list[str]) -> Path:
        """Write a base_pool.json file with GT-first ordered server IDs."""
        pool_path = tmp_path / "base_pool.json"
        pool_path.write_text(json.dumps(server_ids))
        return pool_path

    def test_no_pool_size_returns_all(self, tmp_path: Path) -> None:
        import run_e0 as run_e0_module

        pool_path = self._write_base_pool(tmp_path, ["semantic_scholar", "alpha", "bravo"])
        original = run_e0_module.BASE_POOL_PATH
        run_e0_module.BASE_POOL_PATH = pool_path
        try:
            result = _load_pool_server_ids(pool_size=None)
        finally:
            run_e0_module.BASE_POOL_PATH = original
        assert result == ["semantic_scholar", "alpha", "bravo"]

    def test_pool_size_returns_first_n(self, tmp_path: Path) -> None:
        import run_e0 as run_e0_module

        pool_path = self._write_base_pool(
            tmp_path, ["semantic_scholar", "github", "alpha", "bravo"]
        )
        original = run_e0_module.BASE_POOL_PATH
        run_e0_module.BASE_POOL_PATH = pool_path
        try:
            result = _load_pool_server_ids(pool_size=2)
        finally:
            run_e0_module.BASE_POOL_PATH = original
        assert result == ["semantic_scholar", "github"]

    def test_pool_size_exceeding_total_returns_all(self, tmp_path: Path) -> None:
        import run_e0 as run_e0_module

        pool_path = self._write_base_pool(tmp_path, ["bravo", "alpha"])
        original = run_e0_module.BASE_POOL_PATH
        run_e0_module.BASE_POOL_PATH = pool_path
        try:
            result = _load_pool_server_ids(pool_size=999)
        finally:
            run_e0_module.BASE_POOL_PATH = original
        assert result == ["bravo", "alpha"]

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        import run_e0 as run_e0_module

        original = run_e0_module.BASE_POOL_PATH
        run_e0_module.BASE_POOL_PATH = tmp_path / "nonexistent_base_pool.json"
        try:
            with pytest.raises(FileNotFoundError):
                _load_pool_server_ids()
        finally:
            run_e0_module.BASE_POOL_PATH = original


def _make_eval_result(name: str = "FlatStrategy") -> EvalResult:
    """Minimal EvalResult for testing."""
    return EvalResult(
        strategy_name=name,
        n_queries=10,
        n_failed=0,
        k_used=10,
        precision_at_1=0.5,
        recall_at_k=0.7,
        mrr=0.6,
        ndcg_at_5=0.55,
        confusion_rate=0.1,
        ece=0.05,
        latency_p50=100.0,
        latency_p95=200.0,
        latency_p99=300.0,
        latency_mean=120.0,
    )


class TestEvalResultToDict:
    def test_serializes_metrics(self) -> None:
        result = _make_eval_result()
        d = _eval_result_to_dict(result)
        assert d["name"] == "FlatStrategy"
        assert d["metrics"]["precision_at_1"] == 0.5
        assert d["metrics"]["latency_p95"] == 200.0
        assert d["n_queries"] == 10

    def test_excludes_per_query(self) -> None:
        d = _eval_result_to_dict(_make_eval_result())
        assert "per_query" not in d
        assert "per_query" not in d.get("metrics", {})

    def test_none_values_preserved(self) -> None:
        result = EvalResult(
            strategy_name="Test",
            n_queries=1,
            n_failed=0,
            k_used=10,
            precision_at_1=0.0,
            recall_at_k=0.0,
            mrr=0.0,
            ndcg_at_5=0.0,
            confusion_rate=None,
            ece=None,
            latency_p50=0.0,
            latency_p95=0.0,
            latency_p99=0.0,
            latency_mean=0.0,
        )
        d = _eval_result_to_dict(result)
        assert d["metrics"]["confusion_rate"] is None
        assert d["metrics"]["ece"] is None

    def test_json_serializable(self) -> None:
        d = _eval_result_to_dict(_make_eval_result())
        json.dumps(d)  # Should not raise


class TestBuildResultPayload:
    def test_schema_structure(self) -> None:
        payload = _build_result_payload(
            experiment="E0",
            pool_size=308,
            top_k=10,
            results=[_make_eval_result()],
        )
        assert payload["experiment"] == "E0"
        assert "timestamp" in payload
        assert payload["config"]["pool_size"] == 308
        assert payload["config"]["top_k"] == 10
        assert payload["config"]["embedding_model"] == "text-embedding-3-large"
        assert payload["config"]["gt_sources"] == ["seed_set", "mcp_atlas"]
        assert len(payload["strategies"]) == 1

    def test_timestamp_is_iso_format(self) -> None:
        payload = _build_result_payload("E0", 50, 10, [_make_eval_result()])
        datetime.fromisoformat(payload["timestamp"])  # Should not raise


class TestSaveJson:
    def test_creates_file_and_parents(self, tmp_path: Path) -> None:
        data = {"test": True}
        out_path = tmp_path / "sub" / "dir" / "out.json"
        _save_json(data, out_path)
        assert out_path.exists()
        assert json.loads(out_path.read_text()) == {"test": True}


class TestFormatResultsTable:
    def test_contains_strategy_names(self) -> None:
        r1 = _make_eval_result("FlatStrategy")
        r2 = _make_eval_result("SequentialStrategy")
        output = _format_results_table([r1, r2], n_entries=10, top_k=10)
        assert "FlatStrategy" in output
        assert "SequentialStrategy" in output

    def test_includes_pool_size_when_specified(self) -> None:
        r = _make_eval_result()
        output = _format_results_table([r], n_entries=10, top_k=10, pool_size=50)
        assert "pool=50" in output

    def test_omits_pool_size_when_none(self) -> None:
        r = _make_eval_result()
        output = _format_results_table([r], n_entries=10, top_k=10, pool_size=None)
        assert "pool=" not in output

    def test_single_strategy(self) -> None:
        r = _make_eval_result("ParallelStrategy")
        output = _format_results_table([r], n_entries=10, top_k=10)
        assert "ParallelStrategy" in output

    def test_three_strategies(self) -> None:
        results = [
            _make_eval_result("FlatStrategy"),
            _make_eval_result("SequentialStrategy"),
            _make_eval_result("ParallelStrategy"),
        ]
        output = _format_results_table(results, n_entries=10, top_k=10)
        assert "FlatStrategy" in output
        assert "SequentialStrategy" in output
        assert "ParallelStrategy" in output


class TestStrategyChoices:
    def test_valid_choices(self) -> None:
        assert set(STRATEGY_CHOICES) == {"flat", "sequential", "parallel", "all"}


class TestFormatSweepTable:
    def test_contains_all_pool_sizes(self) -> None:
        payloads = [
            _build_result_payload("E0", size, 10, [_make_eval_result()]) for size in [5, 50]
        ]
        output = _format_sweep_table(payloads)
        assert "5" in output
        assert "50" in output

    def test_contains_strategy_name(self) -> None:
        payloads = [_build_result_payload("E0", 5, 10, [_make_eval_result("FlatStrategy")])]
        output = _format_sweep_table(payloads)
        assert "FlatStrategy" in output


class TestSweepSizes:
    def test_sweep_sizes_constant(self) -> None:
        assert SWEEP_SIZES == [5, 20, 50, 100, 200, 308]


class TestLogWandbResults:
    @patch("run_e0.wandb")
    def test_logs_strategy_metrics(self, mock_wandb) -> None:
        results = [_make_eval_result("FlatStrategy")]
        _log_wandb_results(results)
        mock_wandb.log.assert_called_once()
        logged = mock_wandb.log.call_args[0][0]
        assert logged["FlatStrategy/precision_at_1"] == 0.5
        assert logged["FlatStrategy/mrr"] == 0.6
        assert logged["FlatStrategy/latency_p50_ms"] == 100.0

    @patch("run_e0.wandb")
    def test_logs_delta_when_flat_and_sequential(self, mock_wandb) -> None:
        results = [
            _make_eval_result("FlatStrategy"),
            _make_eval_result("SequentialStrategy"),
        ]
        _log_wandb_results(results)
        logged = mock_wandb.log.call_args[0][0]
        assert "delta/precision_at_1" in logged
        assert "delta/mrr" in logged

    @patch("run_e0.wandb")
    def test_no_delta_without_both_strategies(self, mock_wandb) -> None:
        results = [_make_eval_result("FlatStrategy")]
        _log_wandb_results(results)
        logged = mock_wandb.log.call_args[0][0]
        assert "delta/precision_at_1" not in logged
