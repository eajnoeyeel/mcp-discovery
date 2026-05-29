"""Unit tests for mlp.services.provider_service.ProviderService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class TestProviderServiceGetOrCreateProvider:
    async def test_returns_existing_provider_without_creating(self):
        from service.services.provider_service import ProviderService

        existing = {"user_id": "user-1", "display_name": "Acme"}
        repo = AsyncMock()
        repo.fetch_provider_by_user_id = AsyncMock(return_value=existing)
        service = ProviderService(repo=repo)

        result = await service.get_or_create_provider("user-1")

        assert result == existing
        repo.fetch_provider_by_user_id.assert_awaited_once_with("user-1")
        repo.create_provider.assert_not_awaited()

    async def test_creates_provider_when_not_found(self):
        from service.services.provider_service import ProviderService

        new_provider = {"user_id": "user-2", "display_name": None}
        repo = AsyncMock()
        repo.fetch_provider_by_user_id = AsyncMock(return_value=None)
        repo.create_provider = AsyncMock(return_value=new_provider)
        service = ProviderService(repo=repo)

        result = await service.get_or_create_provider("user-2")

        assert result == new_provider
        repo.create_provider.assert_awaited_once_with("user-2")

    async def test_does_not_call_create_when_provider_exists(self):
        from service.services.provider_service import ProviderService

        repo = AsyncMock()
        repo.fetch_provider_by_user_id = AsyncMock(return_value={"user_id": "user-3"})
        service = ProviderService(repo=repo)

        await service.get_or_create_provider("user-3")

        repo.create_provider.assert_not_awaited()


class TestProviderServiceGetProvider:
    async def test_returns_provider_when_found(self):
        from service.services.provider_service import ProviderService

        provider = {"user_id": "user-1", "org_name": "OrgA"}
        repo = AsyncMock()
        repo.fetch_provider_by_user_id = AsyncMock(return_value=provider)
        service = ProviderService(repo=repo)

        result = await service.get_provider("user-1")

        assert result == provider
        repo.fetch_provider_by_user_id.assert_awaited_once_with("user-1")

    async def test_returns_none_when_provider_not_found(self):
        from service.services.provider_service import ProviderService

        repo = AsyncMock()
        repo.fetch_provider_by_user_id = AsyncMock(return_value=None)
        service = ProviderService(repo=repo)

        result = await service.get_provider("user-missing")

        assert result is None


class TestProviderServiceUpdateProvider:
    async def test_update_with_valid_field_calls_repo(self):
        from service.services.provider_service import ProviderService

        updated = {"user_id": "user-1", "display_name": "New Name"}
        repo = AsyncMock()
        repo.update_provider = AsyncMock(return_value=updated)
        service = ProviderService(repo=repo)

        result = await service.update_provider("user-1", {"display_name": "New Name"})

        assert result == updated
        repo.update_provider.assert_awaited_once_with("user-1", {"display_name": "New Name"})

    async def test_update_filters_out_unknown_fields(self):
        from service.services.provider_service import ProviderService

        repo = AsyncMock()
        repo.update_provider = AsyncMock(return_value={"user_id": "user-1"})
        service = ProviderService(repo=repo)

        await service.update_provider(
            "user-1", {"display_name": "X", "malicious_field": "DROP TABLE"}
        )

        call_data = repo.update_provider.call_args.args[1]
        assert "malicious_field" not in call_data
        assert "display_name" in call_data

    async def test_update_raises_value_error_when_no_valid_fields(self):
        from service.services.provider_service import ProviderService

        repo = AsyncMock()
        service = ProviderService(repo=repo)

        with pytest.raises(ValueError, match="No valid fields"):
            await service.update_provider("user-1", {"unknown_field": "value"})

        repo.update_provider.assert_not_awaited()

    async def test_update_raises_value_error_for_empty_data(self):
        from service.services.provider_service import ProviderService

        repo = AsyncMock()
        service = ProviderService(repo=repo)

        with pytest.raises(ValueError, match="No valid fields"):
            await service.update_provider("user-1", {})

        repo.update_provider.assert_not_awaited()

    async def test_update_accepts_all_allowed_fields(self):
        from service.services.provider_service import ProviderService

        repo = AsyncMock()
        repo.update_provider = AsyncMock(return_value={"user_id": "user-1"})
        service = ProviderService(repo=repo)

        data = {"display_name": "A", "org_name": "OrgB", "contact_email": "a@b.com"}
        await service.update_provider("user-1", data)

        call_data = repo.update_provider.call_args.args[1]
        assert call_data == data

    async def test_update_org_name_field_is_allowed(self):
        from service.services.provider_service import ProviderService

        repo = AsyncMock()
        repo.update_provider = AsyncMock(return_value={"user_id": "user-1"})
        service = ProviderService(repo=repo)

        await service.update_provider("user-1", {"org_name": "MyOrg"})

        repo.update_provider.assert_awaited_once_with("user-1", {"org_name": "MyOrg"})

    async def test_update_contact_email_field_is_allowed(self):
        from service.services.provider_service import ProviderService

        repo = AsyncMock()
        repo.update_provider = AsyncMock(return_value={"user_id": "user-1"})
        service = ProviderService(repo=repo)

        await service.update_provider("user-1", {"contact_email": "dev@example.com"})

        repo.update_provider.assert_awaited_once_with(
            "user-1", {"contact_email": "dev@example.com"}
        )
