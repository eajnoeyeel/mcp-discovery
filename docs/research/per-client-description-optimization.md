# Per-Client Description Optimization 리서치

> 최종 업데이트: 2026-04-12
> 
> 이 문서는 MCP Discovery Platform의 per-client description variants 레이어에 대한 리서치 기초를 제공합니다.
> 벤더별 LLM이 tool 선택 시 다르게 반응하는 description 스타일을 파악하고, 각 벤더에 맞춘 최적화 전략을 제안합니다.

---

## 1. 배경 및 목적

### 1.1 MCP Discovery Platform의 Description Architecture

> **개정 (2026-04-11 pivot 반영):** 기존 4-Field 구조에서 live reranker 레이어(`reranking_description`)를 제거하고, `FlatStrategy` 기반 embedding-only 파이프라인에 맞춰 3개 레이어로 축소. (근거: `docs/design/north-star-realignment.md`, `docs/adr/` 최신 수락 ADR)

현재 Tool Description은 다음 3개 레이어로 관리됩니다 (`src/mcp_discovery/models/core.py`, `src/mcp_discovery/description/`):

| 레이어 | 필드/위치 | 용도 | 최적화 대상 |
|--------|-----------|------|-----------|
| **raw description** | `MCPTool.description` | 원본 MCP 정의 (서버/레지스트리에서 수집) | 기록 및 재구성 용 |
| **selection description** | `MCPTool.selection_description` | Qdrant 인덱싱 + embedding search 입력 | Recall@K (text-embedding-3-large) |
| **per-client variants** | `PerClientVariant` (JSONL via `VariantStore`) | LLM-facing 최종 제시 (Gemini / Claude / GPT) | 각 LLM 벤더별 top-K 내 선택률 |

