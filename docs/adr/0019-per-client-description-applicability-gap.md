# ADR 0019: Per-Client Description Optimization — Production Applicability Gap

**Date:** 2026-04-21
**Status:** Amended 2026-04-22 — Gemini excluded, Phase 1 TERMINATED, Claude routing downgraded to shadow-mode-only
**Deciders:** MCP Discovery Team

---

## Context

The per-client description experiment (bias-max series) tests whether tailoring `selection_description` text to the calling client's vendor style improves tool selection recall. Early results suggest a V_spec (verbose-specific) variant may outperform the baseline V_gen (verbose-generic) description for certain LLM clients.

The question before this ADR is: given those results, can the per-client description path be promoted to production? The answer is: **not yet**. Several production-readiness gaps remain between the experiment scaffold and a live, multi-tenant deployment.

---

## What Is Already Built

The following components exist and are verified in the codebase:

| Component | Location | Notes |
|-----------|----------|-------|
| `MCPTool.selection_description` field | `src/mcp_discovery/models/core.py:72` | Stores the per-tool description variant used at retrieval time |
| `VendorStyle` enum | `src/mcp_discovery/description/base.py:8` | Enumerates known client styles (e.g., `V_spec`, `V_gen`) |
| `_apply_selection_descriptions()` function | `service/rag/service.py:19,218` | Post-retrieval step that overwrites `SearchResult` descriptions before returning |
| `x-client-id` header extraction | `service/lambdas/search/handler.py:88` | Reads `x-client-id` / `X-Client-Id` from Lambda event headers |

---

## What Is Missing for Production

The following five components are absent and required before the per-client path can serve live traffic:

1. **Client-to-style routing table** (~30 LOC)
   A mapping from `client_id` values to `VendorStyle`. Currently hardcoded for experiment use; needs a config-driven or database-backed registry.

2. **Per-style description storage in Qdrant / Supabase** (~50 LOC)
   The index only stores one description per tool. Multi-style serving requires either multiple Qdrant payloads per point or a side-table join at query time.

3. **Cache-aware description selection in `RAGService`** (~40 LOC)
   `_apply_selection_descriptions` currently applies a single static variant. It must be made client-context-aware, passing the resolved `VendorStyle` through the call stack.

4. **Fallback policy when client ID is unknown** (~20 LOC)
   If `x-client-id` is absent or unrecognized, the service must fall back to the default `V_gen` description without raising or degrading results.

5. **Observability: per-client variant logging** (~20 LOC)
   There is no current signal for which description variant was served per request. Without this, A/B effect measurement in production is impossible.

**Estimated total:** ~160 LOC across 2–3 PRs.

---

## Decision

**Defer full production implementation.** Implement the shadow-mode scaffold (Phase 0) as the next step.

The bias-max experiment results are not yet complete (Phases 0–1 are still running). Promoting the feature before results are validated risks shipping a variant that does not reliably improve recall. The shadow-mode scaffold is a low-risk, zero-regression path to collect the production signal needed to make that decision.

**Phase 1 TERMINATED** — 0 of 17 clusters met qualification criteria (`V_orig ≤ 30% AND max_enriched ≥ 20%`). No further Bias-Max runs needed.

**Vendor scope update:**
- **Gemini: EXCLUDED** from per-client routing tiers. Rationale: description-invariant (0% across all 17 clusters × 5 variants). Brand name in `tool_id` is the dominant selection signal. Improvement path: tool naming strategy (separate track).
- **Claude format routing downgraded from "ship candidate" to "shadow-mode-only"** pending large-scale replication of format interference finding (current evidence: n=5 pilot only; did NOT replicate under Bonferroni at n=2,550).

---

## Shadow-Mode Scaffold (Phase 0)

Shadow mode reads the `x-client-id` header and logs the variant that *would* have been applied — but does **not** alter the `selection_description` returned to the client.

Concretely:

1. Extract `client_id` from the `x-client-id` header (already done at `handler.py:88`).
2. Resolve `VendorStyle` via a stub routing table (default: `V_gen` for all unknown clients).
3. Log: `logger.info("shadow_mode client_id={} resolved_style={}", client_id, style)`.
4. **Do not** pass the resolved style to `_apply_selection_descriptions`. Results are unchanged.

This produces zero functional change and ~30 LOC, deliverable in a single PR. It validates the header plumbing and gives the team a Langfuse / log signal before any description variant is live.

---

## Alternatives Considered

1. **Apply immediately** — rejected. Experiment data is incomplete; promoting an unvalidated variant risks recall regression without a rollback signal.

2. **Full production implementation now** — rejected. The five missing components represent ~160 LOC across multiple subsystems. Building them before the experiment yields results is speculative engineering.

3. **Shadow-mode scaffold** — chosen. Delivers observable production signal at minimal risk (~30 LOC, one PR, zero functional change).

---

## Consequences

- Shadow-mode PR: ~30 LOC, zero functional impact, unblocks production observability.
- Full production rollout: ~160 LOC, 2–3 PRs, blocked on bias-max Phase 1 results.
- Existing retrieval path (FlatStrategy, `V_gen` descriptions) is unaffected.

---

## Follow-ups

- Bias-Max Gemini Phase 1 is TERMINATED — no further Gemini description experiments planned.
- For GPT/Claude clients: if shadow-mode logs confirm header plumbing is correct and format interference replicates at n≥100 per condition, proceed with the five missing components in order: routing table → storage → cache-aware selection → fallback → observability.
- If results are inconclusive or variant-dependent, scope a targeted A/B test with shadow-mode data before committing to production rollout.
- Gemini improvement path: pivot to tool_id/name relevance analysis (separate track, not blocked by this ADR).

---

## Amendment — Demo-Scope Exception (2026-04-22)

**Phase 1 demo-only implementation is permitted** without completing Phase 0 shadow collection,
provided the following constraints are satisfied:

1. No changes to `MCPTool` model or Qdrant payload schema
2. Variant data loaded in-memory from existing `VariantStore`/JSONL at service warm-start
3. `ENABLE_PER_CLIENT_ROUTING=false` default — production off, demo on
4. Gemini remains excluded from per-client description routing per this ADR
5. Cache isolation: per-client routing requests must use `client_id`-scoped cache keys

**Rationale:** User requirement is demo capability, not production rollout.
ADR-0019 Phase 0 (shadow mode collection) deferred to post-demo evaluation.

---

## See Also

- `docs/experiments/bias-max-gemini-report.md` — Gemini calibration TERMINATED result
- `docs/experiments/per-client-optimization-consolidated.md` — consolidated per-client experiment overview
- `docs/experiments/per-client-optimization-production-gap.md` — 3-tier production roadmap with code gap analysis
