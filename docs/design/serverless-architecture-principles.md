# Serverless Architecture Principles — MCP Discovery Platform

> "검색은 실시간으로 작게, 품질 개선은 비동기로 크게."

---

## Three-Plane Model

### 1. Query Plane (online / thin)
- Request-time retrieval only
- Lightweight reads of cached or precomputed state
- Filtering, shaping, response construction
- **No** heavy aggregation, analytics computation, or DB writes in hot path
- Bounded latency: `request → normalize → candidate fetch → rerank → response`

**Evidence**: Search/Bridge handlers are thin adapters, `RAGService` owns query orchestration, lexical fallback exists, and operability is read through a cached Supabase view rather than a second query-plane truth store.

### 2. Control Plane (offline / async)
- Registration, canonicalization, indexing
- Analytics aggregation and schema evolution
- Freshness / lifecycle management
- Batch insight generation
- Health scoring, quality audit

**Evidence**: Register → EventBridge → Index Lambda, replay/DLQ hardening, offline/provider-facing insight generation, and schema-managed read models.

### 3. Client Optimization Plane (offline / isolated)
- Per-client description transforms
- Experiments / evaluation
- Client-specific optimization logic
- Must not pollute hot path or canonical models

---

## Core Principles

### P1: Thin Hot Path
Hot path must be: thin, cold, predictable.

Never in hot path:
- DB migration checks
- Provider health recomputation
- Embedding fallback generation
- Schema patches
- Installability tests

### P2: Precomputed Reads
Current-state note:
- Accepted ADR-0022 documents a tactical deviation from full MV precompute at current scale.
- Serving-time operability uses cached reads from `tool_operability_view`.
- Dashboard funnel views remain live-view/read-time until the ADR-0022 tripwire is hit.

Target at scale:
- `tool_operational_stats` / `_7d` (execution metrics)
- `tool_selection_stats` / `tool_exposure_stats` / `_7d` (search analytics)
- `tool_daily_stats` (time-series)
- `tool_client_stats` / `tool_client_selection_stats` (per-client)
- `provider_tool_dashboard` (combined denormalization)

When the ADR-0022 tripwire is hit, these are restored to MV-backed refreshes.

### P3: Freshness as First-Class Field
Three-layer freshness (FreshnessTriple):
- **Source freshness**: when the upstream registry/manifest last changed
- **Index freshness**: when our search index last reflected it
- **Operational freshness**: when the tool was last successfully invoked

All three are tracked, surfaced to users, and used in ranking.

### P4: Entity Lifecycle State Machine
No hard deletes. Versioned deactivation:
- `pending → active → {unreachable, stale, quarantined, deprecated}`
- Valid transitions enforced by `VALID_TRANSITIONS` dict
- `derive_status()` computes from operational signals
- Blocked statuses gated from search results

### P5: Idempotency & Replayability
All background jobs assume duplicate execution:
- `event_id` for dedup on logs
- Upsert patterns for registration
- Content hash for change detection
- Deterministic IDs (`uuid5(namespace, tool_id)`)

### P6: Degraded Modes
Failure modes are designed, not emergent:
- Vector DB timeout → lexical-only fallback
- Reranker removed (architecture pivot) → embedding score only
- Hybrid failure → dense-only degraded recovery
- Freshness unknown → badge downgrade
- Health check stale → caution annotation
- Ingestion failure → previous index snapshot maintained

`source_path` tracks the source of returned results, while degraded behavior is exposed separately through the response contract and stage metrics.

### P7: Explainability
Every search result carries:
- `ScoreBreakdown`: relevance, quality, boost, trust, operability weights
- `reason`: client-facing explanation string
- `retrieval_score`: pre-merge score for transparency
- `operability`: status, cold_start, freshness, grade (A-F)

Provider dashboard surfaces all score components transparently.

### P8: Stage Observability
Per-stage metrics in query logs:
- Candidate retrieval latency
- Freshness search latency
- Rerank latency
- Fallback usage
- Cold-cache status
- `stage_metrics` JSONB in `query_logs`

### P9: Canonicalization
Raw registry data is never used directly for search:
- `CanonicalTool` / `CanonicalServer` — normalized entities
- `merge_candidates()` deduplicates by `tool_id`, preserves highest score
- `content_hash` for change detection
- `entity_status` tracks deprecated/superseded relationships

