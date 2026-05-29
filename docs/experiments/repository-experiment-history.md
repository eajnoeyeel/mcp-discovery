# Repository Experiment History

이 문서는 이 레포에서 실제로 진행된 실험들을 한 페이지에서 볼 수 있도록 재구성한 기록이다.
정리 기준은 현재 남아 있는 `docs/experiments/`, 관련 `scripts/`, 그리고 `git log --all`에 남은
커밋/삭제 이력이다.

> Portfolio note: Cohere mentions in this file are historical experiment context
> only. The current public runtime keeps reranking optional and does not require
> Cohere or `COHERE_API_KEY`.

## 판정 기준

- **Completed**: 결과 수치가 남은 보고서, 실행 스크립트, 또는 커밋 로그가 존재함
- **Cancelled**: 설계/스크립트까지 있었지만 실행 전에 삭제되었고, 삭제 이유가 커밋 메시지에 남아 있음
- **Planned only**: 설계/플랜 흔적은 있으나 결과 아티팩트나 실행 로그를 찾지 못함

## Completed Timeline

| Date | Experiment | Purpose / hypothesis | Process | Result / decision | Evidence |
| --- | --- | --- | --- | --- | --- |
| 2026-03-30 to 2026-03-31 | **E0 architecture validation** | 2-Layer retrieval이 1-Layer보다 실제로 더 좋은지 검증. Gate 조건은 `Sequential_P@1 - Flat_P@1 >= +5%p`. | `scripts/run_e0.py`로 MCP-Zero 292-server pool, covered GT 194개, `text-embedding-3-large` 기준 비교. 3/30에는 flat baseline(P@1 30.9%)을 기록했고, 3/31 reranker 재실행에서는 Flat / Sequential / Parallel을 모두 비교했다. | Gate 실패. Sequential은 Flat보다 낮았고(P@1 32.5% vs about 36%), Layer 1 hard gate 문제가 확인됐다. Parallel만 37.6%로 소폭 우세. 결과적으로 "엄격한 2-Layer가 더 낫다"는 가설은 기각됐다. | `docs/adr/0002-2-layer-recommendation-architecture.md`, `scripts/run_e0.py`, deleted `.claude/evals/E0-baseline.log`, commits `b17af15`, `e213082`, `bab1239` |
| 2026-04-06 | **E4 description enrichment A/B** | "Description 품질이 production pipeline의 tool selection을 높인다"를 dense retrieval + reranker 전체 경로에서 재현 가능한지 검증. | 원본 collection vs Tool-DE enriched collection 비교. 94개 GT-covered tools, GT 2,273개, `ParallelStrategy + Cohere rerank-v3.5`, Wilcoxon signed-rank + bootstrap CI 사용. | P@1은 +0.97pp였지만 유의미하지 않음(`p=0.833`). 대신 Confusion은 -5.02pp, Recall은 -2.92pp. 결론은 enrichment 자체보다 "같은 description을 Stage 1/2에 같이 쓰면 충돌한다"는 구조적 병목 발견이었다. | [`E4-report.md`](./E4-report.md), `scripts/run_e4.py`, commit `bd5624c` |
| 2026-04-07 | **E4v2 selection controllability** | E4의 retrieval confound를 제거하고, description 변경만으로 reranker selection을 바꿀 수 있는지 인과적으로 검증. | Offline fixed-candidate evaluation. 3 clusters, 611 queries, target tool만 enriched description으로 교체, Cohere reranker만 사용, McNemar test 적용. | "Description이 selection을 바꿀 수 있다"는 점은 증명됐다. 다만 효과는 baseline-dependent였다. `git_log`는 100% → 66.7%로 유의미하게 악화(`p=0.008`), `search_records`는 77.3% → 82.5%로 개선. 평균 SP는 +7.39pp. | [`E4v2-report.md`](./E4v2-report.md), [`E4v2-design.md`](./E4v2-design.md), `scripts/run_e4v2_selection.py`, commit `37ed9a3` |
| 2026-04-07 | **E4v2b pattern comparison** | "어떤 description design pattern이 어떤 baseline에서 유효한가?"를 규칙 수준으로 도출. | E4v2와 같은 3 clusters / 611 queries에 7 variants(V0-V6: control, Tool-DE, differentiation, use-case, I/O, boundary, overclaiming)를 투입. Cochran's Q + pairwise McNemar 사용. | Baseline-pattern interaction이 강하게 확인됐다. High-baseline(`git_vcs`)에서는 원본 V0가 최적, mid-baseline(`db_records`)에서는 V4(I/O explicit)가 최고(+9.28pp). Overclaiming은 거의 항상 해로웠다. 이후 Provider guidance rule의 근거가 됐다. | [`E4v2b-report.md`](./E4v2b-report.md), [`E4v2b-design.md`](./E4v2b-design.md), `scripts/run_e4v2b_patterns.py`, commit `2fa1845` |
| 2026-04-11 | **Recall@K baseline after reranker removal** | reranker를 제거한 뒤 embedding-only retrieval의 새 North Star baseline을 확정. | `scripts/run_recall_k_baseline.py`로 Flat vs Parallel 비교. 320 servers, GT 2,273개, K=3/5/10, reranker 없음. | FlatStrategy가 기준선이 됐다. `Recall@3 = 21.5%`, `P@1 = 13.4%`. Parallel은 모든 K에서 Flat보다 낮았다. 이 시점부터 핵심 지표가 pre-pivot P@1 중심 사고에서 Recall@K 중심으로 이동했다. | [`recall-k-baseline-report.md`](./recall-k-baseline-report.md), `scripts/run_recall_k_baseline.py`, commits `326640d`, `d71d607` |
| 2026-04-12 | **Hybrid search baseline** | embedding-only baseline(`Recall@3 = 21.5%`)을 dense+sparse fusion으로 회복/상향할 수 있는지 검증. | Dense(OpenAI) + Sparse(SPLADE) + Qdrant RRF. 320 servers, 2,898 tools, GT 2,273개. Sparse 입력은 93개 LLM enrichment + 2,805개 rule-based enrichment를 사용. | `Recall@3`가 **21.5% → 48.9% (+27.4pp)** 로 크게 상승했다. `P@1 = 31.2%`, latency 증가는 약 +30ms. 이 결과로 retrieval North Star baseline이 48.9%로 재설정됐다. | [`hybrid-search-report.md`](./hybrid-search-report.md), `scripts/run_hybrid_baseline.py`, `scripts/build_hybrid_index.py`, commits `da3795e`, `a3e95ea` |
| 2026-04-12 | **Full LLM enrichment follow-up (hybrid sub-experiment)** | sparse side를 전부 LLM-generated text로 통일하면 hybrid 성능이 더 좋아지는지 검증. | Hybrid report의 section 6. Baseline(93 LLM + 2805 rule) vs Pure LLM(2898) vs Keyword+LLM prefix의 3조건 비교. | Pure LLM은 template homogenization 때문에 오히려 `Recall@3`를 떨어뜨렸다(46.6%). `Keyword+LLM`은 `P@1 = 31.9%`, `Confusion = 21.6%`로 가장 제품 친화적인 균형을 보여 최종 채택됐다. | [`hybrid-search-report.md`](./hybrid-search-report.md), commit `689b462` |
| 2026-04-14 | **Per-client description optimization (pilot + rigorous phase)** | H1 정보 효과, H2 포맷 특이성, H3 cross-vendor interference를 검증. 핵심 가설은 "higher description quality → higher tool selection rate", 그리고 그 효과가 vendor별로 다를 수 있다는 것. | 1) web_search 6-tool cluster에서 small pilot 수행, 2) 동일 정보/다른 포맷 실험으로 Claude markdown interference를 확인, 3) 17 clusters × 3 queries × 5 variants로 대규모 Phase 4 실행(GPT 2,550회 + Claude-sim 765회), 4) Phase 5 통계 분석으로 보고서 업데이트. | H1은 강하게 확인됐다. GPT `83.3% → 94.7%`, Claude-sim `85.6% → 96.1%`. H2는 약했다. 포맷보다 정보량이 더 중요했다. H3는 pilot에서 분명했다. GPT-style markdown은 Claude에서 `100% → 20%`로 급락. Gemini는 rate limit로 미완. | [`per-client-description-experiment-report.md`](./per-client-description-experiment-report.md), [`description-optimization-experiment-design.md`](./description-optimization-experiment-design.md), `scripts/run_phase4_gpt.py`, `scripts/run_phase4_claude.py`, `scripts/run_phase4_gemini.py`, `scripts/run_phase5_statistics.py`, `scripts/run_selection_experiment.py`, commits `4d09077`, `d4d001e`, `4062989` |
| 2026-04-21 | **Bias-Max Gemini calibration (Phase 0, TERMINATED)** | Gemini에서 description 변경으로 hit rate를 높일 수 있는 "hard cluster"를 식별. 기준: `V_orig ≤ 30%` AND `max(enriched variants) ≥ 20%`. | 19 clusters × 5 variants × 1 rep (Phase 0 calibration). `scripts/run_bias_max_gemini.py`, gemini-2.5-flash (>20% flash-lite fallback). | qualifying cluster 0개 — Phase 1 main run 진행 불가. 15/17 완료 clusters에서 all-variant hit rate 0%. get_001/get_002는 이미 포화(80–100%). Gemini는 description이 아닌 tool_id/brand name 기반으로 선택. per-client description routing 대상에서 Gemini 제외 결정. | [`bias-max-gemini-report.md`](./bias-max-gemini-report.md), `data/experiments/bias_max_gemini_calibration.json`, `scripts/run_bias_max_gemini.py`, `scripts/analyze_bias_max_gemini.py` |

