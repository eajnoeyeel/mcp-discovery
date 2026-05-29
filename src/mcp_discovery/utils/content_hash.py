"""Content hash for idempotent indexing — skip unchanged tools."""

import hashlib


def compute_content_hash(tool_name: str, description: str | None) -> str:
    """SHA-256 of tool_name + description for change detection."""
    text = f"{tool_name}\x00{description or ''}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
