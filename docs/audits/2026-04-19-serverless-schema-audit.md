# Serverless Schema Audit — MCP Discovery Platform

> **Date**: 2026-04-19
> **Scope**: 24 migrations (001–024), service/supabase/migrations/, views, materialized views, RLS policies, pg_cron
> **Method**: RALPLAN consensus (schema-audit-fixes team)
> **Status**: Accepted — supersedes `docs/audits/archive/2026-04-15-serverless-schema-audit.md`
> **Pre-migration anchor**: PR#73 (hybrid dense+sparse RRF, R@3=46.8%) landed on main immediately before migrations 022–024

---

## Executive Summary

Migrations 017–024 resolved the three critical and two high findings from the 2026-04-15 audit (C2, C3, H1, H2, H3). The schema is now 24 migrations deep with a strengthened analytics layer (022: column rename + FK + funnel views), operational hardening (023: `event_failed` status), and enrichment caching (024: `tool_enrichment_cache` for ADR-0017 hybrid path).

**New findings introduced by 017–024**: duplicate filename prefixes on 020_ and 021_ (H3), raw aggregation scale risk on new funnel views (H4), missing RLS + `updated_at` on `tool_enrichment_cache` (M2), and minor asymmetries (M3, M5, L1–L4).

**Resolved from prior audit**: C2 (`refresh_token NOT NULL` — dropped), C3 (phantom `provider_analytics` — resolved), H1 (`mcp_tools.updated_at` — added), H2 (GRANT SELECT — added), H3/old (missing index on `selected_tool_id` — column renamed, index exists on `recommended_tool_id`).

**Outstanding critical**: C1 (plaintext secrets at rest in `mcp_server_auth`) — partially addressed at code path level (secret-ref reads only); DB column drop migration pending.

---

## Migration Inventory (001–024)

| # | File | Key Change |
|---|------|-----------|
| 001 | initial.sql | Core catalog: mcp_servers, mcp_tools, providers |
| 002 | provider_dashboard.sql | provider_dashboard_snapshot VIEW, GRANTs |
| 003 | _(gap — not present)_ | — |
| 004 | search_fts.sql | search_tools_fts RPC, provider_search_simulations VIEW |
| 005–007 | lifecycle, auth, events | Status lifecycle, mcp_server_auth, event logging |
| 008 | execution_auth_metadata.sql | Plaintext bearer_token/api_key (C1 origin) |
| 009–010 | oauth_sessions, oauth_refs | mcp_oauth_sessions + \_ref columns |
| 011 | operability_view.sql | tool_operability_view |
| 012 | operational_stats.sql | 8 MVs + provider_tool_dashboard VIEW + pg_cron |
| 013 | client_id_constraint.sql | client_id NOT VALID + VALIDATE pattern |
| 014 | oauth_gateway_tables.sql | Consolidates 009+010 with CHECK constraint |
| 015 | server_github_metadata.sql | server_github_metadata table |
| 016 | tool_enrichment_columns.sql | Enrichment columns on mcp_tools |
| 017–021 | (resolution migrations) | C2/C3/H1/H2/H3 fixes from prior audit |
| 020_mv_to_view.sql | _(duplicate prefix — H3)_ | MV → VIEW conversion |
| 020_http_mcp_metadata_overrides.sql | _(duplicate prefix — H3)_ | HTTP MCP metadata overrides |
| 021_analytics_views_fix.sql | _(duplicate prefix — H3)_ | Analytics views correction |
| 021_http_mcp_parameter_metadata.sql | _(duplicate prefix — H3)_ | HTTP MCP parameter metadata |
| 022 | query_logs_evolution.sql | recommended_tool_id rename + execution FK + funnel views (ADR-0020) |
| 023 | event_failed_status.sql | 'event_failed' added to mcp_tools index_status enum |
| 024 | tool_enrichment_cache.sql | tool_enrichment_cache table for ADR-0017 hybrid path (ADR-0021) |

---

## Findings by Severity

### CRITICAL

#### C1: Plaintext Secrets at Rest in `mcp_server_auth` — DB Column Drop Pending
- **Origin**: Migration 008 (bearer_token, api_key columns)
- **Current state**: Code path updated (worker-backend) to write/read secret refs only. DB columns still exist with legacy plaintext values for any server registered before the code change.
- **Risk**: Supabase backup restore to dev environment exposes all pre-migration upstream credentials. RLS gates by service_role, not individual identity.
- **Fix**: Migration dropping `bearer_token` and `api_key` columns after a backfill window confirming all rows have populated `_ref` equivalents. Tracked in migration 025 plan.

### HIGH

