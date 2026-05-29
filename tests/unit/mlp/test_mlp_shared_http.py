"""Tests for shared MLP runtime helpers."""

import json

from service.shared import (
    MLPSettings,
    build_log_payload,
    error_response,
    json_response,
    log_info,
)
from service.shared import logging as shared_logging


def test_json_response_sets_json_content_type():
    response = json_response(200, {"ok": True})

    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "application/json"
    assert json.loads(response["body"]) == {"ok": True}


def test_error_response_wraps_error_message():
    response = error_response(400, "bad request")

    assert response["statusCode"] == 400
    assert response["headers"]["Content-Type"] == "application/json"
    assert json.loads(response["body"]) == {"error": "bad request"}


def test_json_response_stringifies_non_json_serializable_values():
    class StableValue:
        def __str__(self) -> str:
            return "stable-value"

    response = json_response(200, {"value": StableValue()})

    assert json.loads(response["body"]) == {"value": "stable-value"}


def test_build_log_payload_includes_event_request_id_and_fields():
    payload = build_log_payload("search", "req-123", query="hello", latency_ms=12)

    assert payload == {
        "event": "search",
        "request_id": "req-123",
        "query": "hello",
        "latency_ms": 12,
    }


def test_settings_reads_env_vars(monkeypatch):
    monkeypatch.setenv("MLP_CACHE_TTL_SECONDS", "900")
    monkeypatch.setenv("MLP_SEARCH_TOP_K_DEFAULT", "7")

    settings = MLPSettings(_env_file=None)

    assert settings.cache_ttl_seconds == 900
    assert settings.search_top_k_default == 7


def test_log_info_returns_payload_and_logs_json(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(shared_logging.logger, "info", calls.append)

    payload = log_info("search", "req-123", query="hello", latency_ms=12)

    expected = {
        "event": "search",
        "request_id": "req-123",
        "query": "hello",
        "latency_ms": 12,
    }
    assert payload == expected
    assert calls == [json.dumps(expected)]
