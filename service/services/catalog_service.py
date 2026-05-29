"""Public catalog read service for frontend-facing API routes."""

from __future__ import annotations

import asyncio


class CatalogService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def get_platform_stats(self) -> dict:
        return await self._repo.fetch_platform_stats()

    async def list_servers(self, limit: int = 50, offset: int = 0) -> dict:
        items, total = await asyncio.gather(
            self._repo.fetch_servers(limit=limit, offset=offset),
            self._repo.fetch_server_count(),
        )
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    async def get_server_tools(self, server_id: str) -> dict:
        tools = await self._repo.fetch_server_tools(server_id)
        return {"server_id": server_id, "tools": tools}

    async def get_server_detail(self, server_id: str) -> dict:
        server = await self._repo.fetch_server(server_id)
        if server is None:
            raise LookupError(f"Server '{server_id}' not found")
        tools = await self._repo.fetch_server_tools(server_id)
        return {"server": server, "tools": tools}

    async def get_tool_public_stats(self, tool_id: str) -> dict | None:
        return await self._repo.fetch_tool_public_stats(tool_id)

    async def get_server_quality(self, server_id: str) -> dict:
        """Compute quality checklist for a server.

        GitHub-backed items (has_readme, has_license, has_release) were
        retired with the quality checklist GitHub integration feature.
        """
        data = await self._repo.fetch_server_quality_data(server_id)
        server = data["server"]
        tools = data["tools"]
        has_usage = data["has_usage"]

        geo_scores = [
            t["geo_score"]["total"]
            for t in tools
            if t.get("geo_score") and isinstance(t["geo_score"], dict)
        ]
        avg_geo = sum(geo_scores) / len(geo_scores) if geo_scores else 0.0

        items = [
            {
                "key": "has_description",
                "label": "Has description",
                "status": "pass" if server.get("description") else "fail",
            },
            {
                "key": "has_url",
                "label": "Has URL",
                "status": "pass" if server.get("url") else "fail",
            },
            {
                "key": "provides_tools",
                "label": "Provides tools",
                "status": "pass" if len(tools) > 0 else "fail",
            },
            {
                "key": "tool_quality",
                "label": "Tool definition quality",
                "status": "pass" if avg_geo >= 0.6 else "fail",
                "detail": f"Avg GEO: {avg_geo:.2f}" if geo_scores else "No GEO scores",
            },
            {
                "key": "active_usage",
                "label": "Active usage",
                "status": "pass" if has_usage else "fail",
            },
            {
                "key": "no_vulnerabilities",
                "label": "No known vulnerabilities",
                "status": "na",
                "detail": "Vulnerability scanning not yet available",
            },
            {
                "key": "author_verified",
                "label": "Author verified",
                "status": "pass" if server.get("owner_user_id") else "fail",
            },
        ]

        scored = [i for i in items if i["status"] != "na"]
        passed = sum(1 for i in scored if i["status"] == "pass")

        return {
            "items": items,
            "score": passed,
            "total": len(scored),
        }

    async def get_tool_detail(self, tool_id: str) -> dict:
        tool = await self._repo.fetch_tool(tool_id)
        if tool is None:
            raise LookupError(f"Tool '{tool_id}' not found")
        server = await self._repo.fetch_server(tool["server_id"])
        if server is None:
            raise LookupError(f"Tool '{tool_id}' not found")
        return {"tool": tool, "server": server}
