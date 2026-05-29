"""Unit tests for mlp.services.catalog_service.CatalogService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class TestCatalogServiceGetPlatformStats:
    async def test_get_platform_stats_returns_repo_result(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_platform_stats = AsyncMock(return_value={"servers": 10, "tools": 42})
        service = CatalogService(repo=repo)

        result = await service.get_platform_stats()

        assert result == {"servers": 10, "tools": 42}
        repo.fetch_platform_stats.assert_awaited_once()

    async def test_get_platform_stats_propagates_repo_error(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_platform_stats = AsyncMock(side_effect=RuntimeError("DB down"))
        service = CatalogService(repo=repo)

        with pytest.raises(RuntimeError, match="DB down"):
            await service.get_platform_stats()


class TestCatalogServiceListServers:
    async def test_list_servers_returns_items_with_limit_and_offset(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_servers = AsyncMock(return_value=[{"server_id": "srv-1", "name": "Alpha"}])
        service = CatalogService(repo=repo)

        result = await service.list_servers(limit=20, offset=5)

        assert result["items"] == [{"server_id": "srv-1", "name": "Alpha"}]
        assert result["limit"] == 20
        assert result["offset"] == 5
        repo.fetch_servers.assert_awaited_once_with(limit=20, offset=5)

    async def test_list_servers_uses_default_limit_and_offset(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_servers = AsyncMock(return_value=[])
        service = CatalogService(repo=repo)

        result = await service.list_servers()

        assert result["limit"] == 50
        assert result["offset"] == 0
        repo.fetch_servers.assert_awaited_once_with(limit=50, offset=0)

    async def test_list_servers_returns_empty_items_when_repo_returns_empty(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_servers = AsyncMock(return_value=[])
        service = CatalogService(repo=repo)

        result = await service.list_servers()

        assert result["items"] == []


class TestCatalogServiceGetServerTools:
    async def test_get_server_tools_returns_server_id_and_tools(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_server_tools = AsyncMock(
            return_value=[{"tool_id": "srv-1::search", "tool_name": "search"}]
        )
        service = CatalogService(repo=repo)

        result = await service.get_server_tools("srv-1")

        assert result["server_id"] == "srv-1"
        assert len(result["tools"]) == 1
        assert result["tools"][0]["tool_id"] == "srv-1::search"
        repo.fetch_server_tools.assert_awaited_once_with("srv-1")

    async def test_get_server_tools_returns_empty_tools_when_none_found(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_server_tools = AsyncMock(return_value=[])
        service = CatalogService(repo=repo)

        result = await service.get_server_tools("srv-missing")

        assert result["server_id"] == "srv-missing"
        assert result["tools"] == []


class TestCatalogServiceGetServerDetail:
    async def test_get_server_detail_returns_server_and_tools(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_server = AsyncMock(return_value={"server_id": "srv-1", "name": "Alpha"})
        repo.fetch_server_tools = AsyncMock(
            return_value=[{"tool_id": "srv-1::ping", "tool_name": "ping"}]
        )
        service = CatalogService(repo=repo)

        result = await service.get_server_detail("srv-1")

        assert result["server"] == {"server_id": "srv-1", "name": "Alpha"}
        assert result["tools"][0]["tool_id"] == "srv-1::ping"
        repo.fetch_server.assert_awaited_once_with("srv-1")
        repo.fetch_server_tools.assert_awaited_once_with("srv-1")

    async def test_get_server_detail_raises_lookup_error_when_server_not_found(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_server = AsyncMock(return_value=None)
        service = CatalogService(repo=repo)

        with pytest.raises(LookupError, match="srv-missing"):
            await service.get_server_detail("srv-missing")

    async def test_get_server_detail_does_not_fetch_tools_when_server_missing(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_server = AsyncMock(return_value=None)
        repo.fetch_server_tools = AsyncMock()
        service = CatalogService(repo=repo)

        with pytest.raises(LookupError):
            await service.get_server_detail("srv-missing")

        repo.fetch_server_tools.assert_not_awaited()


class TestCatalogServiceGetToolPublicStats:
    async def test_get_tool_public_stats_returns_repo_result_when_found(self):
        from service.services.catalog_service import CatalogService

        stats = {"call_count": 100, "success_rate": 0.99, "avg_latency_ms": 42.0}
        repo = AsyncMock()
        repo.fetch_tool_public_stats = AsyncMock(return_value=stats)
        service = CatalogService(repo=repo)

        result = await service.get_tool_public_stats("srv::tool")

        assert result == stats
        repo.fetch_tool_public_stats.assert_awaited_once_with("srv::tool")

    async def test_get_tool_public_stats_returns_none_when_not_found(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_tool_public_stats = AsyncMock(return_value=None)
        service = CatalogService(repo=repo)

        result = await service.get_tool_public_stats("srv::missing")

        assert result is None


class TestCatalogServiceGetToolDetail:
    async def test_get_tool_detail_returns_tool_and_server(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_tool = AsyncMock(return_value={"tool_id": "srv-1::search", "server_id": "srv-1"})
        repo.fetch_server = AsyncMock(return_value={"server_id": "srv-1", "name": "Alpha"})
        service = CatalogService(repo=repo)

        result = await service.get_tool_detail("srv-1::search")

        assert result["tool"]["tool_id"] == "srv-1::search"
        assert result["server"]["server_id"] == "srv-1"
        repo.fetch_tool.assert_awaited_once_with("srv-1::search")
        repo.fetch_server.assert_awaited_once_with("srv-1")

    async def test_get_tool_detail_raises_lookup_error_when_tool_not_found(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_tool = AsyncMock(return_value=None)
        service = CatalogService(repo=repo)

        with pytest.raises(LookupError, match="srv::missing"):
            await service.get_tool_detail("srv::missing")

    async def test_get_tool_detail_does_not_fetch_server_when_tool_missing(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_tool = AsyncMock(return_value=None)
        repo.fetch_server = AsyncMock()
        service = CatalogService(repo=repo)

        with pytest.raises(LookupError):
            await service.get_tool_detail("srv::missing")

        repo.fetch_server.assert_not_awaited()

    async def test_get_tool_detail_fetches_server_using_tool_server_id(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_tool = AsyncMock(return_value={"tool_id": "srv-2::ping", "server_id": "srv-2"})
        repo.fetch_server = AsyncMock(return_value={"server_id": "srv-2", "name": "Beta"})
        service = CatalogService(repo=repo)

        await service.get_tool_detail("srv-2::ping")

        repo.fetch_server.assert_awaited_once_with("srv-2")

    async def test_get_tool_detail_raises_lookup_error_when_server_unpublished(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_tool = AsyncMock(return_value={"tool_id": "srv-3::tool", "server_id": "srv-3"})
        repo.fetch_server = AsyncMock(return_value=None)
        service = CatalogService(repo=repo)

        with pytest.raises(LookupError, match="srv-3::tool"):
            await service.get_tool_detail("srv-3::tool")

    async def test_get_tool_detail_returns_200_when_server_published(self):
        from service.services.catalog_service import CatalogService

        repo = AsyncMock()
        repo.fetch_tool = AsyncMock(return_value={"tool_id": "srv-4::run", "server_id": "srv-4"})
        repo.fetch_server = AsyncMock(
            return_value={"server_id": "srv-4", "name": "Gamma", "is_published": True}
        )
        service = CatalogService(repo=repo)

        result = await service.get_tool_detail("srv-4::run")

        assert result["tool"]["tool_id"] == "srv-4::run"
        assert result["server"]["server_id"] == "srv-4"
        assert result["server"]["is_published"] is True
