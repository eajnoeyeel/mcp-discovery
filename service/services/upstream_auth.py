"""Upstream provider MCP authentication helpers."""

from __future__ import annotations

import re
from typing import Protocol

from service.services.contracts import UpstreamAuthConfig

_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")


class UpstreamAuthError(ValueError):
    """Raised when provider upstream auth metadata is invalid."""


class OAuthTokenServiceLike(Protocol):
    """Minimal protocol for resolving refreshed provider OAuth access tokens."""

    async def get_access_token(self, server_id: str) -> str: ...


def _validate_header_name(name: str) -> None:
    if not _HEADER_NAME_RE.fullmatch(name):
        raise UpstreamAuthError(f"Invalid upstream header name: {name}")


def build_upstream_headers(config: UpstreamAuthConfig | None) -> dict[str, str]:
    """Return HTTP headers to attach to the provider MCP upstream request."""
    if config is None or config.auth_type == "none":
        return {}

    if config.auth_type == "bearer":
        if not config.bearer_token:
            raise UpstreamAuthError("bearer_token is required for bearer upstream auth")
        return {"Authorization": f"Bearer {config.bearer_token}"}

    if config.auth_type == "api_key_header":
        if not config.api_key_header_name:
            raise UpstreamAuthError(
                "api_key_header_name is required for api_key_header upstream auth"
            )
        if not config.api_key:
            raise UpstreamAuthError("api_key is required for api_key_header upstream auth")
        _validate_header_name(config.api_key_header_name)
        return {config.api_key_header_name: config.api_key}

    if config.auth_type == "custom_headers":
        headers: dict[str, str] = {}
        for name, value in config.headers.items():
            _validate_header_name(name)
            headers[name] = str(value)
        return headers

    raise UpstreamAuthError(f"Unsupported upstream auth type: {config.auth_type}")


async def resolve_upstream_headers(
    server_id: str,
    config: UpstreamAuthConfig | None,
    *,
    oauth_token_service: OAuthTokenServiceLike | None = None,
) -> dict[str, str]:
    """Resolve execution headers, including OAuth-backed sessions."""
    if config is not None and config.auth_type == "oauth_session":
        if oauth_token_service is None:
            raise UpstreamAuthError(
                "OAuth token service is required for oauth_session upstream auth"
            )
        token = await oauth_token_service.get_access_token(server_id)
        if not token:
            raise UpstreamAuthError("OAuth token service returned an empty access token")
        return {"Authorization": f"Bearer {token}"}

    return build_upstream_headers(config)
