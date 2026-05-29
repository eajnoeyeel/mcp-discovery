from __future__ import annotations


def build_auth_probe_result(
    *,
    user_id: str | None,
    auth_source: str,
    issuer: str | None,
    status: str | None = None,
    error: str | None = None,
) -> dict[str, str | bool | None]:
    authenticated = bool(user_id)
    result: dict[str, str | bool | None] = {
        "authenticated": authenticated,
        "status": status or ("authenticated" if authenticated else "auth_required"),
        "user_id": user_id,
        "auth_source": auth_source,
        "issuer": issuer,
    }
    if error is not None:
        result["error"] = error
    return result
