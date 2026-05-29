"""Provider lifecycle service."""

from __future__ import annotations

from typing import Any

from loguru import logger


class ProviderService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def get_or_create_provider(self, user_id: str) -> dict:
        """Get provider by user_id, or create if not exists."""
        provider = await self._repo.fetch_provider_by_user_id(user_id)
        if provider:
            return provider
        logger.info(f"Provider not found for user_id={user_id!r}, creating new")
        return await self._repo.create_provider(user_id)

    async def get_provider(self, user_id: str) -> dict | None:
        """Get provider by user_id."""
        return await self._repo.fetch_provider_by_user_id(user_id)

    async def update_provider(self, user_id: str, data: dict[str, Any]) -> dict:
        """Update provider profile fields."""
        allowed_fields = {"display_name", "org_name", "contact_email"}
        filtered = {k: v for k, v in data.items() if k in allowed_fields}
        if not filtered:
            raise ValueError("No valid fields to update")
        logger.info(f"Updating provider user_id={user_id!r} fields={list(filtered.keys())}")
        return await self._repo.update_provider(user_id, filtered)
