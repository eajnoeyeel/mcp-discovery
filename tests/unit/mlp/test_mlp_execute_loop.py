"""Tests for the execute loop harness summary computation."""

from service.harness.execute_loop import summarize_execute_runs


def test_summarize_execute_runs_counts_timeouts():
    summary = summarize_execute_runs(
        [{"ok": True, "timed_out": False}, {"ok": False, "timed_out": True}]
    )
    assert summary["timeout_rate"] == 0.5
    assert summary["success_rate"] == 0.5


def test_summarize_execute_runs_empty_input():
    summary = summarize_execute_runs([])
    assert summary["runs"] == 0
    assert summary["error_rate"] == 0.0


def test_execute_auth_loop_counts_header_generation_successes():
    from service.harness.execute_auth_loop import summarize_auth_runs

    summary = summarize_auth_runs(
        [
            {"ok": True, "header_count": 1},
            {"ok": True, "header_count": 2},
            {"ok": False, "header_count": 0},
        ]
    )

    assert summary["runs"] == 3
    assert summary["success_rate"] == 2 / 3
    assert summary["avg_header_count"] == 1.0


def test_metamcp_runtime_loop_summarizes_refresh_and_pool_reuse():
    from service.harness.metamcp_runtime_loop import summarize_runtime_runs

    summary = summarize_runtime_runs(
        [
            {"ok": True, "refreshed": True, "reused_session": False},
            {"ok": True, "refreshed": False, "reused_session": True},
            {"ok": False, "refreshed": False, "reused_session": False},
        ]
    )

    assert summary["runs"] == 3
    assert summary["success_rate"] == 2 / 3
    assert summary["refresh_rate"] == 1 / 3
    assert summary["session_reuse_rate"] == 1 / 3


def test_delegated_oauth_execute_loop_summarizes_auth_and_retry_outcomes():
    from service.harness.delegated_oauth_execute_loop import summarize_delegated_oauth_runs

    summary = summarize_delegated_oauth_runs(
        [
            {"auth_required": True, "callback_ok": True, "retry_ok": True},
            {"auth_required": True, "callback_ok": False, "retry_ok": False},
        ]
    )

    assert summary["runs"] == 2
    assert summary["auth_required_rate"] == 1.0
    assert summary["callback_success_rate"] == 0.5
    assert summary["retry_success_rate"] == 0.5
