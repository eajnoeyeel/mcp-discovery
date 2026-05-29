"""Optimizer MCP 서버 — 프로덕션 구조 검증용.

Claude Code에 find_best_tool / execute_tool 2개 도구만 노출.
백엔드 도구를 직접 노출하지 않고, 추천→실행 2단계 흐름을 제공한다.

Phase 13 프로덕션 구조의 프로토타입.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.models import BackendServerConfig, ProxyConfig, ToolMapping
from src.proxy_client import call_backend_tool
from src.registry import discover_tools


# 전역 상태
_tool_registry: dict[str, ToolMapping] = {}
_backend_configs: dict[str, BackendServerConfig] = {}

server = Server("optimizer-mcp")


def _load_config() -> ProxyConfig:
    """config.json에서 백엔드 설정 로드."""
    config_path = Path(__file__).parent.parent / "config.json"
    if not config_path.exists():
        print(f"Warning: {config_path} not found, using empty config", file=sys.stderr)
        return ProxyConfig(backends=[])
    with open(config_path) as f:
        data = json.load(f)
    return ProxyConfig(**data)


async def _init_registry() -> None:
    """서버 시작 시 모든 백엔드에서 도구를 발견하고 내부 레지스트리 구성."""
    config = _load_config()
    for backend in config.backends:
        _backend_configs[backend.server_id] = backend
    mappings = await discover_tools(config)
    _tool_registry.update(mappings)
    print(
        f"[optimizer] Discovered {len(_tool_registry)} tools from {len(config.backends)} backends",
        file=sys.stderr,
    )


def _find_best_tool(query: str) -> list[dict[str, Any]]:
    """간단한 키워드 매칭 기반 도구 추천.

    프로토타입: 쿼리 단어가 도구의 이름/설명에 포함되면 점수 부여.
    Phase 13 프로덕션에서는 2-stage retrieval pipeline으로 교체.
    """
    query_lower = query.lower()
    query_words = set(query_lower.split())

    scored: list[tuple[float, ToolMapping]] = []
    for mapping in _tool_registry.values():
        searchable = f"{mapping.tool_id} {mapping.original_tool_name} {mapping.description}".lower()
        # 매칭 단어 수 / 전체 쿼리 단어 수 = 점수
        matched = sum(1 for w in query_words if w in searchable)
        if matched > 0:
            score = matched / len(query_words)
            scored.append((score, mapping))

    # 점수 내림차순 정렬, 상위 5개
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "tool_id": mapping.tool_id,
            "score": round(score, 3),
            "description": mapping.description,
            "input_schema": mapping.input_schema,
        }
        for score, mapping in scored[:5]
    ]


# ── MCP 도구 정의 ────────────────────────────────────────────


FIND_BEST_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "자연어로 된 도구 검색 쿼리. 예: 'echo a message back to me'",
        },
    },
    "required": ["query"],
}

EXECUTE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool_id": {
            "type": "string",
            "description": "실행할 도구의 ID. find_best_tool 결과에서 얻은 tool_id를 사용.",
        },
        "arguments": {
            "type": "object",
            "description": "도구에 전달할 인자. find_best_tool 결과의 input_schema 참고.",
        },
    },
    "required": ["tool_id", "arguments"],
}


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """find_best_tool, execute_tool 2개만 노출."""
    return [
        Tool(
            name="find_best_tool",
            description="자연어 쿼리로 최적의 MCP 도구를 추천합니다. 추천 결과의 tool_id를 execute_tool에 전달하세요.",
            inputSchema=FIND_BEST_TOOL_SCHEMA,
        ),
        Tool(
            name="execute_tool",
            description="find_best_tool이 추천한 도구를 실행합니다. tool_id와 arguments를 전달하세요.",
            inputSchema=EXECUTE_TOOL_SCHEMA,
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """도구 호출 처리: find_best_tool 또는 execute_tool."""
    if name == "find_best_tool":
        query = arguments.get("query", "")
        recommendations = _find_best_tool(query)
        return [
            TextContent(
                type="text",
                text=json.dumps({"recommendations": recommendations}, ensure_ascii=False),
            )
        ]

    elif name == "execute_tool":
        tool_id = arguments.get("tool_id", "")
        tool_args = arguments.get("arguments", {})

        mapping = _tool_registry.get(tool_id)
        if not mapping:
            raise ValueError(f"Unknown tool_id: {tool_id}")

        backend = _backend_configs.get(mapping.server_id)
        if not backend:
            raise ValueError(f"Unknown backend: {mapping.server_id}")

        result = await call_backend_tool(backend, mapping.original_tool_name, tool_args)
        return [TextContent(type="text", text=item["text"]) for item in result]

    else:
        raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    """Optimizer MCP 서버 메인 엔트리포인트."""
    await _init_registry()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
