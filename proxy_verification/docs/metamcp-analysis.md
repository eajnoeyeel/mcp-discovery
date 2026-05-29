# MetaMCP 프록시 아키텍처 분석

> **소스**: [metatool-ai/mcp-server-metamcp](https://github.com/metatool-ai/mcp-server-metamcp) (TypeScript, v0.6.5)
> **분석일**: 2026-03-22

---

## 1. 개요

MetaMCP는 여러 MCP 서버를 하나의 통합 MCP 서버로 집약하는 프록시. 4가지 역할: Aggregator, Orchestrator, Middleware, Gateway.

---

## 2. 핵심 파일 구조

```
src/
├── index.ts              # CLI 엔트리포인트 (stdio/SSE/StreamableHTTP)
├── mcp-proxy.ts          # 핵심 프록시 로직 (createServer)
├── client.ts             # 백엔드 MCP 연결 (3종 transport)
├── sessions.ts           # 세션 풀 관리 (persistent connections)
├── fetch-metamcp.ts      # 백엔드 서버 설정 로드 (1초 TTL 캐시)
├── utils.ts              # sanitizeName, getSessionKey 등
├── tool-logs.ts          # 도구 호출 로깅
└── ...
```

---

## 3. 네임스페이스 전략

```typescript
// utils.ts
sanitizeName(name) → name.replace(/[^a-zA-Z0-9_-]/g, "")

// mcp-proxy.ts
const toolName = `${sanitizeName(serverName)}__${tool.name}`;
```

- **구분자**: `__` (이중 언더스코어)
- **형식**: `{sanitized_server_name}__{original_tool_name}`
- **역방향 파싱**: `name.split("__")[1]`

---

## 4. 도구 발견 (list_tools)

```typescript
server.setRequestHandler(ListToolsRequestSchema, async (request) => {
  const serverParams = await getMcpServers(true);
  const allTools: Tool[] = [];

  await Promise.allSettled(  // 병렬, 실패 허용
    Object.entries(serverParams).map(async ([uuid, params]) => {
      const session = await getSession(sessionKey, uuid, params);
      const result = await session.client.request(
        { method: "tools/list", params: {...} },
        ListToolsResultSchema
      );
      const toolsWithSource = result.tools.map(tool => {
        const toolName = `${sanitizeName(serverName)}__${tool.name}`;
        toolToClient[toolName] = session;       // tool→client 매핑
        toolToServerUuid[toolName] = uuid;
        return { ...tool, name: toolName };
      });
      allTools.push(...toolsWithSource);
    })
  );
  return { tools: allTools };
});
```

**패턴**: `Promise.allSettled` → 일부 실패해도 나머지 반환

---

## 5. 도구 호출 라우팅 (call_tool)

```typescript
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const originalToolName = name.split("__")[1];
  const clientForTool = toolToClient[name];

  if (!clientForTool) throw new Error(`Unknown tool: ${name}`);

  const result = await clientForTool.client.request(
    { method: "tools/call", params: { name: originalToolName, arguments: args } },
    CompatibilityCallToolResultSchema
  );
  return result;
});
```

---

## 6. 세션 관리 (Persistent Connections)

- `_sessions`: 세션 풀 (Record<string, ConnectedClient>)
- `initSessions()`: 서버 시작 시 모든 백엔드에 사전 연결
- `getSession()`: 캐시 히트 시 재사용, 미스 시 새 연결
- 세션 키: `UUID + SHA256(params)`
- 재연결: 3회 재시도, 2.5초 간격

---

## 7. 우리 프로토타입에 적용한 패턴

| MetaMCP 패턴 | 프로토타입 적용 | 비고 |
|-------------|--------------|------|
| `sanitizeName()__toolName` | ✅ 적용 | `sanitize_name()` + `__` 구분자 |
| `toolToClient` 인메모리 매핑 | ✅ 적용 | `_tool_registry` dict |
| `Promise.allSettled` | ✅ 적용 | `asyncio.gather(return_exceptions=True)` |
| Persistent sessions | ⚠️ Connect-per-call | Phase 13에서 전환 |
| `initSessions()` 사전 연결 | ⚠️ 시작 시 도구 발견만 | 세션 미유지 |
| SSE/StreamableHTTP | ❌ 미적용 | stdio만 |
| 도구 비활성 필터링 | ❌ 미적용 | Phase 13에서 |
| 도구 호출 로깅 | ❌ 미적용 | Phase 9에서 |