#### H1: TypeScript Drift — `selected_tool_id` References (Partially Resolved)
- **Origin**: Migration 022 renamed `query_logs.selected_tool_id` → `recommended_tool_id`
- **Current state**: RAGService Python and `useToolDashboard` hook updated per worker-frontend/worker-backend. Any Supabase saved queries, PostgREST filters, or external analytics tooling using `selected_tool_id` will silently return empty results.
- **Fix**: Audit all external consumers (Supabase dashboard saved queries, any BI tooling). Add a DB-level alias view if a transition window is needed.

#### H2: Stale Audit + Missing ADRs — Resolved by This Audit
- **Prior state**: 2026-04-15 audit covered 001–016 only; migrations 017–024 were undocumented.
- **Current state**: This audit covers 001–024. ADR-0020 and ADR-0021 written. ADR index updated.
- **Status**: RESOLVED.

#### H3: Duplicate 020_ and 021_ Migration Filename Prefixes
- **Files**: `020_mv_to_view.sql` + `020_http_mcp_metadata_overrides.sql`; `021_analytics_views_fix.sql` + `021_http_mcp_parameter_metadata.sql`
- **Risk**: Supabase migration runner applies migrations in filename order. Two files sharing a prefix are non-deterministically ordered between each other. If either file has a dependency on the other (e.g., view redefined after column added), the order matters and may be wrong on clean installs.
- **Fix**: Renumber to 020, 020b/021, 021b — or use a single squash migration. Tracked as migration 026 rename task.

#### H4: Dashboard Raw Aggregation Scale Risk — `tool_exposure_facts` / `tool_conversion_funnel`
- **Location**: Migration 022 — both views are regular VIEWs aggregating `query_logs` and `execution_logs` on read
- **Risk**: At 10K+ events/day, a dashboard page load triggering these views executes a full GROUP BY + COUNT over unbounded log tables. Violates P1 (Thin Hot Path) if used in any query-plane path; tolerable today on control-plane dashboard only.
- **Fix**: Convert to materialized views refreshed by `refresh_operational_stats()` once log volume exceeds 50K rows. Add to pg_cron job.

### MEDIUM

#### M1: `server_github_metadata` Missing `updated_at` Trigger
- **Location**: Migration 015 — table has `created_at` but no `updated_at` column or trigger
- **Contrast**: `mcp_servers` and `mcp_tools` (post-017) both have `updated_at` triggers
- **Fix**: Migration adding `updated_at TIMESTAMPTZ DEFAULT now()` + trigger

#### M2: `tool_enrichment_cache` Missing RLS + `updated_at`
- **Location**: Migration 024 — no RLS policy, no `updated_at` trigger
- **Risk**: Any service_role consumer can read all cached enrichment payloads (includes LLM-generated keyword/category signals). `updated_at` absence means cache hit age is untrackable.
- **Fix**: Migration 025 — add RLS (service_role only, consistent with mcp_server_auth pattern) + `updated_at` trigger

#### M3: Index Asymmetry — `mcp_servers` vs `mcp_tools`
- **Current**: `mcp_servers` has index on `status`; `mcp_tools` has index on `index_status` and `server_id` but not on `status` (entity_status)
- **Impact**: Queries filtering tools by entity_status (e.g., deprecated tool gating) do full scan on mcp_tools
- **Fix**: `CREATE INDEX idx_mcp_tools_entity_status ON mcp_tools (entity_status) WHERE entity_status != 'active';`

#### M4: `provider_tool_dashboard` Leaks Cross-Provider Metrics
- **Location**: Migration 012 — VIEW is not filtered by `provider_id`; returns all providers' aggregated stats in a single query
- **Current mitigation**: Dashboard fetch in adapter filters by `provider_id` in WHERE clause
- **Risk**: If any future code path reads the VIEW without a WHERE filter, all providers' metrics are exposed
- **Fix**: Create a provider-scoped wrapper view or add `SET app.current_provider_id` + RLS predicate

#### M5: `mcp_tools` Timestamp Column Overlap
- **Columns**: `created_at`, `updated_at` (added 017), `indexed_at`, `source_updated_at`, `last_health_check_at`
- **Overlap**: `updated_at` and `indexed_at` can diverge in confusing ways: a metadata PATCH updates `updated_at` but not `indexed_at`; a re-index updates `indexed_at` but not `updated_at` if description unchanged
- **Fix**: Document the semantic distinction in a migration comment or CLAUDE.md; no schema change needed

### LOW

#### L1: FTS Column Excludes Override Fields
- **Location**: `search_tools_fts` (migration 006) — tsvector built from `tool_name + description` only
- **Gap**: HTTP MCP metadata overrides (migration 020_http_mcp_metadata_overrides) add override fields not included in the FTS tsvector
- **Fix**: Rebuild FTS function to include override fields, or add a separate override tsvector column

