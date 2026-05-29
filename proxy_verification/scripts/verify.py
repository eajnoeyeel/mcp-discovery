"""Proxy MCP 검증 스크립트 — PASS/FAIL 리포트 출력.

사용법: uv run python scripts/verify.py
"""

import asyncio
import os
import shutil
import time
from dataclasses import dataclass

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from src.models import BackendServerConfig
from src.proxy_client import call_backend_tool
from src.registry import discover_tools
from src.models import ProxyConfig


@dataclass
class VerifyResult:
    name: str
    passed: bool
    duration_ms: float
    detail: str = ""


HAS_NPX = shutil.which("npx") is not None

ECHO_BACKEND = BackendServerConfig(
    server_id="echo",
    command="uv",
    args=["run", "python", "-m", "src.echo_server"],
)

PROXY_SERVER_PARAMS = StdioServerParameters(
    command="uv",
    args=["run", "python", "-m", "src.proxy_server"],
)


async def verify_echo_standalone() -> VerifyResult:
    """[1] Echo 서버 독립 동작 검증."""
    start = time.monotonic()
    try:
        result = await call_backend_tool(ECHO_BACKEND, "echo", {"message": "verify"})
        passed = result[0]["text"] == "verify"
        return VerifyResult(
            "Echo server standalone",
            passed,
            (time.monotonic() - start) * 1000,
        )
    except Exception as e:
        return VerifyResult("Echo server standalone", False, (time.monotonic() - start) * 1000, str(e))


async def verify_proxy_discovers_tools() -> VerifyResult:
    """[2] 프록시가 echo 도구를 발견하는지 검증."""
    start = time.monotonic()
    try:
        config = ProxyConfig(backends=[ECHO_BACKEND])
        mappings = await discover_tools(config)
        passed = "echo__echo" in mappings and "echo__reverse" in mappings
        return VerifyResult(
            "Proxy discovers echo tools",
            passed,
            (time.monotonic() - start) * 1000,
            f"Found {len(mappings)} tools",
        )
    except Exception as e:
        return VerifyResult("Proxy discovers echo tools", False, (time.monotonic() - start) * 1000, str(e))


async def verify_proxy_echo() -> VerifyResult:
    """[3] 프록시를 통해 echo__echo 호출 검증."""
    start = time.monotonic()
    try:
        async with stdio_client(PROXY_SERVER_PARAMS) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("echo__echo", {"message": "proxy-test"})
                passed = result.content[0].text == "proxy-test"
                return VerifyResult(
                    "Proxy routes echo__echo",
                    passed,
                    (time.monotonic() - start) * 1000,
                )
    except Exception as e:
        return VerifyResult("Proxy routes echo__echo", False, (time.monotonic() - start) * 1000, str(e))


async def verify_proxy_reverse() -> VerifyResult:
    """[4] 프록시를 통해 echo__reverse 호출 검증."""
    start = time.monotonic()
    try:
        async with stdio_client(PROXY_SERVER_PARAMS) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("echo__reverse", {"text": "proxy"})
                passed = result.content[0].text == "yxorp"
                return VerifyResult(
                    "Proxy routes echo__reverse",
                    passed,
                    (time.monotonic() - start) * 1000,
                )
    except Exception as e:
        return VerifyResult("Proxy routes echo__reverse", False, (time.monotonic() - start) * 1000, str(e))


async def verify_proxy_filesystem() -> VerifyResult:
    """[5] 프록시를 통해 filesystem__read_file 호출 검증."""
    if not HAS_NPX:
        return VerifyResult("Proxy filesystem read_file", False, 0, "SKIP: npx not available")
    start = time.monotonic()
    try:
        test_dir = "/tmp/mcp-test"
        os.makedirs(test_dir, exist_ok=True)
        test_file = os.path.join(test_dir, "verify.txt")
        with open(test_file, "w") as f:
            f.write("verify-content")

        async with stdio_client(PROXY_SERVER_PARAMS) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("filesystem__read_file", {"path": test_file})
                passed = "verify-content" in result.content[0].text
                return VerifyResult(
                    "Proxy filesystem read_file",
                    passed,
                    (time.monotonic() - start) * 1000,
                )
    except Exception as e:
        return VerifyResult("Proxy filesystem read_file", False, (time.monotonic() - start) * 1000, str(e))


async def verify_proxy_memory() -> VerifyResult:
    """[6] 프록시를 통해 memory entity 생성→검색 검증."""
    if not HAS_NPX:
        return VerifyResult("Proxy memory entity roundtrip", False, 0, "SKIP: npx not available")
    start = time.monotonic()
    try:
        async with stdio_client(PROXY_SERVER_PARAMS) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # entity 생성
                await session.call_tool(
                    "memory__create_entities",
                    {
                        "entities": [
                            {
                                "name": "VerifyEntity",
                                "entityType": "test",
                                "observations": ["Verification test entity"],
                            }
                        ]
                    },
                )

                # entity 검색
                result = await session.call_tool(
                    "memory__search_nodes",
                    {"query": "VerifyEntity"},
                )
                passed = "VerifyEntity" in result.content[0].text
                return VerifyResult(
                    "Proxy memory entity roundtrip",
                    passed,
                    (time.monotonic() - start) * 1000,
                )
    except Exception as e:
        return VerifyResult("Proxy memory entity roundtrip", False, (time.monotonic() - start) * 1000, str(e))


async def main() -> None:
    print("\n=== Proxy MCP Verification ===\n")

    verifications = [
        verify_echo_standalone,
        verify_proxy_discovers_tools,
        verify_proxy_echo,
        verify_proxy_reverse,
        verify_proxy_filesystem,
        verify_proxy_memory,
    ]

    results: list[VerifyResult] = []
    for i, verify_fn in enumerate(verifications, 1):
        result = await verify_fn()
        results.append(result)
        status = "PASS" if result.passed else ("SKIP" if "SKIP" in result.detail else "FAIL")
        detail = f" ({result.detail})" if result.detail else ""
        print(f"[{i}/{len(verifications)}] {result.name} {'.' * (40 - len(result.name))} {status} ({result.duration_ms:.0f}ms){detail}")

    print()
    passed = sum(1 for r in results if r.passed)
    skipped = sum(1 for r in results if "SKIP" in r.detail)
    failed = len(results) - passed - skipped
    print(f"Results: {passed} passed, {skipped} skipped, {failed} failed")

    if failed > 0:
        print("\nFailed verifications:")
        for r in results:
            if not r.passed and "SKIP" not in r.detail:
                print(f"  - {r.name}: {r.detail}")


if __name__ == "__main__":
    asyncio.run(main())
