# Per-Client Description Optimization — Production Gap Audit

**Date:** 2026-04-22
**Status:** Gap identified, 3-tier roadmap defined

---

## Current Code State

### What Exists

| Component | File | Line | Status |
|-----------|------|------|--------|
| `MCPTool.selection_description` | `src/mcp_discovery/models/core.py` | :72 | Exists |
| `VendorStyle` enum | `src/mcp_discovery/description/base.py` | :8 | Exists |
| `_apply_selection_descriptions()` | `service/rag/service.py` | :19 | Exists (applies single variant) |
| `x-client-id` header extraction | `service/lambdas/search/handler.py` | :88 | Read (fire-and-forget logging only) |
| Per-client routing | `service/lambdas/search/handler.py` | — | x-client-id not passed to search_service |

### The Gap (One Argument)

`x-client-id` is extracted at `handler.py:88` for query logging purposes, but `search_service.search(request)` is called at line ~73 with a `SearchRequest` that contains only `query` and `top_k`. The `client_id` is never forwarded to the RAG layer, so `_apply_selection_descriptions()` always applies the default `V_gen` variant regardless of which client is calling.

```python
# handler.py ~line 73 — search_service.search() has no client_id
response = await search_service.search(request)

# handler.py ~line 88 — x-client-id extracted AFTER search, logging only
raw_client_id = headers.get("x-client-id") or headers.get("X-Client-Id")
client_id = raw_client_id.strip().lower() if raw_client_id else None
# client_id goes to query_logger only, never to rag_service
```

---

## 3-Tier Roadmap

### Tier 1 — Universal Enriched Descriptions (NOW)

- **What:** Improve `selection_description` quality for all tools uniformly
- **Why:** Information enrichment improves recall across ALL vendors (+11.4%p average at n=2,550, Phase 4 evidence)
- **How:** Data pipeline improvement — rerun enrichment scripts, upsert to Qdrant. No code change needed.
- **Risk:** Zero — existing retrieval path unaffected
- **Evidence gate:** Already passed (Phase 4 n=2,550)
- **Scope:** ~0 LOC code, data-only

### Tier 2 — Shadow Mode (~30 LOC)

- **What:** Pass `x-client-id` through to the RAG layer; log which variant WOULD be selected without changing the response
- **Why:** Validates header plumbing and routing logic before enabling live per-client selection; produces Langfuse signal
- **How:**
  1. Add `client_id: str | None = None` to `SearchRequest` (`service/services/contracts.py`)
  2. Populate `client_id` from headers before `search_service.search(request)` in `handler.py`
  3. In `_apply_selection_descriptions()` (`service/rag/service.py:19`), resolve `VendorStyle` from `client_id` and log shadow decision — but do not change descriptions returned
- **Risk:** Low (logging only, zero functional change)
- **Evidence gate:** Tier 1 deployed; format interference replication at n≥100 per condition pending
- **Scope:** ~30 LOC across 3 files

### Tier 3 — Full Per-Client Routing (~160 LOC)

- **What:** Actually apply vendor-specific `selection_description` variants based on `x-client-id` at query time
- **Five missing components:**
  1. Client-to-style routing table (~30 LOC) — config-driven registry mapping `client_id` → `VendorStyle`
  2. Per-style description storage in Qdrant/Supabase (~50 LOC) — multi-style payloads or side-table join
  3. Cache-aware description selection in `RAGService` (~40 LOC) — make `_apply_selection_descriptions()` client-context-aware
  4. Fallback policy for unknown client_id (~20 LOC) — default to `V_gen` without degrading results
  5. Per-client variant logging (~20 LOC) — observability for A/B measurement in production
- **Evidence gate:** Format interference (Act II) replicated at n≥100 per condition; Tier 2 shadow logs validated
- **Gemini:** EXCLUDED — description-invariant (0% across all 17 clusters × 5 variants); separate tool naming track
- **Scope:** ~160 LOC across 2–3 PRs

---

## Gemini Exclusion Rationale

The Bias-Max Gemini calibration (Phase 0, 17 clusters × 5 variants × 1 rep) found:

- 15/17 clusters: 0% hit rate across ALL description variants (V_orig, V_prose, V_spec, V_md, V_xml)
- Remaining 2 clusters (get_001, get_002): already saturated at 80–100% with original descriptions
- Enrichment occasionally hurts: get_001 drops from 100% to 67% under V_spec

**Conclusion:** Gemini selects tools based primarily on `tool_id` string similarity, not description content. Description optimization provides no measurable recall gain. The improvement path for Gemini clients is tool naming strategy (tool_id clarity, server_name alignment) — a separate investigation track.

Phase 1 of the Bias-Max experiment was TERMINATED: 0 of 17 clusters met the qualification criteria (`V_orig ≤ 30% AND max_enriched ≥ 20%`). No further Bias-Max runs are needed for Gemini.

---

## References

- `docs/experiments/per-client-description-experiment-report.md` — GPT/Claude per-client experiment results
- `docs/experiments/bias-max-gemini-report.md` — Gemini calibration negative result (TERMINATED)
- `docs/adr/0019-per-client-description-applicability-gap.md` — ADR with shadow-mode scaffold design
- `docs/experiments/per-client-optimization-consolidated.md` — consolidated experiment overview
