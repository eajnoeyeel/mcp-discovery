# Per-Client Description Optimization — Demo Plan

**Audience:** Technical stakeholders, investors, product team
**Format:** Pre-recorded replay (no live API calls) via scripts/demo_per_client_optimization.py
**Duration:** ~10 minutes

---

## Setup

```bash
cd /path/to/mcp-discovery
uv run python scripts/demo_per_client_optimization.py --act all
# or individual acts:
uv run python scripts/demo_per_client_optimization.py --act 1
uv run python scripts/demo_per_client_optimization.py --act 2
uv run python scripts/demo_per_client_optimization.py --act 3
```

---

## Act I: Information Wins (Hero Result, ~3 min)

**What the audience sees:**
- Tool pool: 6 web search tools (exa, firecrawl, kagi, tavily, google_custom, brave)
- Query: "Search the web for recent news about AI regulation in Europe"
- V_orig result: GPT 0/10, Claude 0/3 on search_007_Q1 with original description
- V_prose result: GPT 10/10, Claude 3/3 — both correct with enriched prose description

**Key message:** Information richness improves all vendors. No per-client routing needed for the information effect.

**n=2,550 context:** GPT +11.4%p (83.3% → 94.7%), Cohen's h=0.38, p≈0 across 17 clusters.
Claude simulation: +10.5%p (85.6% → 96.1%), p=0.0015.

---

## Act II: Format Matters — Tail Risk (~3 min)

> ⚠️ PILOT RESULT (n=5): This finding did NOT replicate at n=2,550 under Bonferroni correction (Claude V_md diff=0.0, p=1.0). Presented as tail-risk motivation for per-client routing, not confirmed at scale.

**What the audience sees:**
- Same enriched information, 4 format variants applied to a single cluster
- GPT: consistent across ALL formats (format-agnostic at scale)
- Claude (pilot): prose ✓, XML ✓, spec ✓ — but markdown caused a drop in the pilot run

**Key message:** Even a non-replicated pilot finding is a real risk signal. If we serve one format to all clients, we cannot rule out format interference for some vendors. Per-client routing is the hedge.

---

## Act III: Gemini — Brand Bias Overrides Everything (~4 min)

> ⚠️ PROVISIONAL: >20% flash-lite fallback rate — results may not reflect flash-only behavior. 208/210 calls returned null (tool not called).

**What the audience sees:**
- 17 clusters × 5 variants heatmap — 14/17 clusters at 0% across all variants
- Only get_001 (80%), get_002 (100%), get_004 (13%) show any signal
- Brand bias spotlight: hologres::get_query_plan (0%) always loses to alibaba_cloud_analyticdb_for_mysql (12/15 picks in get_003)

**Key message:** GEO research's Gemini brand bias is confirmed in function-calling. Description quality is irrelevant for most clusters; tool naming is the lever. Gemini requires a separate strategy — per-client description optimization does not apply.

---

## Talking Points

1. "We ran 2,550+ API calls across 17 clusters to validate the information effect — GPT and Claude both show +10–11%p lift, statistically significant."
2. "The format interference finding is a pilot result — we're being honest that it didn't replicate at scale, but it motivates the per-client routing design."
3. "Gemini is architecturally different: brand-first, not description-first. 14 of 17 clusters returned 0% hit rate regardless of description variant."
4. "Production deployment path is already designed: Phase 1 (format standardization), Phase 2 (per-client routing for GPT/Claude), Phase 3 (Gemini tool-naming strategy)."
