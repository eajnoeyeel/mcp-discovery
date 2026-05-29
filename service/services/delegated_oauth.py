"""Delegated provider OAuth helpers for user-owned execution connections."""

from __future__ import annotations

import hashlib
import json
import secrets

from service.services.contracts import AuthRequiredPayload


def normalize_scopes(scopes: list[str]) -> list[str]:
    """Return a stable, duplicate-free scope list for comparisons and storage."""
    return sorted({scope.strip() for scope in scopes if scope and scope.strip()})


def fingerprint_scopes(scopes: list[str]) -> str:
    """Build a deterministic fingerprint for a normalized provider scope set."""
    payload = json.dumps(normalize_scopes(scopes), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def scopes_cover(granted_scopes: list[str], required_scopes: list[str]) -> bool:
    """Return True when the granted provider scopes satisfy the required scopes."""
    return set(normalize_scopes(required_scopes)).issubset(normalize_scopes(granted_scopes))


def build_auth_required_payload(
    *,
    provider: str,
    required_scopes: list[str],
    oauth_url: str,
    pending_execution_id: str | None = None,
    resume_token: str | None = None,
) -> AuthRequiredPayload:
    """Build the structured response payload for an execution blocked on OAuth."""
    retry_token = resume_token or f"rt_{secrets.token_urlsafe(18)}"
    return AuthRequiredPayload(
        provider=provider,
        required_scopes=normalize_scopes(required_scopes),
        oauth_url=oauth_url,
        retry_token=retry_token,
        pending_execution_id=pending_execution_id,
        resume_token=retry_token,
        resume_strategy="client_resume",
        message=f"{provider} authorization is required before this tool can run.",
    )
