# ADR-0010: 서버 설명 텍스트 출처 — MCP instructions vs Smithery description

**Date**: 2026-03-27
**Status**: superseded for live retrieval by 2026-04-11 FlatStrategy pivot. Historical experiment context only.
**Deciders**: E0 실험 설계 검토 과정에서 도출
**ADR-0011 영향**: Tool Pool이 MCP-Zero(308 servers)로 전환됨. 그러나 본 ADR의 핵심 concern — "서버 설명 텍스트 품질이 E0 결과를 오염시키는 confound" — 은 미해결. MCP-Zero의 `server_description`/`server_summary`가 Smithery 마케팅 카피와 동일 수준이면 confound 여전히 존재. MCP-Zero 서버 설명 품질 확인 후 enriched description arm 필요 여부 결정.

## Context

E0 실험은 "2-Layer(서버→도구) 구조가 1-Layer(도구만) 대비 검색 정확도를 개선하는가"를 측정한다. 2-Layer 조건에서는 서버 레벨 임베딩이 필요하고, 이 임베딩의 입력 텍스트가 실험 결과를 직접 좌우한다.

> 2026-04-11 update: live retrieval no longer uses the server-level 2-Layer path. Current live authority is `docs/design/north-star-realignment.md`.

현재 서버 설명으로 사용하는 텍스트는 **Smithery 레지스트리의 `description` 필드**다. 이것은 서버 제작자가 Smithery 등록 시 작성한 마케팅 문구로, LLM이 실제로 보는 텍스트가 아니다.

MCP 프로토콜의 `initialize` 응답에는 **`instructions` 필드**(optional, string)가 있다. MCP 스펙 정의:

> "Instructions describing how to use the server and its features. This can be used by clients to improve the LLM's understanding of available tools, resources, etc. It can be thought of like a 'hint' to the model."

이 두 텍스트는 목적이 다르다:
- **Smithery description**: 사람이 레지스트리를 브라우징할 때 보는 마케팅 카피
- **MCP instructions**: LLM이 서버의 도구를 언제/어떻게 사용할지 판단하는 기술 가이드

E0에서 2-Layer가 지면 "서버 레벨 정보가 무용하다"가 아니라 "Smithery 마케팅 문구 기반 서버 필터링이 무용하다"만 말할 수 있다. baseline의 독립변인이 오염된 상태다.

## PoC 결과 — instructions 필드 수집 가능성

### 접근법 1: npx/uvx로 로컬 실행 → stdio initialize (작동 확인)

```
echo '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' | npx -y <package> 2>/dev/null
```

| 서버 | 결과 |
|------|------|
| `@modelcontextprotocol/server-everything` | **instructions 있음** (652자, 상세한 사용 가이드) |
| `math-mcp` | instructions 없음 |
| `rss-reader-mcp` | instructions 없음 |
| `aira-semanticscholar` | instructions 없음 |
| `mcp-server-fetch` (uvx) | instructions 없음 |

**결론**: 기술적으로 작동하지만, npm에 게시된 서버만 가능하고 auth가 필요한 서버는 불가.

### 접근법 2: GitHub 소스코드에서 직접 추출

31개 고유 GitHub 서버의 entry point 파일을 검색한 결과:

| 분류 | 수량 | 비율 |
|------|------|------|
| instructions 설정함 | **3** | 10% |
| instructions 미설정 | 14 | 45% |
| 소스 접근 불가 (비공개/다른 구조) | 14 | 45% |

instructions를 설정한 서버:
- **upstash/context7-mcp**: `"Use this server to retrieve up-to-date documentation and code examples for any library."`
- **LinkupPlatform/linkup-mcp-server**: `"Use this server when you need to search the web for information"`
- **linxule/lotus-wisdom-mcp**: false positive (데이터 필드, MCP instructions 아님)

**결론**: 대부분의 MCP 서버가 instructions 필드를 설정하지 않는다. MCP 스펙에서 optional이므로.

### 접근법 3: Smithery 호스팅 엔드포인트 직접 호출

```
POST https://<server>.run.tools/mcp → "Missing Authorization header"
POST https://server.smithery.ai/<server>/mcp → "Missing Authorization header"
```

**결론**: Smithery API 키 없이는 호스팅 서버에 접근 불가. 무료 키 프로그램 확인 필요.

### 접근법 4: GitHub README/repo 메타데이터

| 출처 | 접근성 | 품질 |
|------|--------|------|
| GitHub repo description | 36/50 서버 (API) | 1줄, 간결하지만 정확 |
| GitHub topics | 36/50 서버 (API) | 카테고리 태그 (e.g., `crm`, `mcp-server`) |
| GitHub README Features 섹션 | 36/50 서버 (raw) | 구체적 기능 나열, 파싱 필요 |

예시 비교 (Clay MCP):
- Smithery: "Access your network seamlessly with a simple and efficient server..."
- GitHub desc: "A simple Model Context Protocol (MCP) server for Clay."
- GitHub topics: `crm`, `crm-connections`, `mcp`, `mcp-server`
- README Features: "Contact Search, Interaction Search, Contact Statistics, Detailed Contact Info, Add New Contact"

**결론**: Smithery description보다 풍부하고 정확한 정보를 무료로 수집 가능.

### 접근법 5: Composio 호스팅 서버 (14/50)

