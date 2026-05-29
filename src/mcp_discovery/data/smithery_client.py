"""HTTP client for Smithery Registry API."""

import asyncio
import time
from urllib.parse import quote

import httpx
from loguru import logger

from mcp_discovery.models import TOOL_ID_SEPARATOR, MCPServer, MCPServerSummary, MCPTool


class SmitheryClient:
    """Smithery Registry API client with rate limiting and retry.

    Use as async context manager to manage httpx client lifecycle:
        async with SmitheryClient(base_url="...") as client:
            summaries = await client.fetch_all_summaries()
    """

    def __init__(self, base_url: str, rate_limit_seconds: float = 0.5) -> None:
        self.base_url = base_url.rstrip("/")
        self.rate_limit_seconds = rate_limit_seconds
        self._last_request_time: float = 0.0
        self._http_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "SmitheryClient":
        self._http_client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *args) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            raise RuntimeError(
                "SmitheryClient must be used as an async context manager: "
                "`async with SmitheryClient(...) as client:`"
            )
        return self._http_client

    async def _rate_limit(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_seconds:
            await asyncio.sleep(self.rate_limit_seconds - elapsed)
        self._last_request_time = time.monotonic()

    async def _request_with_retry(
        self, method: str, url: str, max_retries: int = 3, **kwargs
    ) -> httpx.Response:
        client = self._get_client()
        for attempt in range(max_retries):
            await self._rate_limit()
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                retryable = e.response.status_code in (429, 500, 502, 503, 504)
                if retryable and attempt < max_retries - 1:
                    delay = (2**attempt) * 1.0
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} after {delay}s: "
                        f"HTTP {e.response.status_code}"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt < max_retries - 1:
                    delay = (2**attempt) * 1.0
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} after {delay}s: {type(e).__name__}"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

    async def fetch_server_list(
        self, page: int = 1, page_size: int = 50
    ) -> tuple[list[MCPServerSummary], dict]:
        """Fetch one page of server summaries. Returns (summaries, pagination)."""
        response = await self._request_with_retry(
            "GET",
            f"{self.base_url}/servers",
            params={"page": page, "pageSize": page_size},
        )
        data = response.json()
        servers = [self.parse_server_summary(item) for item in data.get("servers", [])]
        pagination = data.get("pagination", {})
        return servers, pagination

    async def fetch_all_summaries(self, max_pages: int = 10) -> list[MCPServerSummary]:
        """Paginate through all servers.

        Stops when: (1) max_pages reached, (2) empty page, or
        (3) pagination.currentPage >= pagination.totalPages.
        """
        all_summaries: list[MCPServerSummary] = []
        for page in range(1, max_pages + 1):
            summaries, pagination = await self.fetch_server_list(page=page)
            if not summaries:
                break
            all_summaries.extend(summaries)
            logger.info(
                f"Fetched page {page}: {len(summaries)} servers (total: {len(all_summaries)})"
            )
            current = pagination.get("currentPage", page)
            total_pages = pagination.get("totalPages", max_pages)
            if current >= total_pages:
                break
        return all_summaries

    async def fetch_server_detail(self, qualified_name: str) -> MCPServer:
        """Fetch full server detail including tools."""
        response = await self._request_with_retry(
            "GET", f"{self.base_url}/servers/{quote(qualified_name, safe='')}"
        )
        data = response.json()
        return self.parse_server_detail(data)

    @staticmethod
    def parse_server_summary(raw: dict) -> MCPServerSummary:
        return MCPServerSummary(
            qualified_name=raw["qualifiedName"],
            display_name=raw["displayName"],
            description=raw.get("description"),
            use_count=raw.get("useCount", 0),
            is_verified=raw.get("verified", False),
            is_deployed=raw.get("isDeployed", False),
        )

    @staticmethod
    def parse_server_detail(raw: dict) -> MCPServer:
        qualified_name = raw["qualifiedName"]
        raw_tools = raw.get("tools") or []
        tools = []
        for t in raw_tools:
            name = t.get("name")
            if not name:
                logger.warning(f"Skipping tool with missing name in server '{qualified_name}'")
                continue
            tools.append(
                MCPTool(
                    server_id=qualified_name,
                    tool_name=name,
                    tool_id=f"{qualified_name}{TOOL_ID_SEPARATOR}{name}",
                    description=t.get("description"),
                    input_schema=t.get("inputSchema"),
                )
            )
        return MCPServer(
            server_id=qualified_name,
            name=raw["displayName"],
            description=raw.get("description"),
            homepage=raw.get("homepage"),
            tools=tools,
        )
