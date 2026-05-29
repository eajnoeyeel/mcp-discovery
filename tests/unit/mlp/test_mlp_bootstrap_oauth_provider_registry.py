from __future__ import annotations

import json

import httpx
import pytest

from service.scripts.bootstrap_oauth_provider_registry import (
    interpolate_env_placeholders,
    load_registry_entries,
)


def test_load_registry_entries_interpolates_env_placeholders(monkeypatch) -> None:
    monkeypatch.setenv("APIFY_OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setenv(
        "APIFY_OAUTH_REDIRECT_URI", "https://mlp.example.com/api/oauth/providers/apify/callback"
    )

    payload = json.dumps(
        [
            {
                "provider_key": "apify",
                "display_name": "Apify",
                "authorize_url": "${APIFY_OAUTH_AUTHORIZE_URL}",
                "token_url": "${APIFY_OAUTH_TOKEN_URL}",
                "client_id": "${APIFY_OAUTH_CLIENT_ID}",
                "redirect_uri": "${APIFY_OAUTH_REDIRECT_URI}",
                "default_scopes": [],
                "scope_aliases": {},
                "supports_refresh_token": True,
                "pkce_required": True,
                "enabled": True,
                "metadata": {},
            }
        ]
    )

    monkeypatch.setenv("APIFY_OAUTH_AUTHORIZE_URL", "https://auth.apify.example/authorize")
    monkeypatch.setenv("APIFY_OAUTH_TOKEN_URL", "https://auth.apify.example/token")

    entries = load_registry_entries(payload)

    assert entries[0]["client_id"] == "client-123"
    assert (
        entries[0]["redirect_uri"] == "https://mlp.example.com/api/oauth/providers/apify/callback"
    )
    assert entries[0]["authorize_url"] == "https://auth.apify.example/authorize"
    assert entries[0]["token_url"] == "https://auth.apify.example/token"


def test_interpolate_env_placeholders_rejects_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_ENV", raising=False)

    with pytest.raises(ValueError, match="Missing required environment variable"):
        interpolate_env_placeholders("${MISSING_ENV}")


@pytest.mark.asyncio
async def test_upsert_registry_entries_posts_merge_duplicate_payload() -> None:
    from service.scripts.bootstrap_oauth_provider_registry import upsert_registry_entries

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["prefer"] = request.headers["Prefer"]
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json=[])

    entries = [
        {
            "provider_key": "apify",
            "display_name": "Apify",
            "authorize_url": "https://auth.apify.example/authorize",
            "token_url": "https://auth.apify.example/token",
            "client_id": "client-123",
            "redirect_uri": "https://mlp.example.com/api/oauth/providers/apify/callback",
            "default_scopes": [],
            "scope_aliases": {},
            "supports_refresh_token": True,
            "pkce_required": True,
            "enabled": True,
            "metadata": {},
        }
    ]

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await upsert_registry_entries(
            client=client,
            supabase_url="https://db.example.co",
            service_key="service-key",
            entries=entries,
        )

    assert seen == {
        "method": "POST",
        "url": "https://db.example.co/rest/v1/oauth_provider_registry?on_conflict=provider_key",
        "prefer": "resolution=merge-duplicates,return=minimal",
        "payload": entries,
    }
