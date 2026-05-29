본 논문은 ChatGPT, Perplexity, Gemini와 같은 생성형 인공지능(AI) 기반 검색 엔진의 빠른 도입이 정보 검색 방식을 근본적으로 재편하고 있음을 다룹니다. 이는 전통적인 순위 목록에서 인용 기반의 종합적인 답변으로의 전환을 의미하며, 기존의 SEO(Search Engine Optimization) 관행에 도전을 제기하고 GEO(Generative Engine Optimization)라는 새로운 패러다임의 필요성을 역설합니다.

**1. 연구 목표 및 배경**
이 연구의 주요 목표는 AI 검색과 전통적인 웹 검색(Google)을 포괄적으로 비교 분석하는 것입니다. 이는 정보 획득 및 브랜드 가시성에 대한 전략적 함의를 도출하기 위함입니다. 논문은 AI 검색이 Google의 균형 잡힌 정보 혼합과는 대조적으로 Earned media(제3자 권위 있는 출처)에 대한 체계적이고 압도적인 편향을 보인다는 핵심 발견을 제시합니다. 또한, AI 검색 서비스 간에도 도메인 다양성, 신선도, 교차 언어 안정성, 문구 민감도 등에서 상당한 차이가 있음을 보여줍니다. 이러한 경험적 결과를 바탕으로, 기계 판독성 및 정당성을 위한 콘텐츠 엔지니어링, Earned media 장악을 통한 AI 인지 권위 구축, 엔진별 및 언어 인식 전략 채택, 그리고 틈새 시장 플레이어를 위한 "빅 브랜드 편향" 극복 등 실질적인 GEO 전략을 제안합니다.

**2. 핵심 방법론 (Core Methodology)**
본 연구는 AI 엔진과 Google 검색을 동일한 검색 의도(intent)에 대해 비교하는 일반적인 파이프라인을 따릅니다. 각 실험은 특정 쿼리(vertical, language, paraphrase)와 비교 대상 엔진, 계산된 레이블(domain type, website language)에 따라 달라집니다.

## **쿼리 생성 및 변환 (Query Generation and Transformation):**
 - "Top 10... brands"와 같은 랭킹 스타일 프롬프트(ranking-style prompts)를 표준화하여 직접적인 비교 및 점수화가 가능하도록 합니다.
 - 범주별 쿼리 세트를 생성하거나, GPT-4o API를 사용하여 제어된 변형(controlled variants)을 프로그래밍 방식으로 생성합니다 (예: 추가 제약 조건, 번역). 일관성을 위해 템플릿화된 지침(templated instructions)이 사용됩니다.

## **AI 엔진 실행 및 Google 데이터 수집 (AI Engine Execution and Google Collection):**
 - **AI 엔진:** Perplexity (sonar-pro), Claude (claude-3.5-sonnet-latest with web_search_20250305 tool), Gemini (gemini-2.5-flash with Google Search grounding), GPT (gpt-4o-search-preview)와 같은 웹 지원 AI 엔진에 각 프롬프트를 발행합니다. 답변 텍스트와 모든 인용 링크(citation links)를 수집합니다.
 - **Google:** Programmable Search (Custom Search) API를 통해 각 쿼리에 대한 상위 10개 웹 결과(top-10 web results)의 URL을 검색합니다.

## **데이터 추출 (Data Extraction):**
 - 수집된 모든 URL에서 등록 가능한 도메인(registrable domain, 예: `https://www.bankrate.com/...` → `bankrate.com`)을 추출합니다.
 - AI 엔진의 원본 답변 텍스트는 GPT-4o에 전송되어 답변에 언급된 브랜드/제품의 순위 목록을 추출합니다. 순서가 있는 경우 유지하고, 문자열을 최소한으로 정규화(case-folding, punctuation trimming)합니다.

## **정규화 및 분류 (Normalization and Classification):**
 - 각 쿼리 x API 결과에 대해 도메인과 브랜드를 중복 제거(de-duplicate)하여 동일한 사이트나 항목이 한 답변 내에서 여러 번 인용되는 것을 방지합니다.
 - 각 추출된 도메인은 GPT-4o-search-preview를 통해 세 가지 범주로 분류됩니다:
     - **Brand:** 제품이나 서비스를 직접 제공하는 공식 브랜드 사이트 (예: `chase.com`).
     - **Social:** 소셜 플랫폼, 커뮤니티 포럼, 사용자 생성 콘텐츠 (예: `reddit.com`, `youtube.com`).
     - **Earned:** 독립 미디어, 리뷰, 비교 사이트 (예: `nerdwallet.com`, `forbes.com`).
 - 언어 실험에서는 GPT-4o-search-preview가 각 도메인을 사이트의 주요 콘텐츠 언어에 따라 영어 또는 대상 언어(이진 선택)로 레이블링합니다.

