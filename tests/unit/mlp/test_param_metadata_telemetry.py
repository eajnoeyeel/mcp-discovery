"""Unit tests for service.shared.param_metadata_telemetry and its integration with
the RegisterService / DashboardService normalizers.

Follow-up #4 from the 2026-04-17 transplant: providers' HTTP MCP servers return
tools/list responses whose parameter-metadata entries are silently dropped when
malformed. The telemetry helper emits a single aggregated warning per
normalizer invocation, gated by the MLP_WARN_PARAM_DROPS env flag
(default off) to avoid CloudWatch spam at provider scale.
"""

from __future__ import annotations

import pytest
from loguru import logger

from service.services.register_service import RegisterService
from service.shared.param_metadata_telemetry import emit_drop_warning


@pytest.fixture
def captured_warnings(monkeypatch):
    """Capture loguru WARNING-level messages to a list.

    Mirrors the pattern at tests/unit/mlp/test_mlp_local_eventbridge_relay.py:57.
    Also enables the MLP_WARN_PARAM_DROPS flag so the helper actually emits.
    """
    monkeypatch.setenv("MLP_WARN_PARAM_DROPS", "1")
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="WARNING", format="{message}")
    try:
        yield messages
    finally:
        logger.remove(sink_id)


def test_emit_drop_warning_noop_when_env_flag_unset(monkeypatch):
    """Kill switch: warning is skipped when MLP_WARN_PARAM_DROPS is not '1'."""
    monkeypatch.delenv("MLP_WARN_PARAM_DROPS", raising=False)
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="WARNING", format="{message}")
    try:
        emit_drop_warning("test.normalizer", 3, 5, {"not_a_dict": 3})
    finally:
        logger.remove(sink_id)
    assert messages == [], "Warning emitted despite env flag being unset"


def test_emit_drop_warning_noop_when_zero_drops(captured_warnings):
    """Happy path: zero drops → no warning even when env flag is on."""
    emit_drop_warning("test.normalizer", 0, 5, {})
    assert captured_warnings == []


def test_register_service_normalize_drops_emits_single_aggregated_warning(
    captured_warnings,
):
    """Feed 3 invalid + 2 valid entries; verify single aggregated warning."""
    raw = [
        "not-a-dict",  # not_a_dict
        {"path": "", "name": "anon"},  # missing_required_fields (empty path)
        {"path": "query", "name": ""},  # missing_required_fields (empty name)
        {"path": "query", "name": "query", "type": "string"},  # valid
        {"path": "limit", "name": "limit", "type": "integer"},  # valid
    ]
    result = RegisterService._normalize_parameter_metadata(
        raw, context="register", server_id="srv-1"
    )
    assert len(result) == 2, "Valid entries should be kept"
    assert len(captured_warnings) == 1, (
        f"Expected 1 aggregated warning, got {len(captured_warnings)}: {captured_warnings}"
    )
    msg = captured_warnings[0]
    assert "RegisterService._normalize_parameter_metadata" in msg
    assert "dropped 3/5" in msg
    assert "context=register" in msg
    assert "server_id=srv-1" in msg
    assert "not_a_dict" in msg
    assert "missing_required_fields" in msg


def test_register_service_normalize_context_defaults_to_unknown(captured_warnings):
    """When context / server_id omitted, warning shows 'unknown'."""
    raw = ["bad-entry"]  # triggers not_a_dict drop
    RegisterService._normalize_parameter_metadata(raw)
    assert len(captured_warnings) == 1
    msg = captured_warnings[0]
    assert "context=unknown" in msg
    assert "server_id=unknown" in msg


def test_register_service_normalize_reason_counts_aggregated(captured_warnings):
    """Multiple reason classes produce aggregated counts dict in message."""
    raw = [
        "not-a-dict",  # not_a_dict
        "not-a-dict-either",  # not_a_dict
        {"path": "", "name": "x"},  # missing_required_fields
    ]
    RegisterService._normalize_parameter_metadata(raw, context="register", server_id="srv-x")
    assert len(captured_warnings) == 1
    msg = captured_warnings[0]
    assert "'not_a_dict': 2" in msg
    assert "'missing_required_fields': 1" in msg
    assert "dropped 3/3" in msg


def test_register_service_published_normalize_drops_emit_warning(captured_warnings):
    """Published variant: missing description / path triggers drops + warning."""
    raw = [
        {"path": "query", "description": ""},  # missing_required_fields
        {"path": "", "description": "Search limit"},  # missing_required_fields
        {"path": "limit", "description": "Max rows"},  # valid
    ]
    result = RegisterService._normalize_published_parameter_metadata(
        raw, context="register", server_id="srv-2"
    )
    assert len(result) == 1
    assert len(captured_warnings) == 1
    msg = captured_warnings[0]
    assert "RegisterService._normalize_published_parameter_metadata" in msg
    assert "dropped 2/3" in msg
    assert "context=register" in msg
    assert "server_id=srv-2" in msg
