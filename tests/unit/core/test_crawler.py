"""Tests for SmitheryCrawler — orchestrates the crawling pipeline."""

from unittest.mock import AsyncMock

import pytest

from mcp_discovery.data.crawler import SmitheryCrawler
from mcp_discovery.data.smithery_client import SmitheryClient
from mcp_discovery.models import MCPServer, MCPServerSummary, MCPTool


@pytest.fixture
def mock_client() -> SmitheryClient:
    client = AsyncMock(spec=SmitheryClient)
    client.rate_limit_seconds = 0.5

    summaries = [
        MCPServerSummary(
            qualified_name="@a/server",
            display_name="Server A",
            use_count=100,
            is_deployed=True,
        ),
        MCPServerSummary(
            qualified_name="@b/server",
            display_name="Server B",
            use_count=50,
            is_deployed=True,
        ),
    ]
    client.fetch_all_summaries = AsyncMock(return_value=summaries)

    servers = {
        "@a/server": MCPServer(
            server_id="@a/server",
            name="Server A",
            tools=[
                MCPTool(
                    server_id="@a/server",
                    tool_name="tool1",
                    tool_id="@a/server::tool1",
                    description="Tool 1",
                ),
            ],
        ),
        "@b/server": MCPServer(
            server_id="@b/server",
            name="Server B",
            tools=[],
        ),
    }
    client.fetch_server_detail = AsyncMock(side_effect=lambda qn: servers[qn])
    return client


class TestSmitheryCrawler:
    async def test_crawl_returns_servers(self, mock_client):
        crawler = SmitheryCrawler(client=mock_client)
        servers = await crawler.crawl(max_pages=1, max_servers=10)
        assert len(servers) == 2
        assert servers[0].server_id == "@a/server"
        assert len(servers[0].tools) == 1

    async def test_crawl_respects_max_servers(self, mock_client):
        crawler = SmitheryCrawler(client=mock_client)
        servers = await crawler.crawl(max_pages=1, max_servers=1)
        assert len(servers) == 1

    async def test_crawl_calls_detail_for_each(self, mock_client):
        crawler = SmitheryCrawler(client=mock_client)
        await crawler.crawl(max_pages=1, max_servers=10)
        assert mock_client.fetch_server_detail.call_count == 2

    async def test_crawl_skips_failed_detail(self, mock_client):
        mock_client.fetch_server_detail = AsyncMock(
            side_effect=[
                MCPServer(server_id="@a/server", name="A", tools=[]),
                Exception("API error"),
            ]
        )
        crawler = SmitheryCrawler(client=mock_client)
        servers = await crawler.crawl(max_pages=1, max_servers=10)
        assert len(servers) == 1


class TestSaveLoad:
    def test_save_and_load_roundtrip(self, tmp_path):
        server = MCPServer(
            server_id="@test/srv",
            name="Test",
            description="Test server",
            tools=[
                MCPTool(
                    server_id="@test/srv",
                    tool_name="my_tool",
                    tool_id="@test/srv::my_tool",
                    description="A tool",
                    input_schema={
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                ),
            ],
        )
        crawler = SmitheryCrawler(client=AsyncMock())
        path = crawler.save([server], output_dir=tmp_path)
        assert path.exists()
        assert path.suffix == ".jsonl"

        loaded = SmitheryCrawler.load(path)
        assert len(loaded) == 1
        assert loaded[0].server_id == "@test/srv"
        assert len(loaded[0].tools) == 1
        assert loaded[0].tools[0].tool_id == "@test/srv::my_tool"

    def test_save_creates_directory(self, tmp_path):
        new_dir = tmp_path / "sub" / "dir"
        crawler = SmitheryCrawler(client=AsyncMock())
        path = crawler.save([], output_dir=new_dir)
        assert path.exists()

    def test_load_empty_file(self, tmp_path):
        f = tmp_path / "servers.jsonl"
        f.write_text("")
        loaded = SmitheryCrawler.load(f)
        assert loaded == []