## **중복 측정 및 집계 (Overlap Metrics and Aggregation):**
 - **Top-k domain overlap (fixed-length):** 두 시스템이 동일한 상위 k개 고유 도메인 세트에서 평가될 때, `Coverage@k`를 사용하여 두 세트에 공통된 도메인의 비율을 계산합니다 (겹치는 개수 / k).
 - **Domain overlap (variable-length sets):** 인용 횟수가 다르기 때문에 자카드 지수(Jaccard index)를 사용합니다. $J(A, B) = \frac{|A \cap B|}{|A \cup B|}$
 - **Group aggregation:** 여러 쿼리로 구성된 그룹(예: 10개 프롬프트 산업 분야)의 경우, 해당 엔진 및 조건에 대한 분야별 점수를 얻기 위해 멤버 쿼리 전체의 평균 중복을 계산합니다.

## **분포 집계 (Aggregation for Distributions):**
 - 소스 유형 분석을 위한 실험의 경우, 필요한 세분성(예: model x language)에서 모든 (중복 제거된) 인용을 모아서 공유 분포(예: brand / social / earned; English / non-English)를 계산합니다.

**3. 주요 연구 결과**

## **AI 검색과 Google 검색 비교 분석:**
 - **지역 및 분야별 실험:** AI 검색은 Google과는 달리 Earned media에 일관되게 편향되어 있습니다. Google은 Brand, Social, Earned 콘텐츠의 균형 잡힌 분포를 유지합니다. 특히 AI 검색에서는 Social 미디어 소스가 거의 나타나지 않는 구조적 변화가 확인됩니다.
 - **지역 검색 실험:** 지역 비즈니스 쿼리에서 AI 검색과 Google 간의 도메인 중복률이 낮습니다. 이는 AI 엔진이 전통적인 Google Local SEO와 다른 전략을 요구함을 시사합니다.
 - **언어 민감도 실험:**
     - **크로스-랭귀지 도메인 안정성:** Claude는 Google보다 훨씬 높은 교차 언어 안정성을 보이며, 동일한 권위 도메인을 여러 언어에서 재사용하는 경향이 있습니다. GPT는 가장 낮은 중복률을 보여 효과적으로 다른 사이트 생태계로 전환합니다. Perplexity와 Gemini는 Google과 비슷하거나 약간 높은 중복률을 보입니다.
     - **소스 유형 혼합:** AI 시스템은 언어에 관계없이 Earned media에 더 많이 편향되어 있습니다. Google은 Brand, Earned, Social의 균형을 유지합니다.
     - **웹사이트 언어:** 비영어 프롬프트에서는 인용이 대상 언어로 기울지만, Google의 경우 그 정도가 덜합니다. GPT와 Perplexity는 현지 언어 비중이 높고, Claude는 영어 비중이 훨씬 높습니다.
 - **문구 변경 민감도 실험:** 문구 변경은 언어 변경보다 검색 결과에 미치는 영향이 작습니다. AI 엔진은 Google보다 문구 변경에 덜 민감하며, Earned media를 일관되게 선호합니다. Google은 간단한 형식 변경(예: 명령형 목록, 키워드 전용)에서 결과가 가장 안정적입니다.

## **일반 쿼리 유형 분석:**
 - **정보성 쿼리 (Informational Queries):** Google은 Brand, Earned, Social을 균형 있게 다루고, GPT는 Earned를 강조하며 Social을 거의 배제하고, Perplexity는 Brand 도메인을 가장 강하게 강조합니다.
 - **고려 쿼리 (Consideration Queries):** 모든 시스템에서 Earned 콘텐츠가 지배적이지만, Google은 Social과 Earned를 짝짓고, GPT는 거의 Earned에만 집중하며, Perplexity는 세 범주에서 균형을 유지합니다.
 - **거래 쿼리 (Transactional Queries):** 모든 시스템에서 Brand 콘텐츠의 중요성이 높아집니다. GPT는 Brand 콘텐츠를 가장 강하게 증폭시키고 Earned가 그 뒤를 잇습니다.