#### L2: No Partial Index on `mcp_tools.indexed_at` for Stale-Refresher Queue
- **Use case**: Stale-refresher Lambda queries `WHERE indexed_at < now() - interval '24 hours' AND index_status = 'indexed'`
- **Current**: Full scan on mcp_tools for this pattern
- **Fix**: `CREATE INDEX idx_mcp_tools_stale ON mcp_tools (indexed_at) WHERE index_status = 'indexed';`

#### L3: `search_tools_fts` Redefined Three Times
- **Files**: Migrations 001, 002, 006 — function evolved but trail is noisy
- **Fix**: Documentation only; no functional issue

#### L4: `provider_search_simulations` Does Not Filter `event_type`
- **Location**: Migration 004 VIEW — aggregates all `query_logs` rows regardless of `event_type`
- **Gap**: Post-migration 023, `event_failed` is a valid `index_status` value on `mcp_tools`; if `event_type` logging is added to `query_logs`, this view will over-count
- **Fix**: Add `WHERE event_type = 'search'` predicate when `event_type` column is added

---

## End-to-End Data Flow Validation

```
Registration (register Lambda)
  → mcp_servers INSERT/UPSERT                                         ✅
  → mcp_tools INSERT                                                  ✅
  → mcp_server_auth INSERT (secret refs only post-worker-backend)     ✅ (code)
  → mcp_server_auth legacy plaintext columns still exist in DB        ⚠️ (C1 pending)
  → mcp_oauth_sessions INSERT (refresh_token nullable post-017)       ✅

Indexing (index Lambda)
  → mcp_tools PATCH: pending → indexing → indexed / event_failed      ✅
  → content_hash skip-if-unchanged                                    ✅
  → tool_enrichment_cache lookup/write (ADR-0021)                     ✅
  → Qdrant upsert (uuid5 deterministic ID)                            ✅

Retrieval (search Lambda / RAG pipeline — PR#73 anchor R@3=46.8%)
  → Qdrant hybrid dense+sparse RRF (primary)                          ✅
  → search_tools_fts RPC (lexical fallback)                           ✅
  → tool_operability_view for ops score merge                         ✅
  → Confidence branching (gap > 0.15)                                 ✅

Logging (query + execution)
  → query_logs INSERT (recommended_tool_id post-022)                  ✅
  → execution_logs INSERT (query_log_id FK post-022)                  ✅
  → event_id dedup on both tables                                     ✅

Aggregation (pg_cron every 5 min)
  → refresh_operational_stats() → 8 MVs CONCURRENTLY                 ✅
  → tool_exposure_facts / tool_conversion_funnel (raw VIEW — H4)      ⚠️

Dashboard
  → provider_tool_dashboard VIEW (6-way LEFT JOIN on MVs)             ✅
  → tool_exposure_facts / tool_conversion_funnel (scale risk — H4)   ⚠️
```

---

## Finding Status vs 2026-04-15 Audit

| Finding | Prior Status | Current Status |
|---------|-------------|----------------|
| C1: Plaintext secrets | OPEN | PARTIAL (code fixed; DB columns pending drop) |
| C2: refresh_token NOT NULL | OPEN | RESOLVED (migration 017) |
| C3: Phantom provider_analytics | OPEN | RESOLVED |
| H1: TS drift selected_tool_id | OPEN | PARTIAL (code updated; external consumers need audit) |
| H2: Stale audit + missing ADRs | OPEN | RESOLVED (this document + ADR-0020/0021) |
| H3: Missing index on selected_tool_id | OPEN | RESOLVED (renamed column, index on recommended_tool_id) |
| H4: Fresh-install vs live DB divergence | OPEN | DEFERRED (duplicate 020/021 prefix is related — H3 new) |
| M1: Raw aggregation in views | OPEN | PARTIAL (old views tolerable; new funnel views flagged H4) |
| M2: MV refresh monitoring | OPEN | DEFERRED |
| M3: No FK on log tables | OPEN | INTENTIONAL (append-only audit design) |
| M4: Blocking I/O in OAuth adapter | OPEN | DEFERRED |
| M5: Migration 003 gap + numbering | OPEN | WONTFIX (cosmetic) |

---

## Recommendation

| Priority | Finding | Fix | Migration # |
|----------|---------|-----|-------------|
| NOW | C1: Drop legacy plaintext columns after backfill confirm | Migration dropping bearer_token/api_key | 025 |
| NOW | M2: tool_enrichment_cache RLS + updated_at | Migration + trigger | 025 |
| NOW | H3: Duplicate 020/021 prefix rename | Rename files | 026 |
| SOON | H4: Convert funnel views to MVs | Add to refresh_operational_stats() | 027 |
| SOON | M1: server_github_metadata updated_at | Migration + trigger | 028 |
| DEFER | M3: entity_status index on mcp_tools | Partial index | backlog |
| DEFER | L1: FTS override field inclusion | Rebuild FTS function | backlog |
| DEFER | L2: Partial index on indexed_at | Index migration | backlog |
