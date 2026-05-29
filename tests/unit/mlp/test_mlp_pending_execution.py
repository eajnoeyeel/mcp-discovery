from service.services.pending_execution import (
    build_pending_execution,
    mark_pending_execution_ready,
    validate_resume_request,
)


def test_build_pending_execution_preserves_original_request():
    record = build_pending_execution(
        user_id="user-123",
        tool_id="apify-oauth::search",
        params={"query": "대한민국 대통령"},
        provider_key="apify",
        required_scopes=["tools.execute"],
    )

    assert record["user_id"] == "user-123"
    assert record["tool_id"] == "apify-oauth::search"
    assert record["params_json"] == {"query": "대한민국 대통령"}
    assert record["provider_key"] == "apify"
    assert record["required_scopes"] == ["tools.execute"]
    assert record["status"] == "waiting_for_connect"
    assert record["resume_token"].startswith("rt_")
    assert record["expires_at"].endswith("Z")


def test_mark_pending_execution_ready_sets_ready_to_resume():
    updated = mark_pending_execution_ready(
        {"id": "pending-123", "status": "waiting_for_connect", "resume_token": "rt_123"}
    )

    assert updated["id"] == "pending-123"
    assert updated["status"] == "ready_to_resume"
    assert updated["resume_token"] == "rt_123"


def test_validate_resume_request_rejects_wrong_user():
    error = validate_resume_request(
        {"user_id": "user-123", "status": "ready_to_resume"},
        requester_user_id="user-456",
    )

    assert error == "Pending execution belongs to a different user"


def test_validate_resume_request_accepts_matching_ready_record():
    error = validate_resume_request(
        {"user_id": "user-123", "status": "ready_to_resume"},
        requester_user_id="user-123",
    )

    assert error is None
