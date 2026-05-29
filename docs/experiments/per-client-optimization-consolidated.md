# Per-Client Description Optimization — Consolidated Findings

**Date:** 2026-04-22
**Status:** Complete (4 experiments)
**Source experiments:** per-client-description-experiment-report.md, bias-max-gemini-report.md

---

## TL;DR

- **Information enrichment is the dominant driver**: enriched descriptions raised GPT hit rate from 83.3% → 94.7% (+11.4%p, p≈0, Cohen's h=0.38) across 2,550 trials; effect confirmed for Claude-sim as well.
- **Format interference is a tail risk, not a universal effect**: pilot (n=5) showed GPT-optimized markdown drops Claude from 100% → 20%; this did not reach significance in Phase 4 large-scale (17 clusters, Bonferroni-corrected), but motivates per-client routing as a hedge.
- **Gemini is description-invariant**: 15/17 clusters showed 0% across all 5 variants — Gemini selects by tool_id/brand name, not description content; per-client routing is excluded for Gemini.

---

## Cross-Vendor Asymmetry (Key Result)

| Vendor | Description sensitivity | Best format | Worst format | Key driver |
|--------|------------------------|-------------|--------------|------------|
| GPT | High | any (format-agnostic) | — | Info richness |
| Claude | High (info + format) | XML / prose | markdown | Info + format alignment |
| Gemini | None | — | — | tool_id / brand name |

---

## Act I: Information Wins — Universal Effect (Hero Result)

Large-scale validation: 17 clusters × 3 queries × 5 variants × 10 reps GPT / 3 reps Claude-sim (n=2,550 GPT, n=765 Claude-sim).

| Model | V_orig | V_prose | Delta | z | p | Cohen's h |
|-------|--------|---------|-------|---|---|-----------|
| GPT-4o-mini | 83.3% (425/510) | 94.7% (483/510) | **+11.4%p** | 5.81 | 0.0000 | 0.38 |
| Claude-sim | 85.6% (131/153) | 96.1% (147/153) | **+10.5%p** | 3.17 | 0.0015 | 0.38 |

Pilot confirmation (web_search cluster, n=5 per condition):

| Model | V_orig → V_enriched | Delta |
|-------|---------------------|-------|
| GPT-4o-mini | 0% → 100% | +100%p |
| Claude Sonnet | 60% → 100% | +40%p |

**Key insight**: enriched descriptions improve ALL vendors regardless of format. Specific gains came from adding query-relevant features (date filtering, news mode, publication timestamps) that matched the test query directly.

---

## Act II: Format Interference — Tail Risk

> **Evidence caveat**: This result is from a pilot study (n=5 per condition, single cluster). The large-scale Phase 4 test (n=2,550, 17 clusters) found strong information effects but format-specific interference did NOT reach significance under Bonferroni correction. This exhibit provides motivation for per-client routing as a tail-risk hedge, not a confirmed large-scale effect.

Format-Only experiment: same information across 4 formats, web_search cluster.

| Format | GPT-4o-mini | Claude Sonnet | Notes |
|--------|-------------|---------------|-------|
| V_prose (control) | 5/5 (100%) | 5/5 (100%) | baseline |
| V_md (GPT-markdown: `##` headers, `**bold**`) | 5/5 (100%) | **1/5 (20%)** | ← interference |
| V_xml (Claude-XML: `<capabilities>` tags) | 5/5 (100%) | 5/5 (100%) | |
| V_spec (Gemini-specsheet: key-value) | 5/5 (100%) | 5/5 (100%) | |

GPT: format-agnostic (100% on all formats). Claude: markdown causes 80%p drop.

Phase 4 H2/H3 results (Bonferroni-corrected, all non-significant):

| Comparison | Delta | p (Bonferroni) | Significant? |
|-----------|-------|---------------|-------------|
| GPT V_md vs V_prose | +1.4%p | 0.887 | No |
| GPT V_xml vs V_prose | +2.1%p | 0.260 | No |
| GPT V_spec vs V_prose | +1.2%p | 1.000 | No |
| Claude-sim V_md vs V_prose | +0.0%p | 1.000 | No |
| Claude-sim V_xml vs V_prose | +0.0%p | 1.000 | No |
| Claude-sim V_spec vs V_prose | +0.0%p | 1.000 | No |

---

## Act III: Gemini — Brand Bias Overrides Everything

> **Evidence caveat**: Provisional result — >20% of calls fell back to gemini-2.5-flash-lite due to rate limits. Results attributed to gemini-2.5-flash may be partially contaminated.

Phase 0 calibration: 17/19 clusters × 5 variants × 1 rep. Overall hit rate: **11.4%** (driven entirely by get_001 and get_002 which were already saturated at 80–100% with original descriptions).

| Category | Clusters | Hit rate (all variants) |
|----------|----------|------------------------|
| Floor (0% across all variants) | 15/17 | 0% |
| Already saturated | 2/17 (get_001, get_002) | 80–100% |

Brand bias example:
- `hologres::get_query_plan` (get_003): 0% across all 5 variants
- Clusters with prominent brand names (get_001: `contentful-mcp`, get_002: `productboard`): consistently selected

**Finding**: Gemini selects tools primarily based on `tool_id` string similarity and brand name recognition, not description content. No description enrichment strategy can overcome a semantically misaligned tool_id.

**Implication**: Gemini optimization requires tool_id/naming strategy — per-client description routing is excluded for Gemini.

---

## Bonus Finding: Enrichment Can Regress

V_spec on `get_001` (contentful-mcp::get_entry): V_orig=100% → V_spec=67%. Over-specified descriptions can introduce noise even in saturated clusters. This echoes the Phase 4 pilot finding that V2–V6 long descriptions underperformed the concise V1.

---

## Implications for Production

1. **Deploy now — universal enriched descriptions (Tier 1)**: no routing needed, all vendors benefit from information enrichment. Raises the floor from 83% to 94%+ for GPT.
2. **Shadow-mode — wire x-client-id to RAG layer (Tier 2)**: ~30 LOC change, gated on Phase 4 format interference replication with real Claude (not Claude-sim). Protects against the tail risk identified in the pilot.
3. **Gemini — excluded from per-client routing**: separate track for tool_id/naming conventions. No description routing until a viable signal is identified.

See: `docs/experiments/per-client-optimization-production-gap.md`

---

## Experiment Index

| Experiment | Date | n | Key finding |
|-----------|------|---|-------------|
| Pilot — web_search cluster (cross-vendor matrix) | 2026-04-14 | 5/condition | Information: GPT 0%→100%, Claude 60%→100% |
| Pilot — Format-Only (same info, 4 formats) | 2026-04-14 | 5/condition | V_md → Claude 20% (80%p drop); GPT format-agnostic |
| Phase 4 large-scale | 2026-04-14 | 2,550 GPT + 765 Claude-sim | +11.4%p info effect (p≈0); format ns under Bonferroni |
| Bias-Max Gemini Phase 0 calibration | 2026-04-21 | 17 clusters × 5 variants | 0% all variants on 15/17 clusters; brand bias confirmed; TERMINATED |
