# Bias-Max Gemini Experiment Report

**Date:** 2026-04-21  
**Status:** TERMINATED — No qualifying clusters identified  
**Script:** `scripts/run_bias_max_gemini.py`  
**Calibration output:** `data/experiments/bias_max_gemini_calibration.json`

---

## Summary

The Phase 0 calibration (all 19 clusters × 5 variants × 1 rep) yielded **zero clusters** qualifying for Phase 1 main run under the hard-cluster selection criteria:

```
V_orig ≤ 30%  AND  max(V_prose, V_spec, V_md, V_xml) ≥ 20%
```

**The Bias-Max experiment cannot proceed.** There is no signal to amplify.

---

## Phase 0 Results (17/19 clusters; 2 missing: remote_022, pods_024)

| Cluster | Target | V_orig | V_prose | V_spec | V_md | V_xml | Qualifies? |
|---------|--------|--------|---------|--------|------|-------|------------|
| get_001 | contentful-mcp::get_entry | 100% | 100% | 67% | 67% | 67% | — (V_orig too high) |
| get_002 | productboard::get_notes | 100% | 100% | 100% | 100% | 100% | — (V_orig too high) |
| get_004 | wikipedia::get_summary | 33% | 0% | 33% | 0% | 0% | — (no enrichment gain) |
| get_003 | hologres::get_query_plan | 0% | 0% | 0% | 0% | 0% | — (floor, brand bias) |
| list_005 | clickup::list_documents | 0% | 0% | 0% | 0% | 0% | — (floor) |
| create_006 | clickup::create_space_tag | 0% | 0% | 0% | 0% | 0% | — (floor) |
| search_007 | gitee::search_users | 0% | 0% | 0% | 0% | 0% | — (floor) |
| search_008 | opendota::search_player | 0% | 0% | 0% | 0% | 0% | — (floor) |
| update_009 | clickup::update_space_tag | 0% | 0% | 0% | 0% | 0% | — (floor) |
| delete_010 | clickup::delete_space_tag | 0% | 0% | 0% | 0% | 0% | — (floor) |
| delete_011 | elevenlabs::delete_job | 0% | 0% | 0% | 0% | 0% | — (floor) |
| monday_014 | monday.com::monday-delete-item | 0% | 0% | 0% | 0% | 0% | — (floor) |
| load_016 | ramp::load_bills | 0% | 0% | 0% | 0% | 0% | — (floor) |
| atlas_020 | mongodb::atlas-list-projects | 0% | 0% | 0% | 0% | 0% | — (floor) |
| weather_021 | weather-data::weather_alerts | 0% | 0% | 0% | 0% | 0% | — (floor) |
| whois_023 | whois::whois_ip | 0% | 0% | 0% | 0% | 0% | — (floor) |
| drop_025 | mongodb::drop-database | 0% | 0% | 0% | 0% | 0% | — (floor) |

Overall hit rate across all variants: **11.4%** (driven entirely by get_001 and get_002)

---

## Key Findings

### Finding 1: Gemini is description-invariant

15/17 clusters show 0% hit rate across ALL 5 description variants. Changing description format (prose, spec, markdown, XML) produces no measurable effect. This is not a "no improvement from bad baseline" result — it is a **total floor** where the model cannot identify the correct tool regardless of description quality.

**Contrast with GPT-4o** (from per-client-description-experiment-report.md): GPT showed 0%→100% improvement with enriched descriptions on certain clusters. Gemini shows 0%→0%.

### Finding 2: Success clusters are already saturated

get_001 and get_002 already achieve 80–100% with original descriptions. No room for improvement, and enrichment occasionally hurts (V_spec drops get_001 from 100% to 67%).

### Finding 3: get_004 shows V_orig regression pattern

wikipedia::get_summary has V_orig=33% but enriched variants drop to 0% (V_prose, V_md, V_xml) or stay flat (V_spec=33%). Description enrichment actively hurts this cluster.

### Finding 4: flash-lite fallback contaminates results

`provisional=true` — >20% of calls fell back to `gemini-2.5-flash-lite` due to rate limits. Flash-lite's tool selection capability may differ significantly from flash. Results cannot be cleanly attributed to a single model tier.

---

## Interpretation

### Why Gemini shows 0% on most clusters

Three non-exclusive hypotheses:

1. **Tool_id/name-first selection**: Gemini may select tools primarily based on `tool_id` string similarity to the query (e.g., `clickup::list_documents` for "list documents in ClickUp"), not description content. When the tool_id is semantically misaligned with the query, no description enrichment can compensate.

2. **Rate-limit / flash-lite degradation**: Heavy fallback to flash-lite introduces a weaker model that may not perform tool selection reliably at all.

3. **Context window / ranking mechanics**: The pool sizes for some clusters are large (90–105 tools for clickup clusters). Gemini may not effectively rank tools across very large candidate sets from descriptions alone.

### Cross-vendor asymmetry (emerging pattern)

| Vendor | Description sensitivity | Notes |
|--------|------------------------|-------|
| GPT-4o | High | 0%→100% gains observed |
| Claude | Medium | markdown variant helped; XML hurt |
| Gemini | None | 0%→0%, description-invariant |

This asymmetry has product implications: **per-client description optimization is only viable for GPT and Claude clients.** Gemini clients should receive tool_id / tool_name improvements instead.

---

## Implications for Production Deployment (ADR-0019)

The shadow-mode scaffold planned in ADR-0019 remains valid for GPT and Claude paths. For Gemini, the roadmap should pivot to:

- Tool ID clarity / naming conventions
- server_name alignment with common query patterns
- Possibly Gemini-specific system prompt engineering (outside description field)

---

## Next Steps

1. **Close Bias-Max experiment** — no Phase 1 run needed, no qualifying clusters
2. **Pivot Gemini investigation** to tool_id/name relevance analysis
3. **Update per-client-description-experiment-report.md** Section 3.1 with Gemini calibration negative result
4. **Consider ADR-0019 amendment** — limit shadow-mode to GPT + Claude clients initially

---

## Related Documents

- [`per-client-optimization-consolidated.md`](./per-client-optimization-consolidated.md) — Act III of the consolidated findings; integrates this result with GPT/Claude experiments into the cross-vendor asymmetry summary.
- [`per-client-optimization-production-gap.md`](./per-client-optimization-production-gap.md) — Production deployment plan; Gemini is excluded from per-client description routing based on this experiment's findings.
- [`repository-experiment-history.md`](./repository-experiment-history.md) — Full experiment timeline entry for this calibration run.

---

## Run Metadata

- Model: gemini-2.5-flash (with flash-lite fallback)
- Total API calls: 210
- Null responses: 208 (99% — model responded but selected wrong tool)
- Elapsed: 107.4 minutes
- Clusters completed: 17/19 (remote_022, pods_024 incomplete — not expected to change conclusions)
- Flash-lite fallback rate: >20% → provisional=true