Instagram, Slack, Gmail 등 Composio 호스팅 서버는 잘 알려진 서비스이므로 description 품질이 비교적 양호. 별도 API 탐색 미완.

### 접근법 6: 외부 MCP 레지스트리 크로스 참조

Smithery 외에도 MCP 서버를 등록·소개하는 레지스트리가 다수 존재한다:

| 레지스트리 | URL 패턴 | 특징 |
| --- | --- | --- |
| MCP Market | `mcpmarket.com/server/{name}` | 한국어/영어, 서버별 상세 소개 페이지 |
| Glama | `glama.ai/mcp/servers/{name}` | 서버 설명 + 도구 목록 + 사용 예시 |
| PulseMCP | `pulsemcp.com/servers/{name}` | 카테고리 분류 + 요약 |
| mcp.so | `mcp.so/server/{name}` | 커뮤니티 기반, 사용자 리뷰 포함 |

각 레지스트리는 동일 서버에 대해 서로 다른 마케팅 문구를 작성하므로, 교차 참조 시 Smithery 단일 출처보다 풍부한 설명을 합성할 수 있다. 다만 스크래핑 정책 확인 필요.

**결론**: GitHub 메타데이터와 상호 보완적. 특히 GitHub repo가 없는 Composio 호스팅 서버(14개)의 설명 보강에 유효.

## Decision

**E0 실험의 서버 설명 텍스트를 다층화(tiered)하고, confound를 문서화한다.**

1. **E0에서 3-arm 비교로 확장**:
   - Arm 1: 1-Layer (tool only) — 기존과 동일
   - Arm 2: 2-Layer (Smithery description) — 기존과 동일
   - Arm 3: 2-Layer (enriched description) — GitHub 메타데이터로 보강

2. **enriched description 구성 방법**:
   ```
   {server_name}: {github_repo_description}
   Topics: {github_topics}
   Tools: {tool_name_1}, {tool_name_2}, ...
   ```
   GitHub 접근 불가 시 Smithery description + tool name aggregation으로 fallback.

3. **E0 결론에 텍스트 출처 명시**: "Smithery registry description 기반" vs "enriched description 기반" 구분하여 리포트.

4. **MCP instructions 필드**: 현재 대부분 서버(~90%)가 미설정이므로 실용적 가치 낮음. 채택률이 올라가면 재평가.

## Alternatives Considered

### Alternative 1: MCP instructions 필드만 사용

- **Pros**: 프로토콜 표준 필드, LLM이 실제로 보는 텍스트
- **Cons**: 50개 풀 중 2~3개만 설정됨 (~6%). 나머지는 null → fallback 필요
- **Why not**: 커버리지가 너무 낮아 독립적 실험 조건으로 성립 불가

### Alternative 2: Smithery API 키 확보 후 호스팅 서버에서 일괄 수집

- **Pros**: 실제 런타임 instructions 필드 수집 가능
- **Cons**: API 키 취득 불확실, 대부분 서버가 instructions 미설정이면 수고 대비 효과 낮음
- **Why not**: instructions 미설정 비율이 높다는 것이 이미 소스코드 분석으로 확인됨

### Alternative 3: E0를 현행대로 유지하고 결론에 caveat만 추가

- **Pros**: 가장 빠르게 진행 가능
- **Cons**: confound가 해소되지 않아 후속 실험 기반이 약해짐
- **Why not**: baseline의 신뢰성이 프로젝트 전체 실험 체계의 근거. 시간 투자 대비 효과가 높음

## Consequences

### Positive
- E0의 독립변인(계층 구조)과 혼란변인(설명 품질)이 분리됨
- enriched description은 GitHub API로 자동 수집 가능 (추가 비용: 임베딩 1회)
- E4(Description Quality 실험)의 예비 데이터 확보

### Negative
- E0 arm이 2→3으로 증가하여 리포트 복잡도 상승
- enriched description 생성 스크립트 추가 구현 필요

### Risks
- GitHub API rate limit (미인증 시 60 req/hr) → 50개 서버면 충분하지만, 반복 실행 시 주의
- enriched description도 완전한 해결이 아님 (MCP instructions와 여전히 다른 텍스트) → ADR에 한계 명시

## TODO

> **E0 실행 결과 (2026-03-31)**: E0은 Arm 1 (Flat 1-Layer), Arm 2 (Sequential/Parallel with Smithery description)만 실행됨.
> Arm 3 (2-Layer enriched description) 미구현/미실행.
> 아래 TODO는 Post-E1 작업으로 deferred됨.

- [ ] GitHub API로 36개 서버의 repo description, topics 수집하는 스크립트 작성
- [ ] 외부 레지스트리(MCP Market, Glama, PulseMCP, mcp.so) 크로스 참조 수집 검토 (스크래핑 정책 확인 후 적용)
- [ ] enriched description 생성 로직 구현 (GitHub 메타 + tool name aggregation, fallback 포함)
- [ ] enriched description 기반 서버 임베딩 생성 → Qdrant에 별도 collection 또는 별도 payload로 인덱싱
- [ ] E0 스크립트에 Arm 3 (2-Layer enriched) 조건 추가
- [ ] E0 실행 후 Arm 2 vs Arm 3 비교 → enriched description이 2-Layer 성능을 실제로 개선하는지 검증
- [ ] 결과에 따라 E1 이후 실험의 기본 서버 설명 텍스트 결정 (Smithery vs enriched)
