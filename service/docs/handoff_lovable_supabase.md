# MCP Discovery ↔ Supabase 연결 핸드오프

> 작성: 2026-04-05, Master 세션에서 전달

---

## 1. Supabase 연결 정보

- **SUPABASE_URL**: `.env`의 `SUPABASE_URL` 값 사용
- **SUPABASE_ANON_KEY**: `.env`의 `SUPABASE_ANON_KEY` 값 사용 (프론트엔드용)
- `SUPABASE_SERVICE_KEY`는 **절대 프론트엔드에 노출하지 않음** (Lambda 전용)

---

## 2. 현재 Supabase 데이터 현황

| 테이블 | 행 수 | 비고 |
|--------|------|------|
| `mcp_servers` | 292 | MCP-Zero pool, `index_status='indexed'` |
| `mcp_tools` | 2,763 | GEO score 6D 포함, 모두 `indexed` |
| `query_logs` | 0 | 아직 검색 트래픽 없음 |
| `execution_logs` | 0 | 아직 실행 트래픽 없음 |

---

## 3. 사용 가능한 Views / RPCs

### RPC: `get_platform_stats()`
```sql
-- 호출: POST /rest/v1/rpc/get_platform_stats
-- 반환 예시:
{"server_count": 292, "tool_count": 2763, "indexed_count": 2763, "avg_geo_score": 0.11}
```
용도: 랜딩 페이지 통계

### RPC: `search_tools_fts(search_query, result_limit, status_filter)`
```sql
-- 호출: POST /rest/v1/rpc/search_tools_fts
-- body: {"search_query": "github", "result_limit": 5}
-- status_filter 기본값: 'indexed' (생략 가능)
```
용도: 검색 페이지 (lexical fallback). **의미 검색은 Lambda API 필요 (아직 미배포)**

### View: `provider_dashboard_snapshot`
```sql
-- 호출: GET /rest/v1/provider_dashboard_snapshot
-- 컬럼: server_id, server_name, server_description, tool_count,
--        avg_geo_score, min_geo_score, max_geo_score, low_score_count, indexed_count
```
용도: Provider Dashboard 서버 목록 + GEO 집계

### View: `server_tool_counts`
```sql
-- 호출: GET /rest/v1/server_tool_counts
-- 컬럼: server_id, tool_count
```
용도: /servers 목록에서 도구 수 표시

---

## 4. 테이블 직접 쿼리

### `mcp_servers`
```
GET /rest/v1/mcp_servers?select=server_id,name,description,url,tags,index_status
```

### `mcp_tools`
```
GET /rest/v1/mcp_tools?select=tool_id,server_id,tool_name,description,input_schema,geo_score,index_status

# 특정 서버의 도구만:
GET /rest/v1/mcp_tools?server_id=eq.github&select=*

# 특정 도구 상세:
GET /rest/v1/mcp_tools?tool_id=eq.github::search_repositories&select=*
```

### `geo_score` JSONB 구조
```json
{
  "clarity": 0.95,
  "disambiguation": 0.0,
  "parameter_coverage": 0.0,
  "boundary": 0.0,
  "stats": 0.0,
  "precision": 0.0,
  "total": 0.158
}
```

---

## 5. RLS (Row-Level Security)

| 역할 | mcp_servers | mcp_tools | query_logs | execution_logs |
|------|------------|-----------|------------|---------------|
| `anon` | SELECT | SELECT | 불가 | 불가 |
| `authenticated` | SELECT | SELECT | 불가 | 불가 |
| `service_role` | ALL | ALL | ALL | ALL |

프론트엔드(anon key)로 서버/도구 읽기는 가능. 로그 테이블은 service_role만 접근.

---

## 6. 주의사항

1. **GEO score 평균이 0.11로 낮음** — 대부분 도구가 `clarity`만 높고 나머지 5개 dimension이 0. Dashboard 색상 임계값을 너무 높게 잡으면 전부 빨간색으로 보임. 0.3 이상이면 "양호"로 표시하는 게 적절.

2. **검색 페이지**: `search_tools_fts` RPC는 PostgreSQL tsvector 기반이라 **exact token match만** 됨. "send email"은 안 잡히고 "github"은 잡힘. 의미 검색은 Lambda API 배포 후 연결 필요.

3. **`tags` 컬럼은 대부분 NULL** — MCP-Zero 데이터에 태그가 없어서. 태그 필터 UI는 빈 상태 처리 필요.

4. **`url` 컬럼도 일부 NULL** — 모든 서버가 homepage URL을 제공하지 않음.

5. **frontend spec 참조**: `service/docs/lovable-spec.md` (985줄)에 페이지별 상세 스펙 있음. 단, MCP Discovery에서 실제 구현하면서 바뀐 부분이 있을 수 있으니 실제 프론트엔드가 SOT.

---

## 7. MCP Discovery 설정 체크리스트

- [ ] Supabase URL + anon key 설정
- [ ] 랜딩 페이지: `get_platform_stats()` 호출 확인
- [ ] /servers: `mcp_servers` + `server_tool_counts` view 연결
- [ ] /servers/:id: `mcp_tools?server_id=eq.{id}` 연결
- [ ] /tools/:id: `mcp_tools?tool_id=eq.{id}` 연결 + `geo_score` JSONB 파싱
- [ ] /dashboard: `provider_dashboard_snapshot` view 연결
- [ ] /search: `search_tools_fts` RPC 연결 (lexical only, 의미 검색은 후속)
- [ ] NULL 처리: tags, url, geo_score 각각 null-safe 렌더링