※ pre-pivot `reranking_description` 레이어는 **제거됨**. Cohere Rerank 3 등 live reranker는 현 파이프라인에 없으며, 실험(reranking/*) 코드에서만 참조 목적으로 유지됩니다.

이 문서는 **per-client variants** 레이어 설계의 이론적 근거를 제공합니다. 측정 지표는 Precision@1이 아니라 **"Recall@K 후보 내에서 특정 벤더 LLM이 정답 tool을 선택하는 비율"** — 우리가 top-K를 제공하고 LLM이 그 중 1개를 고르는 구조이기 때문입니다.

### 1.2 핵심 가설

**"벤더별 최적화된 description을 사용하면 해당 벤더 LLM이 top-K 후보에서 정답 tool을 더 높은 확률로 선택한다."**

이 가설을 검증하기 위해 최신 학술 연구(GEO 논문), 실무 가이드(Per-Model Prompting), 그리고 사례 연구(MCP tool description 최적화 사례)를 조사했습니다.

---

## 2. 핵심 발견: 벤더별 콘텐츠 선호 차이

### 2.1 GEO 논문 — 콘텐츠 소싱 편향

**출처:** Chen, M., Wang, X., Chen, K., & Koudas, N. (2025). "Generative Engine Optimization: How to Dominate AI Search." arXiv:2509.08919.

이 논문은 2025년 8월 기준 ChatGPT, Google Gemini, Claude, Perplexity 등 4개 주요 AI 엔진의 소스 인용 패턴을 분석했습니다. Brand, Earned, Social 3가지 콘텐츠 범주별로 각 엔진의 선호도를 측정했습니다.

#### 2.1.1 벤더별 소싱 편향

**Gemini**
- Brand(자체 도메인)과 Earned(외부 권위 도메인)의 균형적 활용
- 구조화된 자체 도메인 콘텐츠가 효과적
- 은행 관련 쿼리에서 가장 Brand 지향적 성향
- Claude, GPT, Perplexity의 중간적 포지션

**Claude**
- Earned 도메인(외부 권위 매체)을 가장 강하게 선호
- ChatGPT와 유사한 수준의 Earned 의존도
- 교차 언어 안정성이 Google보다 높음 — 동일한 권위 도메인을 여러 언어에서 일관되게 재사용
- 전체적으로 영어 콘텐츠 비중이 매우 높음
- **전략적 함의:** 글로벌하게 인정받는 권위 있는 도메인 내에서 핵심 위치 확보가 중요

**ChatGPT/GPT**
- Earned 도메인 강조, Social 소스는 거의 배제
- 기관 및 언론사의 Earned 도메인에 집중 (Bing 인덱스 기반)
- 거래(transactional) 관련 쿼리에서 Brand 콘텐츠를 가장 강하게 증폭
- 교차 언어 중복률 최저 — 효과적으로 다양한 사이트 생태계로 전환
- **전략적 함의:** 공식 API, 공식 문서 위상이 높음

**Perplexity**
- Brand와 Social 소스를 더 많이 통합, 더 다양한 정보 제공
- YouTube 등 비디오 콘텐츠, 주요 소매점 도메인 포함
- Brand, Earned, Social 세 범주 균형적 활용
- 실시간 RAG 기반으로 최신성 시그널 강함

#### 2.1.2 Cross-Engine Overlap

논문의 주요 발견: AI 모델별 고유 소스(exclusive sources)의 범위가 넓음. 즉, 각 엔진이 선호하는 소스가 겹치지 않는 부분이 상당하다는 뜻입니다(2025년 말 기준 약 11% 정도의 도메인만 겹침).

#### 2.1.3 문구 변경에 대한 민감도

GEO 논문과 후속 연구에서 발견된 중요 인사이트:
- AI 엔진은 Google 검색보다 문구 변경에 덜 민감함
- Earned media를 일관되게 선호하는 강한 신호가 있음
- 동일한 정보를 다른 문구로 제시해도 선호 도메인이 변하지 않음

#### 2.1.4 GEO 전략 권장사항 (논문)

논문에서 제시한 실무 권장사항:

1. **기계 판독성 및 정당성을 위한 콘텐츠 엔지니어링**
   - 구조화된 정보 제시 (key-value 쌍, 명확한 구분)
   - 알고리즘 신뢰성 강화

2. **Earned media 장악을 통한 AI 인지 권위 구축**
   - 외부 권위 매체에 인용/소개 확보
   - 벤더별로 중요성이 다름 (Claude > GPT >> Gemini)

3. **엔진별 및 언어 인식 전략 채택**
   - 각 엔진의 소싱 편향 이해
   - 언어별 전략 차별화 (Claude는 언어 간 일관성 높음)

4. **Schema.org 등 구조화된 데이터**
   - JSON-LD, microdata 등으로 명확한 메타데이터 제공
   - MCP tool description 컨텍스트에서는 JSON schema로 parameter/return 명시

5. **스캔 가능한 콘텐츠**
   - 비교 테이블, 장단점 목록, 명확한 가치 제안
   - 첫 150-300 단어에 핵심 정보 집중 (ChatGPT 특성)

#### 2.1.5 논문의 제한사항

- **데이터 스냅샷:** 2025년 8월 기준 (현시점에서 약 8개월 전)
- **소스 분류의 주관성:** Brand/Earned/Social 분류는 모델 기반이므로 100% 객관적이지 않음
- **내부 데이터 부재:** AI 벤더의 비공개 알고리즘에 대한 "왜"는 추론만 가능 — "무엇"은 설명 가능하나 메커니즘은 블랙박스

---

### 2.2 Per-Model Prompting — 포맷 선호

**출처:** ExplainLLM. "Per-Model Prompting: Claude vs GPT vs Gemini vs Llama — Optimize for Each LLM." https://explainllm.ru/en/applications/per-model-guides

이 가이드는 4개 주요 LLM (Claude, GPT, Gemini, Llama)의 프롬프트 포맷 선호도를 분석했습니다. 각 모델이 구조화된 입력에 다르게 반응하는 패턴을 정리했습니다.

#### 2.2.1 Claude의 포맷 선호: XML 구조

**특징:**
- XML 태그 구조(`<instructions>`, `<context>`, `<examples>`, `<output_format>`)에 최적화
- Extended thinking 지원으로 깊은 사고 가능
- 200K 토큰 컨텍스트
- 강한 시스템 프롬프트 준수성

**핵심 인사이트:**
> "Claude was specifically trained on XML-structured data, which is why wrapping your prompt sections in tags dramatically improves performance."

**시사점:** Claude에게 제시되는 tool description은 명확한 태그 구조를 가져야 함. 추상적 설명보다는 구체적인 capability를 구조화하여 제시할 때 선택률 증가 예상.

#### 2.2.2 GPT-4/GPT-5의 포맷 선호: 마크다운 헤더

**특징:**
- 마크다운 헤더(`## Role`, `## Instructions`, `## Parameters`)에 최적화
- JSON mode와 function/tool calling 강화
- 나중의 instruction이 더 높은 우선도
- 간결한 구조 선호

**핵심 인사이트:**
> "Using XML on GPT actually hurts readability for the model."

**시사점:** GPT에게는 XML이 아닌 마크다운을 사용해야 함. 첫 줄부터 핵심 정보 제시 (reading order 순서 중시).

#### 2.2.3 Gemini의 포맷 선호: 구조화된 템플릿

**특징:**
- 명확한 섹션 구분을 가진 구조화된 템플릿
- 멀티모달의 경우 이미지를 먼저 제시
- 1M+ 토큰 컨텍스트
- Search grounding (실시간 검색 결과 통합)

**핵심 인사이트:**
> "Structured prompt templates boost accuracy 40%"

**시사점:** Gemini는 일관된 템플릿 형식을 선호. 필드별 명확한 라벨과 일정한 순서 중요.

#### 2.2.4 크로스 모델 성능 차이

**결정적 발견:**
> "A prompt optimized for GPT-4 may underperform on Claude by 20-30% because Claude expects XML structure, not markdown headers. Always adapt to the model."

이는 단순 포맷 차이가 아닌 **근본적 성능 격차**를 야기함을 의미합니다.

**MCP Tool Description 적용:**
- 동일한 정보라도 구조/포맷이 다르면 각 벤더별 선택률에 차이 발생 예상
- 특히 경합 관계(confusion) 있는 도구들 간 선택에서 이 차이가 증폭될 수 있음

---

### 2.3 GEO 실무 가이드 — 벤더별 인용 행동 및 콘텐츠 소싱

**출처:** Pixis. (2026). "ChatGPT vs. Perplexity vs. Gemini: How Each AI Engine Cites Differently — And How to Optimize for Each." https://pixis.ai/blog/chatgpt-vs-perplexity-vs-gemini-how-each-ai-engine-cites-differently-and-how-to-optimize-for-each/

이 가이드는 실제 운영 맥락에서 각 엔진의 콘텐츠 선택 행동을 분석했습니다.

#### 2.3.1 ChatGPT의 특성

**데이터 소스:**
- Bing 인덱스 기반
- 87% 인용이 Bing top 10 organic results와 일치 (Seer Interactive, 2025)

**선택 메커니즘:**
- Domain authority ~40% (신뢰성)
- Content quality ~35% (품질)
- Platform trust ~25% (플랫폼 평판)

**콘텐츠 처리:**
- 첫 150-300 단어에서 답변 추출
- 최신성 시그널에 민감: 30일 내 업데이트 콘텐츠 3.2x 더 많은 인용 (SE Ranking, 2025)

**시사점:**
- 공식 도메인(official API docs)에서 추출한 설명이 강함
- 최근 업데이트된 설명이 유리
- 앞부분(첫 50-100 단어)에 핵심 정보 집중

#### 2.3.2 Perplexity의 특성

**특징:**
- 실시간 RAG 기반 검색
- Reddit 등 사용자 커뮤니티 콘텐츠 활용
- 최신성 우선

**시사점:**
- 실제 사용자 경험/리뷰 포함 시 가중치 상향
- 최신 정보 매우 중요

#### 2.3.3 Gemini의 특성

**특징:**
- 교차 플랫폼 엔티티 권위 기반 평가
- Brand와 Earned media 균형

**시사점:**
- 널리 인정받은 도메인의 일관된 메시지 중요
- 여러 플랫폼에서 반복되는 설명이 유리

#### 2.3.4 벤더 간 비중복성

**중요 발견:**
> 벤더 간 도메인 겹침은 약 11%에 불과 (The Digital Bloom, 2025, 680M+ citations 분석)

이는 각 벤더가 **거의 다른 소스 생태계**를 사용한다는 뜻입니다. 한 벤더에 최적화된 설명이 다른 벤더에는 도움이 안 될 수 있음을 시사합니다.

---

### 2.4 MCP Tool Description 최적화 선행 사례

#### 2.4.1 Neon (ZenML 케이스 스터디)

**출처:** ZenML. "Implementing Evaluation Framework for MCP Server Tool Selection." https://www.zenml.io/llmops-database/implementing-evaluation-framework-for-mcp-server-tool-selection

**결과:**
- Description 최적화만으로 tool selection 성공률 **60% → 100%**
- **코드 변경 없음** — description 수정만으로 달성
- 다른 infrastructure 변경 없음

**최적화 항목:**
1. 순차 워크플로우의 명시적 설명 (각 단계가 무엇인지)
2. 도구 간 관계 명확화 (언제 이 도구를 쓰는가)
3. 적절한 사용 사례 기술 (구체적인 시나리오)
4. 파라미터와 반환값의 의미 명확화

**함의:** Description 품질이 tool selection에 미치는 영향이 매우 큼.

#### 2.4.2 GitHub Copilot & Block (AWS Heroes)

**출처:** AWS Heroes. (2026). "MCP Tool Design: Why Your AI Agent Is Failing (And How to Fix It)." https://dev.to/aws-heroes/mcp-tool-design-why-your-ai-agent-is-failing-and-how-to-fix-it-40fc

**GitHub Copilot:**
- 도구 수 40개 → 13개로 축소
- Description 개선 + 도구 정렬
- 벤치마크 성능 향상

**Block:**
- 도구 수 30+ → 2개로 축소
- 3번에 걸친 재설계
- Description clarity 핵심

**공통 패턴:**
> "fewer tools, better descriptions, outcome-oriented design"

**최적화 원칙 (UX 원칙 적용):**

1. **Affordance (제공성)**
   - 도구의 이름과 설명이 그 기능을 즉시 전달해야 함
   - "search" vs "find_github_repositories" 명확성 차이

2. **Recognition over Recall (인식 > 회상)**
   - enum, 예시값, 선택지를 명시적으로 나열
   - LLM이 "이건 이 도구다"를 인식하도록

3. **Visibility of System Status (시스템 상태의 명확성)**
   - 명확한 에러 메시지
   - 도구의 한계 명시 (언제 쓰면 안 되나)

#### 2.4.3 Stacklok: MCP Tool Description Testing Framework

**출처:** Stacklok. "Introducing mcp-tef: Testing Your MCP Tool Descriptions Before They Cause Problems." https://dev.to/stacklok/introducing-mcp-tef-testing-your-mcp-tool-descriptions-before-they-cause-problems-fan

**Description 품질의 3축:**

1. **Clarity (명확성)**
   - 도구가 무엇을 하는가를 5글자 이내로 표현 가능해야 함
   - 기술 용어 없이 설명 가능해야 함

2. **Completeness (완전성)**
   - 파라미터의 타입, 필수/선택 명확
   - 반환값의 형식과 의미 명확
   - 사용 사례 최소 1-2개 제시

3. **Conciseness (간결성)**
   - 불필요한 수식어 제거
   - 150단어 이내로 핵심 전달

**일반적 실패 모드:**

1. **Vague language → LLM 혼란**
   - "retrieves data" vs "searches public GitHub repositories by keyword, language, license"

2. **Overlapping descriptions → Tool 선택 충돌**
   - `search_repos` vs `find_repositories` 의미 중복으로 선택 혼동

3. **Misleading confidence → 높은 확신으로 잘못된 선택**
   - "무조건 이 도구를 쓴다"고 LLM이 판단하게 만드는 과장된 설명

**벤더별 차이는 아직 체계적으로 문서화되지 않음** — 본 실험이 기여할 수 있는 영역.

---

## 3. Tool Description에의 적용: 벤더별 스타일 매핑

앞의 4개 섹션 (GEO 논문, Per-Model Prompting, GEO 실무 가이드, 선행 사례)의 발견을 결합하면, 다음과 같은 벤더별 description 스타일 매핑이 도출됩니다:

### 3.1 매핑 로직

**콘텐츠 톤 (GEO 소싱 편향) + 포맷 (Per-Model Prompting) = Description 스타일**

| 벤더 | GEO 콘텐츠 톤 | Per-Model 포맷 | 결과: Description 스타일 |
|------|-------------|--------------|----------------------|
| **Gemini** | Brand+Earned 균형, 구조화됨 | 구조화된 템플릿 (+40% 효과) | **스펙시트 포맷**: key-value 쌍으로 기능/파라미터/리턴값 명시. 카테고리 태그. 측정 가능한 속성. |
| **Claude** | Earned 강세, 권위적 | XML 태그 구조 | **권위적 서사 + 태그 구조**: "Standard interface for...", "widely adopted", 논리적 정당화. `<capability>`, `<parameters>` 등으로 구조화. |
| **GPT** | Earned + Brand (거래 강화), 간결 | 마크다운 헤더, 액션-퍼스트 | **액션-퍼스트 마크다운**: 첫 줄에 핵심 기능 요약. `## Parameters`, `## Returns` 등 헤더. 공식 기능 강조. |

### 3.2 벤더별 스타일 상세 설명

#### 3.2.1 Gemini 스타일: 스펙시트 포맷

**핵심 특징:**
- Key-value 쌍 중심 (JSON 스키마와 유사)
- 측정 가능한 속성 강조
- 카테고리/태그 명시
- 선택지 명확히 열거

**이유:**
- Gemini: "structured prompt templates boost accuracy 40%"
- GEO 논문: 구조화된 자체 도메인 콘텐츠 선호
- 1M+ 컨텍스트로 상세 정보 처리 가능

**장점:**
- 빠른 스캔성
- 명확한 계층 구조
- 선택지가 명시되어 헷갈림 적음

#### 3.2.2 Claude 스타일: 권위적 서사 + XML 구조

**핵심 특징:**
- 명시적 capability 나열 (bullets)
- 권위적 톤 ("standard interface", "widely adopted")
- XML 태그로 섹션 분리
- 논리적 정당화 포함

**이유:**
- Claude: "XML-structured data dramatically improves performance"
- GEO 논문: Earned media (권위있는 표현) 강세
- Extended thinking으로 복잡한 설명 처리 가능

**장점:**
- 상세한 논리 전개 가능
- 신뢰성 강조
- 도구의 중요성 부여

#### 3.2.3 GPT 스타일: 액션-퍼스트 마크다운

**핵심 특징:**
- 첫 줄: 핵심 기능 한 문장 요약
- `## Parameters` / `## Returns` 등 마크다운 헤더로 섹션 분리
- 공식 기능 강조 ("Official API for...")
- 간결한 표현

**이유:**
- GPT: "XML on GPT actually hurts readability"
- GEO 논문: 첫 150-300 단어에서 답 추출 (앞부분 집중)
- 거래 쿼리에서 Brand(공식) 콘텐츠 증폭

**장점:**
- 빠른 이해
- 스캔하기 좋은 구조
- 공식 문서처럼 신뢰성 높음

### 3.3 구체적 예시: github::search_repositories

원본 raw_description 가정:
```
Search GitHub repositories using keywords, filters like language and stars, 
and sort options. Returns matching repositories with metadata.
```

#### 3.3.1 Gemini-optimized (스펙시트)

```
Tool: search_repositories
Category: Code Discovery / Version Control / Repository Management
Function: Searches GitHub repositories by keyword, language, stars, license
Parameters: 
  - query (required, string): Search keywords
  - language (optional, string): Programming language filter
  - sort (optional, enum): [stars | forks | updated | help_wanted | recently_updated]
  - order (optional, enum): [asc | desc]
  - per_page (optional, int 1-100): Results per page

Returns: Array of {name, full_name, description, stargazers_count, language, html_url, topics}
Supported Filters: language, license, topic, archived status, fork status
Example Use Cases:
  - Find Python data science libraries with 1000+ stars
  - Search for JavaScript frameworks updated in last 30 days
  - Discover Rust projects licensed under MIT
```

**특징:**
- 명확한 key-value 구조
- enum을 [ ] 형식으로 명시
- 측정 가능한 기준 (1000+ stars, 30 days)
- 구체적인 use case 3개

#### 3.3.2 Claude-optimized (권위적 + XML)

```xml
<tool name="search_repositories">
<description>
The standard programmatic interface for querying GitHub's public repository 
index — widely adopted for code discovery, dependency auditing, and open-source 
landscape analysis. Enables structured filtering across 100M+ repositories.
</description>
<capabilities>
<capability>Full-text search across repository names, descriptions, and README files</capability>
<capability>Filter by programming language, license type, star count, and activity status</capability>
<capability>Configurable sort order enables ranking by relevance (stars), popularity (forks), or recency (updated date)</capability>
<capability>Supports discovery of trending projects, dependency analysis, and competitive intelligence</capability>
</capabilities>
<parameters>
<param name="query" required="true" type="string">Primary search keywords</param>
<param name="language" required="false" type="string">Filter by primary programming language</param>
<param name="sort" required="false" type="string">Ranking criterion: stars (default) | forks | updated</param>
<param name="order" required="false" type="string">Sort direction: asc | desc (default)</param>
</parameters>
<rationale>
GitHub search is the canonical method for open-source discovery. Preferred by 
developers and AI systems for reliability and comprehensive coverage.
</rationale>
</tool>
```

**특징:**
- 명확한 XML 구조 (`<tool>`, `<capabilities>`, `<parameters>`)
- 권위적 표현 ("standard", "widely adopted", "canonical")
- Capability를 bullet list로 명시
- 정당화 섹션 추가

#### 3.3.3 GPT-optimized (액션-퍼스트 마크다운)

```markdown
Search GitHub repositories by keyword, language, stars, license, and more. 
Returns ranked repository metadata for code discovery and analysis.

## Parameters
- **query** (required, string): Search keywords or phrase
- **language**: Filter by primary programming language
- **sort**: Ranking criterion — use "stars" (default) for popularity, 
  "forks" for impact, "updated" for recency
- **order**: asc or desc (default)
- **per_page**: 1–100 (default 30)

## Returns
Array of matching repositories with:
- name, full_name, URL
- stargazers_count, forks_count
- primary language
- topics/tags

## Common Uses
- Find Python libraries with 1000+ stars
- Search repositories updated in the last 30 days
- Discover MIT-licensed JavaScript projects
```

**특징:**
- 첫 줄에 핵심 요약
- `##` 마크다운 헤더로 섹션 분리
- 깔끔하고 간결한 포맷
- 구체적 사용 예시

### 3.4 선택 메커니즘 설계

4-field architecture에서 per_client_variants를 생성하는 프로세스:

```python
async def generate_per_client_variants(
    raw_description: str,
    tool_id: str,
    tool_metadata: dict  # parameters, return schema 등
) -> dict[str, str]:  # {"gemini": ..., "claude": ..., "gpt": ...}
    
    # 각 벤더별 프롬프트 템플릿으로 GPT-4o-mini 이용하여 생성
    variants = {
        "gemini": await generate_with_template(
            template=GEMINI_SPECSHEET_TEMPLATE,
            raw_description=raw_description,
            metadata=tool_metadata
        ),
        "claude": await generate_with_template(
            template=CLAUDE_XML_TEMPLATE,
            raw_description=raw_description,
            metadata=tool_metadata
        ),
        "gpt": await generate_with_template(
            template=GPT_MARKDOWN_TEMPLATE,
            raw_description=raw_description,
            metadata=tool_metadata
        ),
    }
    
    return variants
```

각 템플릿은 앞의 스타일 예시를 반영하여 설계됨.

---

## 4. 실험 설계

### 4.1 실험 개요

**목표:** Per-client description optimization이 실제로 각 벤더 LLM의 tool 선택률을 개선하는가?

**가설:**
- H0 (귀무): 벤더별 최적화 description과 원본 description의 선택률 차이 없음
- H1 (대립): 최소 1개 이상의 벤더에서 최적화 description 선택률이 유의미하게 높음 (p < 0.05)

### 4.2 실험 대상 선택

**Tool 선택 기준:**
- Ground truth에서 confusion 높은 tool 5-10개 선정
- "confusion 높다" = 비슷한 경쟁 tool이 많은 것 (경합 가능성 high)
- 예: `github::search_repositories` vs `github::list_repositories` vs `github::search_code`
- 이러한 도구들이 description 차이에 가장 민감할 것으로 예상

**쿼리 선택 기준:**
- 각 tool마다 실제 GT에서 정답인 쿼리 3-5개
- 총 15-50 쿼리 세트 구성
- 쿼리 길이, 도메인 다양성 확보

### 4.3 실험 설계 (A/B)

| 요소 | Control | Treatment |
|------|---------|-----------|
| Description | raw_description | 벤더별 최적화된 per_client_variant |
| LLM Vendor | Gemini, Claude, GPT | 각각 3회 반복 |
| Top-K 후보 | 동일 5개 (Stage 1, 2 거친 후) | 동일 5개 |
| Temperature | 낮음 (0.1-0.3) | 낮음 (0.1-0.3) for determinism |
| Repetitions | 3회 | 3회 (temperature variance 통제) |

### 4.4 측정 항목

**Primary Metric: Selection Rate**
```
= (target tool 선택 횟수) / (총 시도 횟수)
= X / (3 vendors × 3 reps × Q queries) = X / (9Q)
```

Control vs Treatment 비교:
```
Improvement = (Treatment_SelectRate - Control_SelectRate) / Control_SelectRate
Significance: t-test or binomial test (p < 0.05)
```

**Secondary Metrics:**
- Rank position of target tool in top-5 (평균 순위)
- LLM confidence score (if available)
- Latency (per vendor, to check cost difference)

### 4.5 시행 순서

1. **Confusion 높은 tool 5-10개 선정** (GT 분석)
2. **쿼리 세트 구성** (각 tool당 3-5개, ~25-50 쿼리)
3. **Control 실험 실행** (raw_description, 3 vendors × 3 reps)
4. **per_client_variants 생성** (GPT-4o-mini 이용)
5. **Treatment 실험 실행** (optimized description)
6. **통계 분석** (t-test, 95% CI)
7. **결과 보고** (개별 tool별, 벤더별 breakdown)

### 4.6 성공 기준

**실험 성공:**
- 최소 1개 벤더에서 최적화 description 선택률이 원본 대비 유의미하게 높음 (p < 0.05)
- 또는 여러 벤더에서 일관된 개선 추세 (p < 0.10, practical significance)

**파일럿 성공:**
- 모든 실험 코드 정상 작동
- 데이터 수집 완료
- 벤더별 응답 일관성 확인

### 4.7 비용 추정

**Tool description 생성:**
- GPT-4o-mini: ~10-15개 tool variant 생성
- 비용: ~$0.10-0.20

**LLM 평가:**
- 3 vendors × ~50 queries × 3 reps = 450 invocations
- Gemini (flash): Free tier 사용 가능 ($0)
- Claude (haiku): ~450 × $0.0008 = $0.36
- GPT-4o-mini: ~450 × $0.00015 = $0.07
- **총 비용: ~$0.50-1.00**

---

## 5. 참고 문헌

1. Chen, M., Wang, X., Chen, K., & Koudas, N. (2025). "Generative Engine Optimization: How to Dominate AI Search." *arXiv:2509.08919*.
   - https://arxiv.org/abs/2509.08919
   - 벤더별 콘텐츠 소싱 편향의 주요 출처

2. ExplainLLM. "Per-Model Prompting: Claude vs GPT vs Gemini vs Llama — Optimize for Each LLM."
   - https://explainllm.ru/en/applications/per-model-guides
   - 각 LLM의 포맷 선호도 분석

3. Pixis. (2026). "ChatGPT vs. Perplexity vs. Gemini: How Each AI Engine Cites Differently — And How to Optimize for Each."
   - https://pixis.ai/blog/chatgpt-vs-perplexity-vs-gemini-how-each-ai-engine-cites-differently-and-how-to-optimize-for-each/
   - 벤더별 실무 인용 행동 분석

4. ZenML. "Implementing Evaluation Framework for MCP Server Tool Selection (Neon Case Study)."
   - https://www.zenml.io/llmops-database/implementing-evaluation-framework-for-mcp-server-tool-selection
   - Description 최적화 실제 사례: 60% → 100% 성공률 개선

5. AWS Heroes. (2026). "MCP Tool Design: Why Your AI Agent Is Failing (And How to Fix It)."
   - https://dev.to/aws-heroes/mcp-tool-design-why-your-ai-agent-is-failing-and-how-to-fix-it-40fc
   - GitHub Copilot, Block 사례 / UX 원칙 (Affordance, Recognition, Visibility)

6. Stacklok. "Introducing mcp-tef: Testing Your MCP Tool Descriptions Before They Cause Problems."
   - https://dev.to/stacklok/introducing-mcp-tef-testing-your-mcp-tool-descriptions-before-they-cause-problems-fan
   - Description 품질 3축 (Clarity, Completeness, Conciseness) 및 일반적 실패 모드

### 5.1 부차 출처 (논문/가이드에서 인용된 연구)

7. Seer Interactive. (2025). "SearchGPT Citation Analysis: 500+ citations study."
   - Pixis 가이드에서 인용
   - ChatGPT의 Bing top 10 일치도 87% 발견

8. SE Ranking. (2025). "Content recency and AI citation frequency."
   - Pixis 가이드에서 인용
   - ChatGPT의 30일 내 업데이트 콘텐츠 3.2x 인용 증가

9. The Digital Bloom. (2025). "AI Citation Analysis: 680M+ citations across ChatGPT and Perplexity."
   - Pixis 가이드에서 인용
   - 벤더 간 도메인 overlap 약 11% 발견

10. ZipTie.dev. (2025). "ChatGPT Source Selection Algorithm Analysis."
    - Pixis 가이드에서 인용
    - Domain authority 40%, Content quality 35%, Platform trust 25%

---

## 6. 결론 및 다음 단계

### 6.1 핵심 결론

1. **벤더별 콘텐츠 선호는 확실함** (GEO 논문, 11% overlap)
   - 각 벤더가 거의 다른 소스 생태계를 사용
   - Description의 톤과 구조도 각 벤더에 맞춰야 함

2. **포맷 선택이 성능에 미치는 영향은 크다** (Per-Model Prompting, 20-30% 차이)
   - Claude의 XML vs GPT의 마크다운은 단순 취향 아님
   - 근본적으로 모델의 훈련 데이터와 아키텍처 차이에서 비롯됨

3. **Description 품질은 tool selection에 직결됨** (선행 사례, 60% → 100%)
   - 코드 변경 없이 설명만 개선해도 효과 큼
   - MCP 도구의 경우 더욱 중요 (코드는 고정, 설명만 변수)

4. **벤더별 최적화 description의 실제 효과는 미검증** (Gap in literature)
   - 이 실험이 기여할 수 있는 영역
   - 4-field architecture의 per_client_variants 정당성 제공 가능

### 6.2 다음 단계

1. **실험 1단계 (파일럿):** 5개 도구, ~25 쿼리로 프로토타입 실행
2. **결과 기반 스케일링:** 성공 시 전체 pool (50+) 도구로 확대
3. **매트릭 통합:** Recall@K 측정에 per_client variant 영향도 포함
4. **배포:** 성공 확인 후 실제 Bridge MCP Server에 적용

---

**문서 버전:** v1.0  
**마지막 수정:** 2026-04-12  
**담당자:** MCP Discovery Research Team
