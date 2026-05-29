from service.harness.claude_auth_probe import summarize_auth_probe_runs
from service.services.auth_probe import build_auth_probe_result


def test_build_auth_probe_result_marks_authenticated_request():
    result = build_auth_probe_result(
        user_id="user-123",
        auth_source="bridge_authorizer",
        issuer="supabase",
    )

    assert result["authenticated"] is True
    assert result["user_id"] == "user-123"
    assert result["status"] == "authenticated"


def test_build_auth_probe_result_marks_missing_auth():
    result = build_auth_probe_result(
        user_id=None,
        auth_source="bridge_authorizer",
        issuer=None,
    )

    assert result["authenticated"] is False
    assert result["status"] == "auth_required"
    assert result["user_id"] is None


def test_build_auth_probe_result_supports_unavailable_validation_status():
    result = build_auth_probe_result(
        user_id=None,
        auth_source="supabase_bearer",
        issuer=None,
        status="validation_unavailable",
        error="supabase_validation_unavailable",
    )

    assert result["authenticated"] is False
    assert result["status"] == "validation_unavailable"
    assert result["error"] == "supabase_validation_unavailable"


def test_summarize_auth_probe_runs_tracks_clear_and_reauth_states():
    summary = summarize_auth_probe_runs(
        [
            {"label": "cleared", "status": "auth_required", "authenticated": False},
            {"label": "reauthenticated", "status": "authenticated", "authenticated": True},
            {
                "label": "backend unavailable",
                "status": "validation_unavailable",
                "authenticated": False,
            },
        ]
    )

    assert summary == {
        "runs": 3.0,
        "authenticated_rate": 1 / 3,
        "auth_required_rate": 1 / 3,
        "validation_unavailable_rate": 1 / 3,
    }
