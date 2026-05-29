"""Crawling orchestrator — combines SmitheryClient + ServerSelector."""

from pathlib import Path

from loguru import logger

from mcp_discovery.data.server_selector import select_servers
from mcp_discovery.data.smithery_client import SmitheryClient
from mcp_discovery.models import MCPServer


class SmitheryCrawler:
    """Orchestrates server list fetch -> selection -> detail fetch."""

    def __init__(self, client: SmitheryClient) -> None:
        self.client = client

    async def crawl(
        self,
        max_pages: int = 10,
        curated_list: Path | None = None,
        max_servers: int = 100,
    ) -> list[MCPServer]:
        summaries = await self.client.fetch_all_summaries(max_pages=max_pages)
        logger.info(f"Fetched {len(summaries)} server summaries")

        selected = select_servers(
            summaries,
            curated_list=curated_list,
            max_servers=max_servers,
        )
        logger.info(f"Selected {len(selected)} servers for detail fetch")

        servers: list[MCPServer] = []
        for i, summary in enumerate(selected, 1):
            try:
                server = await self.client.fetch_server_detail(summary.qualified_name)
                servers.append(server)
                logger.info(
                    f"Fetched {i}/{len(selected)}: {summary.qualified_name} "
                    f"({len(server.tools)} tools)"
                )
            except Exception as e:
                logger.warning(f"Failed {i}/{len(selected)}: {summary.qualified_name} — {e}")
        return servers

    def save(
        self,
        servers: list[MCPServer],
        output_dir: Path = Path("data/raw"),
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "servers.jsonl"
        with path.open("w") as f:
            for server in servers:
                f.write(server.model_dump_json() + "\n")
        logger.info(f"Saved {len(servers)} servers to {path}")
        return path

    @staticmethod
    def load(path: Path) -> list[MCPServer]:
        servers: list[MCPServer] = []
        text = path.read_text().strip()
        if not text:
            return servers
        for line in text.splitlines():
            if line.strip():
                servers.append(MCPServer.model_validate_json(line))
        return servers