## Cancelled Or Removed

| Date | Experiment | Status | What existed | Why it stopped | Evidence |
| --- | --- | --- | --- | --- | --- |
| 2026-04-07 | **E4v3 production-near dual-description validation** | Cancelled before run | `E4v2b`의 best variant를 실제 `selection_description` field와 reranker 코드 경로로 재현하려는 설계 문서와 스크립트가 있었다. | 삭제 커밋에서 "추가 Cohere API 실험 없이 unit/integration test로 production-path 검증이 충분하다"고 명시했다. 즉, 과학 실험이라기보다 engineering validation으로 재분류되어 폐기됐다. | deleted `docs/experiments/E4v3-design.md`, deleted `scripts/run_e4v3_dual_desc.py`, commit `e8877e1` |
| 2026-03-28 to 2026-04-01 | **Early description-optimizer experiment harness** | Removed / non-authoritative | `run_grounded_ab_comparison.py`, `run_retrieval_ab_eval.py`, `run_selection_eval.py`, `run_comparison_verification.py` 등 초기 실험성 스크립트와 `description_optimizer/` 모듈이 한 차례 들어왔다. | 2026-04-01 revert에서 전체 lane이 제거됐다. 현재 남아 있는 보고서/결과 문서가 없어서, 실행 여부나 결과를 신뢰 가능한 completed experiment로 세기 어렵다. | revert commit `233e48b`, prior merge `59d03d1`, deleted scripts/modules listed in revert |