### P10: Data Contract Clarity
Separated models per concern:
- `MCPServer` / `MCPTool` — canonical entities
- `SearchResult` — query-plane response with score breakdown
- `ToolOperabilitySnapshot` — control-plane operational state
- `provider_tool_dashboard` VIEW — dashboard read model
- Frontend types mirror backend contracts

### P11: Multi-tenancy & Quota (Phase 2)
Required for production:
- Per-tenant ingestion/embedding/rerank budgets
- Dashboard analytics partitioned by provider
- API key scopes and rate limiting
- Abuse throttling

Currently: provider-level ownership via `providers` table + RLS. Quota enforcement deferred.

### P12: Composite Ranking
Ranking function: relevance + operability, with quality/trust/freshness planned for Phase 2.

```
# Live (current): 2-component
final_score = retrieval_score * 0.75 + operability * 0.25 + conditional_boost

# Phase 2 (planned): quality and boost activated after data accumulation
# Phase 2+: trust and freshness activated after provider telemetry
```

Trust signals (Phase 2): success_rate, latency, timeout_rate, call_count, freshness.

---

## Storage Separation

| Store | Purpose | Technology |
|-------|---------|------------|
| Registry canonical DB | providers, servers, tools, status, lifecycle | Supabase PostgreSQL |
| Search index | vector similarity, ANN | Qdrant Cloud |
| Lexical index | full-text search fallback | Supabase tsvector |
| Analytics store | query_logs, execution_logs, MVs | Supabase PostgreSQL |
| Cache | hot queries, operability snapshots | In-memory TTL (OperabilityCache) |

---

## Analytics Read Model (current state, 2026-04-19)

After migration 022, the analytics layer has the following read model:

| Object | Type | Refresh | Purpose |
|--------|------|---------|---------|
| `tool_operational_stats` | VIEW | on read | Per-tool execution success/failure counts |
| `tool_operational_stats_7d` | VIEW | on read | 7-day rolling window of above |
| `tool_selection_stats` | VIEW | on read | Per-tool recommendation counts (uses `recommended_tool_id` post-022) |
| `tool_exposure_stats` | VIEW | on read | Per-tool exposure (impression) counts |
| `tool_exposure_stats_7d` | VIEW | on read | 7-day rolling window of above |
| `tool_daily_stats` | VIEW | on read | Daily time-series per tool |
| `tool_client_stats` | VIEW | on read | Per-tool per-client breakdown |
| `tool_client_selection_stats` | VIEW | on read | Per-client recommendation breakdown |
| `provider_tool_dashboard` | VIEW | on read (JOIN of the above views) | Combined denormalized dashboard read model |
| `tool_exposure_facts` | VIEW | on read (raw aggregation) | Funnel exposure facts — scale risk at >50K rows (H4) |
| `tool_conversion_funnel` | VIEW | on read (raw aggregation) | Funnel conversion metrics — scale risk at >50K rows (H4) |

`tool_exposure_facts` and `tool_conversion_funnel` are regular VIEWs that aggregate `query_logs` and `execution_logs` directly. This entire read model is a current-scale live-view exception under ADR-0022. If the tripwire is hit, the view layer must be restored to MV-backed refreshes.

The `recommended_tool_id` column (renamed from `selected_tool_id` in migration 022 per ADR-0020) is the join key between `query_logs` and the selection/exposure MVs.

---

## Audit Status (2026-04-13)

| Principle | Status | Evidence |
|-----------|--------|----------|
| P1 Thin hot path | IMPLEMENTED | Search handler ~95 LOC |
| P2 Precomputed reads | DEFERRED / CURRENT-SCALE EXCEPTION | Live views accepted under ADR-0022 until restoration tripwire is hit |
| P3 Freshness triple | IMPLEMENTED | `FreshnessTriple` model |
| P4 Entity lifecycle | IMPLEMENTED | `VALID_TRANSITIONS` + `derive_status()` |
| P5 Idempotency | IMPLEMENTED | event_id, upsert, content_hash |
| P6 Degraded modes | IMPLEMENTED | Lexical fallback, status hard gate |
| P7 Explainability | IMPLEMENTED | ScoreBreakdown, reason, operability |
| P8 Stage observability | IMPLEMENTED | Per-stage latency in logs |
| P9 Canonicalization | IMPLEMENTED | CanonicalTool, merge_candidates |
| P10 Data contracts | IMPLEMENTED | Separated models per concern |
| P11 Multi-tenancy | PARTIAL | Provider ownership only; quota Phase 2 |
| P12 Composite ranking | PARTIAL | 2-component live (relevance 0.75 + operability 0.25); quality/trust/freshness Phase 2 |
