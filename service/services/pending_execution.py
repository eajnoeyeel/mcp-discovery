"""Pending execution helpers for delegated OAuth resume flows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Any


def build_pending_execution(
    *,
    user_id: str,
    tool_id: str,
    params: dict[str, Any],
    provider_key: str,
    required_scopes: list[str],
) -> dict[str, Any]:
    """Build a short-lived pending execution record for OAuth-blocked tools."""
    return {
        "user_id": user_id,
        "tool_id": tool_id,
        "params_json": params,
        "provider_key": provider_key,
        "required_scopes": required_scopes,
        "status": "waiting_for_connect",
        "resume_token": f"rt_{token_urlsafe(18)}",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat().replace(
            "+00:00", "Z"
        ),
    }


def mark_pending_execution_ready(record: dict[str, Any]) -> dict[str, Any]:
    """Return a pending execution row advanced to ready-to-resume."""
    return {
        **record,
        "status": "ready_to_resume",
    }


def validate_resume_request(record: dict[str, Any] | None, *, requester_user_id: str) -> str | None:
    """Validate that a pending execution can be resumed by the requester."""
    if record is None:
        return "Pending execution not found"
    if record.get("user_id") != requester_user_id:
        return "Pending execution belongs to a different user"
    expires_at_raw = str(record.get("expires_at") or "").strip()
    if expires_at_raw:
        try:
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        except ValueError:
            expires_at = None
        if expires_at is not None and expires_at <= datetime.now(UTC):
            return "Pending execution has expired"
    if record.get("status") != "ready_to_resume":
        return f"Pending execution is not resumable: {record.get('status')}"
    return None