## Planned Only Or Not Evidenced

| Experiment family | What is present | What is missing | Current reading |
| --- | --- | --- | --- |
| **E1 to E3** | 연구/설계 문서와 eval spec 흔적 | 결과 보고서, 결과 JSON, 실행 로그, 결과를 적은 커밋 | 계획은 있었지만 완료 증거는 찾지 못했다. |
| **E5 pool scaling** | `scripts/run_e0.py --sweep`, `data/results/e5_scale_sweep.json` 경로, 설계/플랜 문서 | `docs/experiments` 보고서, 결과 파일, 수치가 남은 커밋 | 구현/스캐폴딩은 있었지만 이 레포 히스토리에서 실행 결과는 확인되지 않았다. |
| **E6 pool similarity** | 계획 문서, 연구 문헌 연결, GT/pool design note | 결과 보고서, 결과 파일, 실행 로그 | planned only. |
| **E7 GEO / smell mapping** | ADR/연구/plan 문서, scoring discussion | 결과 보고서, 상관계수 결과, 실행 로그 | planned only. |

## Throughline

- **3월 말 E0**: "2-Layer가 1-Layer보다 낫다"는 초기 아키텍처 가설은 성립하지 않았다. 이후 검색 전략 판단이 경험 기반으로 바뀌었다.
- **4월 6일 to 4월 7일 E4 series**: 설명 품질 실험은 full-pipeline A/B에서 출발했지만, 곧 reranker-only 인과 검증(E4v2)과 pattern rule discovery(E4v2b)로 쪼개졌다.
- **4월 11일 to 4월 12일 retrieval pivot**: reranker를 제거하고 Recall@K로 기준선을 다시 잡은 뒤, hybrid search가 대폭 개선을 만들었다.
- **4월 14일 per-client lane**: retrieval-facing description 최적화와 별개로, LLM-facing vendor-specific description 최적화라는 두 번째 실험 축이 생겼다.

## Practical Summary

- **실제로 결과가 남은 핵심 실험 축**은 `E0`, `E4`, `E4v2`, `E4v2b`, `Recall@K baseline`, `Hybrid baseline`, `Hybrid full-LLM follow-up`, `Per-client description optimization`, `Bias-Max Gemini calibration (TERMINATED)`이다.

### Per-Client Optimization 관련 문서 (2026-04-22 추가)

| Document | Purpose |
|----------|---------|
| [`per-client-optimization-consolidated.md`](./per-client-optimization-consolidated.md) | 4개 실험(pilot, format-only, Phase 4 large-scale, Bias-Max Gemini) 통합 요약 및 cross-vendor asymmetry 정리 |
| [`per-client-optimization-production-gap.md`](./per-client-optimization-production-gap.md) | 실험 결과와 production 배포 사이의 gap 분석 및 단계별 배포 계획 |
| [`per-client-optimization-demo-plan.md`](./per-client-optimization-demo-plan.md) | 데모 시나리오 및 스크립트 |
- **삭제됐지만 흔적이 분명한 실험**은 `E4v3`와 초기 `description-optimizer` lane이다.
- **E1-E3, E5-E7은 이 레포 기준으로는 "기획/스캐폴딩은 있었지만 완료된 실험"으로 보기 어렵다.**
