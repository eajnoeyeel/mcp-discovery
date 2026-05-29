# Proxy MCP 검증 결과 보고서

> **검증일**: 2026-03-22
> **환경**: Python 3.14.2, Node.js v22.21.1, MCP SDK v1.26.0

---

## 1. 검증 개요

MCP Bridge/Router 패턴(Phase 13)의 핵심 가정을 본격 구현 전에 검증.
Python 프록시 MCP 서버가 여러 백엔드 MCP 서버의 도구를 집약하여 단일 진입점으로 제공하는 패턴이 E2E로 동작하는지 확인.

---

## 2. 검증 항목별 결과

| # | 항목 | 결과 | 지연시간 | 비고 |
|---|------|------|---------|------|
| 1 | Echo 서버 독립 동작 | PASS | ~600ms | Python→Python stdio 정상 |
| 2 | 프록시 도구 발견 | PASS | ~550ms | 2개 도구 발견 |
| 3 | 프록시 echo__echo 라우팅 | PASS | ~2500ms | 네임스페이스 라우팅 정상 |
| 4 | 프록시 echo__reverse 라우팅 | PASS | ~2200ms | 역방향 파싱 정상 |
| 5 | 프록시 filesystem__read_file | PASS | ~2400ms | Python→Node.js 크로스 언어 프록시 정상 |
| 6 | 프록시 memory entity 라운드트립 | PASS | ~3300ms | 상태 있는 프록시 정상 |

**전체**: 6/6 PASS, 28개 단위 테스트 모두 통과

---

## 3. 발견된 기술적 사실 (Findings)

### 3.1 MCP Python SDK API (v1.26.0)

**실제 import 경로:**
```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession
from mcp.types import Tool, TextContent
```

**서버 측 패턴:**
```python
server = Server("server-name")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(name="...", description="...", inputSchema={...})]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    return [TextContent(type="text", text="result")]

async with stdio_server() as (read, write):
    await server.run(read, write, server.create_initialization_options())
```

**클라이언트 측 패턴:**
```python
params = StdioServerParameters(command="...", args=[...])
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()      # → ListToolsResult
        result = await session.call_tool(name, args)  # → CallToolResult
```

### 3.2 stdio 이중 채널

**확인**: 프록시의 stdin/stdout(Claude Code용)과 백엔드 연결의 subprocess pipes는 완전히 독립.
- `stdio_client`는 내부적으로 `subprocess.Popen`으로 백엔드 프로세스를 생성
- 각 프로세스는 자체 stdin/stdout 파이프를 사용 → 충돌 없음
- 프록시가 3개 백엔드(echo, filesystem, memory)에 동시 연결해도 문제 없음

### 3.3 네임스페이스 구분자

**확인**: `__` 구분자가 MCP tool name으로 유효함.
- Claude Code, MCP SDK 모두 `echo__echo`, `filesystem__read_file` 등 `__` 포함 이름을 정상 처리
- `/`는 사용하지 않음 — MCP 스펙에서 유효성이 불확실

### 3.4 Connect-per-call 지연

- Echo(Python) 백엔드: ~600ms/call (프로세스 시작 + MCP 핸드셰이크)
- 프록시 경유 Echo: ~2200-2500ms (프록시 시작 + 프록시 내부 백엔드 연결)
- 프록시 경유 Node.js: ~2400-3300ms (npx 시작 지연 포함)

**결론**: Connect-per-call은 프로토타입용으로는 충분하나, 프로덕션(Phase 13)에서는 반드시 persistent connection 필요. 특히 Node.js 백엔드의 npx cold start가 큼.

### 3.5 크로스 언어 프록시 (Python → Node.js)

**확인**: Python MCP 프록시 → Node.js MCP 서버 완벽 동작.
- `@modelcontextprotocol/server-filesystem` (Node.js): 파일 읽기/쓰기 정상
- `@modelcontextprotocol/server-memory` (Node.js): entity 생성/검색 라운드트립 정상
- MCP 프로토콜이 언어 독립적이므로 transport만 같으면(stdio) 언어 무관

### 3.6 에러 전파 패턴

- **백엔드 부재**: `discover_tools()`에서 `asyncio.gather(return_exceptions=True)` 사용 → 실패한 백엔드는 경고만, 나머지 정상 반환
- **도구 호출 에러**: 서버 측에서 `ValueError` raise → MCP SDK가 `isError=True`인 CallToolResult로 변환하여 클라이언트에 전달 (프록시 크래시 없음)
- **Unknown tool**: MCP SDK는 `list_tools`에 없는 도구 호출 시에도 서버로 전달 (`"Tool 'X' not listed, no validation will be performed"` 경고)

### 3.7 pytest-asyncio + MCP SDK 호환성

- **문제**: async fixture에서 `stdio_client` context manager 사용 시 teardown에서 `RuntimeError: Attempted to exit cancel scope in a different task` 발생
- **원인**: pytest-asyncio가 fixture와 test를 서로 다른 task에서 실행할 수 있어 anyio의 cancel scope와 충돌
- **해결**: fixture 대신 `async def _run_with_session(fn)` 헬퍼 패턴 사용 — 세션 생성/사용/정리를 단일 함수 스코프 내에서 완료

---

## 4. Phase 13 구현에 대한 시사점

### 검증으로 확인된 가정
1. ✅ Python MCP 서버가 stdio 기반으로 다른 MCP 서버에 프록시 가능
2. ✅ 여러 백엔드의 도구를 네임스페이스화하여 단일 MCP로 노출 가능
3. ✅ Claude Code → Proxy → Backend → 결과 반환 전체 흐름 동작
4. ✅ Python ↔ Node.js 크로스 언어 프록시 가능
5. ✅ `__` 네임스페이스 구분자가 MCP 호환

### Phase 13에서 추가 필요 사항
- **Persistent connections**: `initSessions()` 패턴으로 서버 시작 시 사전 연결, 세션 풀 유지
- **재연결 로직**: MetaMCP처럼 3회 재시도 + 지수 백오프
- **타임아웃**: 백엔드 응답 타임아웃 설정 필요
- **헬스체크**: 주기적으로 백엔드 연결 상태 확인
- **동적 설정 리로드**: MetaMCP의 1초 TTL 캐시처럼 설정 변경 시 자동 반영
- **SSE/Streamable HTTP transport**: stdio 외 추가 transport 지원

---

## 5. 코드 스니펫 & 레퍼런스

### 재사용 가능 패턴: 도구 발견 + 네임스페이스

```python
# registry.py — Phase 13에서 그대로 재사용 가능
async def discover_tools(config: ProxyConfig) -> dict[str, ToolMapping]:
    tasks = [_discover_backend_tools(b) for b in config.backends]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # 실패 허용, 나머지 집약
```

### 재사용 가능 패턴: 프록시 라우팅

```python
# proxy_server.py — Phase 13의 execute_tool() 기반
@server.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    mapping = _tool_registry.get(name)
    if not mapping:
        raise ValueError(f"Unknown tool: {name}")
    backend = _backend_configs[mapping.server_id]
    result = await call_backend_tool(backend, mapping.original_tool_name, arguments)
    return [TextContent(type="text", text=item["text"]) for item in result]
```

### MCP SDK 버전 참고
- 테스트 시 `mcp>=1.26.0` 사용
- `Server.list_tools()`, `Server.call_tool()` 데코레이터 방식 안정적
- `ClientSession.call_tool(name, arguments)` — arguments는 `dict[str, Any] | None`