## **AI 검색 엔진 간 비교 분석:**
 - **유명 브랜드 vs. 틈새 브랜드:** 모든 AI 시스템은 Earned 도메인에 일관되게 편향되어 있지만, Claude와 ChatGPT는 유명 브랜드와 틈새 브랜드 모두에서 Earned 도메인을 가장 강하게 선호합니다. Perplexity는 Social 콘텐츠를 더 많이 포함하며, Gemini는 그 중간 지점에 있습니다. 틈새 브랜드의 경우, AI 시스템 간의 결과 일치도가 낮아집니다.
 - **수직 도메인 및 신선도 분석:** Claude와 ChatGPT는 소비자 가전 및 자동차 분야에서 Earned media에 크게 의존하지만, 자동차 분야에서는 신선도(recency)가 떨어지는 경향을 보입니다. Perplexity는 Brand와 Social 소스를 더 많이 통합하여 더 다양한 정보를 제공하지만, 상업적인 링크가 많습니다.
 - **자동차 브랜드 분석 (Electric, Family SUVs, Hybrid):** Google은 Reddit과 같은 Social 소스를 일관되게 포함하여 커뮤니티 기반의 결과를 제공합니다. ChatGPT는 Social 플랫폼을 거의 배제하고 기관 및 언론사의 Earned 도메인에 집중합니다. Perplexity는 두 접근 방식을 혼합하여 Social, Brand, Earned 콘텐츠를 포함합니다.
 - **교차 모델 도메인 다양성:** 각 AI 모델은 고유한 소스(exclusive sources)의 넓은 범위를 유지합니다. Claude와 Perplexity 간의 도메인 중복이 GPT와 Perplexity 간보다 일관되게 강합니다. 소수의 "핵심" 고권위 사이트만 모든 모델에서 공통적으로 나타납니다.
 - **지역 서비스에서의 교차 모델 도메인 다양성:** 지역 서비스 쿼리에서 AI 엔진 간의 도메인 생태계는 매우 파편화되어 있습니다. Claude와 GPT는 더 좁고 보수적인 소스 세트에 의존하는 반면, Gemini와 Perplexity는 더 넓은 범위의 도메인을 탐색합니다.
 - **빅 브랜드 편향 (탄산음료 분야):** 브랜드가 없는 쿼리에서 ChatGPT와 Perplexity 모두 주요 탄산음료 브랜드(예: Coca-Cola, Pepsi)에 대한 체계적인 편향을 보입니다. 이는 모델의 출력과 인용된 도메인 프로파일에서 명확히 나타납니다.
 - **은행 쿼리 (페르소나별):** 모든 AI 모델은 은행 랭킹 쿼리에서 Earned 소스(편집 리뷰 및 금융 설명)에 크게 의존하지만, Brand 소스의 통합 정도에서 차이를 보입니다. Gemini가 Brand 지향적이고, Perplexity가 균형을 이루며, Claude/ChatGPT가 Earned 지향적입니다. Social 소스의 기여는 미미합니다.

**4. GEO 의제 및 전략적 함의**

본 연구의 결과는 전통적인 SEO 기술만으로는 AI 검색 환경에서 충분하지 않으며, GEO라는 새로운 전략이 필요함을 명확히 합니다.

## **에이전시 및 스캔 가능성을 위한 엔지니어링 (Engineer for Agency and Scannability):** AI 시스템은 데이터를 구문 분석하고 해석하여 답변을 생성하므로, 웹사이트 콘텐츠는 기계 판독 가능한 구조화된 데이터로 설계되어야 합니다. Schema.org와 같은 상세한 스키마 마크업을 제품, 사양, 가격, 리뷰 등에 엄격하게 구현하여 AI가 쉽게 정보에 "비즈니스"를 할 수 있도록 만들어야 합니다.
## **모든 엔진에서 Earned Media 장악 (Dominate Earned Media Across All Engines):** AI 엔진의 압도적인 Earned media 편향성을 고려할 때, 브랜드는 자사 소유 콘텐츠 생성에서 Earned media를 체계적으로 획득하는 데 초점을 맞춰야 합니다. 이는 PR, 미디어 아웃리치, 전문가 협력을 통해 권위 있는 출판물 및 리뷰 사이트에 노출되고 언급되는 것을 의미합니다. 이러한 고권위 도메인으로부터 백링크(backlink)를 구축하는 것은 AI의 E-E-A-T(Experience, Expertise, Authoritativeness, Trustworthiness) 인지에 직접적인 영향을 미치므로 핵심 GEO 전략입니다.
## **브랜드 가시성을 위한 엔진별 전술 (Engine-Specific Tactics for Brand Visibility):**
 - **Claude 및 ChatGPT:** 글로벌하게 인정받는 권위 있는 도메인 내에서 핵심적인 위치를 확보하는 것이 중요합니다.
 - **Perplexity:** YouTube와 같은 비디오 콘텐츠를 생성하고 주요 소매점 도메인에 제품 정보가 정확하게 나열되도록 하는 등 더 다양한 소스를 활용합니다.
 - **Gemini:** Earned media와 함께 잘 구조화된 자체 도메인 콘텐츠를 활용하는 균형 잡힌 접근 방식이 효과적입니다.
