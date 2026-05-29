# GEO for MCP Descriptions — 종합 리서치

> 조사 목적: MCP tool description에 적용 가능한 Generative Engine Optimization 기법 파악
> 해결하려는 기능/문제: E4 실험 설계, GEO Score v2 개선 방향
> 작성일: 2026-04-06

---

## 조사 목적

MCP tool description(1-3문장, 10-30 단어)에 GEO 기법을 적용할 때:
1. 어떤 전략이 dense retrieval(임베딩 검색)에 효과적인가?
2. 어떤 전략이 오히려 해로운가?
3. 기존 GEO 연구가 짧은 기술 설명에 직접 적용 가능한가?

## 검토한 논문/자료 목록

| 논문 | 파일 | 핵심 기여 |
|------|------|----------|
| GEO (Aggarwal et al., KDD 2024) | `../papers/geo-analysis-ko.md` (미생성, 아래 요약) | 9가지 전략, Position-Adjusted Word Count |
| Content is Goliath (Ma et al., 2025) | 아래 요약 | LLM이 낮은 perplexity 콘텐츠 선호 |
| CORE (Jin et al., 2026) | 아래 요약 | 91.4% Top-5 프로모션 성공률 |
| **SAGEO Arena** (Kim et al., 2026) | 아래 요약 | **GEO가 retrieval을 -9%~-36% 악화시킴** |
| E-GEO (Bagga et al., 2025) | 아래 요약 | 이커머스 GEO, 범용 패턴 수렴 |
| Dominate AI Search (Chen et al., 2025) | 아래 요약 | 엔진별 인용 패턴, Earned media 편향 |

## 각 자료에서 가져온 핵심 포인트

### GEO 원 논문 (arxiv:2311.09735)
- 9가지 전략 중 상위 3: Quotation Addition(+41%, 본문 확인 필요 -- abstract은 'up to 40%'만 언급), Statistics Addition(+40%), Cite Sources(+30%)
- **Keyword Stuffing은 무효** — 전통 SEO 기법이 GEO에서는 작동 안 함
- 하위 랭크 콘텐츠에 더 큰 효과 (Rank 5 + Cite Sources = +115%)
- **한계**: 웹페이지(수백~수천 단어) 대상, dense retrieval 미검증

### Content is Goliath (arxiv:2509.14436)
- LLM은 **낮은 perplexity**(= LLM이 예측하기 쉬운) 콘텐츠를 선호
- Perplexity 1 SD 감소 → 인용 확률 47%→56% (full paper 확인 필요 -- abstract에서 수치 미확인)
- LLM으로 polish한 콘텐츠: 인용 +1~2건/쿼리
- **시사점**: description을 LLM으로 다듬으면 LLM 기반 reranker에서 유리할 수 있음

### SAGEO Arena (arxiv:2602.12187) — **가장 중요한 발견**
- **Body text GEO 최적화가 retrieval을 -9%~-36% 악화시킴**
- AutoGEO 적용 시 retrieval **-36%** 하락 (최악)
- **구조적 메타데이터 최적화만 retrieval +22% 개선**
- 기술 용어 삽입이 lexical retrieval에서 query-term 불일치 유발
- **시사점**: MCP description의 "본문"을 GEO 최적화하면 Stage 1 검색이 악화될 수 있음. 구조적 정보(tool_name, input_schema)가 더 중요

### CORE (arxiv:2602.03608)
- Review-based 전략: Top-5 프로모션 성공 (논문 보고: 91.4% Top-5, 86.6% Top-3, 80.3% Top-1. 88-96% 범위는 전략별 변동치이며, strategy-level variation에서 기인)
- 모델 간 전이 가능
- **시사점**: LLM 합성 단계 타겟이며 retrieval 단계는 별개. Reranker에는 관련 가능

### E-GEO (arxiv:2511.20867)
- 15가지 rewriting 휴리스틱 비교
- **범용 패턴 수렴**: 사용자 의도 정렬 + 기능 차별점 명시 + 사실성 유지
- **시사점**: 짧은 제품 설명 대상이라 MCP description과 길이가 비교적 유사

### Dominate AI Search (arxiv:2509.08919)
- GPT: Earned media 81.9% 편향 (abstract에서 수치 미확인, full paper 확인 필요), Claude: 높은 도메인 재사용률 (abstract에서 Claude 미언급, full paper 확인 필요)
- 엔진별 인용 패턴이 크게 다름
- **시사점**: Phase 2에서 LLM 벤더별 description 최적화 가능성 (현재는 후순위)

## 후보 접근 방식 비교

| 접근 | Dense Retrieval 효과 | Reranker 효과 | 근거 | 적용 가능성 |
|------|---------------------|--------------|------|------------|
| **A. 본문 GEO 최적화** (기존 방식) | **악화** (-9%~-36%, SAGEO) | 불확실 | SAGEO Arena | 낮음 |
| **B. 구조적 메타데이터 보강** | **개선** (+22%, SAGEO) | N/A | SAGEO Arena | 높음 |
| **C. LLM polish (perplexity 감소)** | 미검증 | 유리 가능 | Content is Goliath | 중간 |
| **D. 기능적 명확성 + when-to-use** | **개선** (+10pp NDCG, Tool-DE) | 유리 | Tool-DE, CallNavi | **높음** |
| **E. doc2query 확장** | **개선** (+47.8% MRR) | N/A | doc2query | 중간 |

## 채택안

**D. 기능적 명확성 중심 + 구조적 보강** — Tool-DE와 SAGEO의 교차 검증이 가장 강함

- 핵심 기능을 명확히 서술 (clarity)
- when-to-use, tags, limitations 필드 추가 (Tool-DE 방식)
- **example_usage는 제외** (Tool-DE ablation에서 성능 저하 확인)
- 과도한 문체 변환 금지 (SAGEO 경고)

## 제외안

- **A. 본문 GEO 최적화**: SAGEO에서 retrieval 악화 확인, Slave 실험에서도 P@1 -0.069 확인
- **E. doc2query**: 효과적이지만 description 자체가 아닌 쿼리 확장 기법이라 E4 scope와 다름

## 연구 갭 (미답 영역)

1. **Dense retrieval에서의 GEO 효과**: SAGEO가 BM25만 테스트, dense embedding은 미검증
2. **짧은 텍스트(1-3문장) GEO**: 모든 GEO 논문이 긴 콘텐츠 대상
3. **2-stage pipeline trade-off**: Stage 1에 좋은 최적화가 Stage 2에 해로울 수 있음 (미검증)

## 관련 papers

- `../papers/tool-de-analysis-ko.md`
- `../papers/trace-free-plus-analysis-ko.md`
- `../papers/dynamic-react-analysis-ko.md`
- `../papers/mcp-descriptions-smelly-analysis-ko.md`
- `../papers/callnavi-analysis-ko.md`
- `../papers/tooltweak-analysis-ko.md`
