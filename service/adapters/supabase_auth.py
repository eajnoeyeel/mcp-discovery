"""Supabase Auth adapter for backend bearer-token validation."""

from __future__ import annotations

import httpx


class SupabaseAuthClient:
    """Validate Supabase access tokens and return the current user."""

    def __init__(self, url: str, service_key: str) -> None:
        self._url = url.rstrip("/")
        self._service_key = service_key

    async def get_user(self, access_token: str) -> dict:
        headers = {
            "apikey": self._service_key,
            "Authorization": f"Bearer {access_token}",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._url}/auth/v1/user", headers=headers)
            resp.raise_for_status()
            return resp.json()