## **다국어 전략: 콘텐츠뿐 아니라 권위의 현지화 (Multilingual Strategy: Localize Authority, Not Just Content):**
 - **GPT 및 Perplexity:** 대상 언어 생태계에서 권위 있는 현지 언어 퍼블리셔 및 리뷰 사이트와의 관계를 구축하고 커버리지를 확보해야 합니다.
 - **Claude:** 최상위 영어 Earned media에서의 브랜드 입지를 강화하는 것이 여러 언어에서 가시성을 높이는 데 도움이 됩니다.
## **콘텐츠 전략: 쇼트리스트를 위한 정당화 및 비교 (Content Strategy: Justify and Compare for the Shortlist):** AI 검색은 간결하고 정당화된 쇼트리스트에 포함되는 것을 목표로 합니다. 웹사이트 콘텐츠는 명확하고 모호하지 않은 정당성을 제공하도록 설계되어야 합니다. 경쟁사와의 상세한 비교 테이블, 장단점 목록, 명확한 가치 제안(예: "가장 긴 배터리 수명")과 같은 스캔 가능한 콘텐츠를 만들어 AI가 브랜드의 우수성을 쉽게 추출할 수 있도록 해야 합니다.
## **틈새 브랜드 전략: 빅 브랜드 편향 극복 (Niche Brand Strategy: Overcome the Big Brand Bias):** 틈새 브랜드는 특정 틈새 시장을 깊이 있는 전문 콘텐츠와 전문 출판물을 통한 Earned media 캠페인으로 장악하여 검증 가능한 권위를 구축해야 합니다. Perplexity와 같은 엔진에서 효과적인 전략(예: 고품질 YouTube 리뷰 콘텐츠)을 활용하여 초석 권위를 구축하는 것도 중요합니다.

**5. 결론**

이 연구는 AI 검색 환경의 복잡성과 경쟁력을 보여주며, 기존의 일회성 SEO 전술이 시대에 뒤떨어졌음을 시사합니다. 지속 가능한 우위를 점하기 위해서는 원칙적이고 규율적이며 지속적인 GEO 방법론이 필수적입니다. 이는 단순히 일회성 프로젝트가 아니라, 최고의 정보, 가장 영향력 있는 콘텐츠, 가장 강력한 권위, 그리고 가장 빠른 대응 시간을 가진 자만이 승리하는 끊임없는 "군비 경쟁"에서 성공하기 위한 필수적인 관리 서비스로 간주되어야 합니다.

**6. 연구의 한계**

본 연구의 한계점은 다음과 같습니다:
## **시간적 특성:** 데이터는 2025년 8월에 수집되었으며, AI 서비스의 행동, 알고리즘, 사용자 인터페이스는 동적으로 변화하므로, 결과는 특정 시점의 스냅샷일 뿐 영구적인 진실이 아닙니다.
## **소스 분류 시스템:** 소스 분류(Brand, Earned, Social)는 주관적인 모델이며, 다른 분류 체계는 다른 정량적 결과를 초래할 수 있습니다. 결과의 절대적인 수치보다는 엔진 간의 비교적 강한 추세에 중점을 두어야 합니다.
## **내부 데이터 접근 부족:** 내부 쿼리 로그, 사용자 데이터, 랭킹 모델 등에 대한 접근 없이 외부에서 분석되었으므로, "무엇이 발생하는지"는 정확히 설명할 수 있지만 "왜 발생하는지"는 추론에 불과합니다.

이러한 한계에도 불구하고, 본 연구는 AI 검색 엔진에 대한 귀중하고 엄격한 비교 분석을 제공하며, 진화하는 검색 환경에서 현재의 전략을 지속적으로 검증하고 조정해야 함을 강조합니다.