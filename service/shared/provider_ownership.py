"""Compatibility helpers for provider ownership metadata."""

from __future__ import annotations

from typing import Any

OWNER_TAG_PREFIX = "__owner_user_id:"
MISSING_OWNER_COLUMN_CODES = {"42703", "PGRST204"}


def add_owner_tag(tags: list[str] | None, owner_user_id: str) -> list[str]:
    """Return tags with a single internal owner marker attached."""
    public_tags = strip_internal_owner_tags(tags)
    return [*public_tags, f"{OWNER_TAG_PREFIX}{owner_user_id}"]


def strip_internal_owner_tags(tags: list[str] | None) -> list[str]:
    """Remove internal ownership markers from a tag list."""
    return [tag for tag in (tags or []) if not tag.startswith(OWNER_TAG_PREFIX)]


def extract_owner_user_id(server_row: dict[str, Any]) -> str | None:
    """Resolve the owner from the explicit column or the compatibility tag."""
    if owner_user_id := server_row.get("owner_user_id"):
        return str(owner_user_id)

    for tag in server_row.get("tags") or []:
        if tag.startswith(OWNER_TAG_PREFIX):
            return tag.removeprefix(OWNER_TAG_PREFIX) or None
    return None


def is_missing_column_error_payload(payload: Any, column_name: str) -> bool:
    """Detect Supabase/PostgREST errors caused by a missing column.

    Matches only when the error message explicitly names the requested
    ``column_name``. The earlier implementation returned True for any 42703
    error regardless of column, which caused false positives that cascaded
    through ``fetch_server`` fallback and silently dropped ``owner_user_id``
    from SELECT lists.
    """
    if not isinstance(payload, dict):
        return False

    code = str(payload.get("code") or "")
    message = str(payload.get("message") or "").lower()
    if code in MISSING_OWNER_COLUMN_CODES:
        return column_name in message
    return False


def is_missing_owner_column_error_payload(payload: Any) -> bool:
    """Detect Supabase/PostgREST errors caused by the missing owner column."""
    return is_missing_column_error_payload(payload, "owner_user_id")
