"""Tests for the index loop harness summary computation."""

from __future__ import annotations

import json
from pathlib import Path

from service.harness.index_loop import DEFAULT_SAMPLE_RUNS, main, summarize_index_runs

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "service/harness/fixtures/index_runs_content_hash_skip_sample.json"
)
EXPECTED_SAMPLE_RUNS = [
    {"ok": True, "indexed_count": 2, "skipped_count": 0},
    {"ok": True, "indexed_count": 0, "skipped_count": 2},
    {"ok": True, "indexed_count": 1, "skipped_count": 1},
]


def test_summarize_index_runs_reports_failure_and_skip_metrics():
    summary = summarize_index_runs(
        [
            {"ok": True, "indexed_count": 2, "skipped_count": 1},
            {"ok": False, "indexed_count": 0, "skipped_count": 0},
            {"ok": True, "indexed_count": 4, "skipped_count": 3},
        ]
    )
    assert summary["success_rate"] == 2 / 3
    assert summary["failure_rate"] == 1 / 3
    assert summary["indexed_total"] == 6
    assert summary["skipped_total"] == 4
    assert summary["skip_rate"] == 0.4
    assert summary["average_batch_size"] == 2


def test_summarize_index_runs_empty_input():
    summary = summarize_index_runs([])
    assert summary["runs"] == 0
    assert summary["indexed_total"] == 0
    assert summary["skipped_total"] == 0
    assert summary["skip_rate"] == 0.0


def test_summarize_index_runs_zero_processed_guard():
    summary = summarize_index_runs([{"ok": False, "indexed_count": 0, "skipped_count": 0}])
    assert summary["skip_rate"] == 0.0
    assert summary["skipped_total"] == 0


def test_default_sample_runs_match_fixture_contract():
    fixture_runs = json.loads(FIXTURE_PATH.read_text())
    assert fixture_runs == EXPECTED_SAMPLE_RUNS
    assert DEFAULT_SAMPLE_RUNS == EXPECTED_SAMPLE_RUNS
    assert fixture_runs == DEFAULT_SAMPLE_RUNS

    summary = summarize_index_runs(DEFAULT_SAMPLE_RUNS)
    assert summary["success_rate"] == 1.0
    assert summary["failure_rate"] == 0.0
    assert summary["indexed_total"] == 3
    assert summary["skipped_total"] == 3
    assert summary["skip_rate"] == 0.5


def test_results_file_mode_label_is_neutral(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["index_loop", "--results-file", str(FIXTURE_PATH)],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "results_file"
