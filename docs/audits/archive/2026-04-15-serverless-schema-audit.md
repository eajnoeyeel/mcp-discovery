> **SUPERSEDED** — Archived 2026-04-19. Covered migrations 001–016 only. Superseded by `docs/audits/2026-04-19-serverless-schema-audit.md` which covers 001–024 and reflects the post-PR#73 state. Findings C2, C3, H1, H2, H3 addressed in migrations 017–021; C1 addressed in migrations 022–023 code path; new findings added for 022–024.

# Serverless Schema Audit — MCP Discovery Platform

> **Date**: 2026-04-15
> **Scope**: 16 migrations (001–016), 3 Supabase adapters, 5 views, 8 materialized views, RLS policies, pg_cron refresh
> **Method**: RALPLAN consensus (Planner → Architect → Critic, deliberate mode)
> **Status**: Consensus reached (Iteration 1)

---

## Executive Summary

The MCP Discovery Platform's database schema is **well-architected for serverless** with strong separation between query plane (precomputed MVs) and control plane (async indexing/refresh). The migration evolution from 001→016 shows disciplined progression from core catalog → lifecycle → operational stats → provider analytics → security hardening.

**Strengths**: Precomputed read model (8 MVs + combined VIEW), idempotent event logging (event_id dedup), content hash for change detection, three-tier freshness tracking, per-MV error isolation in refresh function.

**Weaknesses**: Plaintext secrets in `mcp_server_auth` (zero indirection), `refresh_token NOT NULL` latent bug blocking OAuth registration, phantom `provider_analytics` table reference, migration path divergence between fresh-install and live DB.

---

## Findings by Severity

### CRITICAL

#### C1: Plaintext Secrets in `mcp_server_auth` — Zero Indirection
- **Location**: Migration `008_execution_auth_metadata.sql:14-16`
- **Code path**: `service/lambdas/register/handler.py:144-152` writes plaintext `bearer_token`, `api_key` → `service/lambdas/execute/handler.py:162-164` reads them back in plaintext for upstream auth
- **Risk**: Database dump, Supabase backup restored to dev environment with shared service_role key, or any service_role key leak exposes all provider upstream credentials. RLS gates by role (`service_role` only), not by individual user identity — anyone with the key reads all rows.
- **Contrast**: `mcp_oauth_sessions` has partial mitigation via `_ref` columns (migration 010), but `mcp_server_auth` has **none**
- **Fix**: New migration adding `bearer_token_ref`, `api_key_ref` columns + Secrets Manager resolver (pattern exists in `service/adapters/supabase_oauth_tokens.py`) + update register/execute handlers + backfill + drop plaintext columns

#### C2: `refresh_token NOT NULL` Latent Bug — OAuth Registration Broken
- **Location**: Migration `014_oauth_gateway_tables.sql:39` — `refresh_token TEXT NOT NULL` with no DEFAULT
- **Code path**: `service/lambdas/register/handler.py:156-165` (`_oauth_session_row()`) builds INSERT payload **without** `refresh_token`. `service/adapters/supabase_oauth_tokens.py:83-98` (`store()`) also omits `refresh_token` from upsert payload.
- **Impact**: First OAuth session registration will fail with `NOT NULL constraint violation`. The entire OAuth provider registration path is broken.
- **Secondary**: `_store_sync()` at `supabase_oauth_tokens.py:111-139` duplicates the same omission (dead code, but if used for testing, tests will fail identically)
- **Fix**: `ALTER TABLE mcp_oauth_sessions ALTER COLUMN refresh_token DROP NOT NULL;` — the design intent (secret refs) means plaintext `refresh_token` should be optional

#### C3: Code-DB Contract Drift — `provider_analytics` Phantom Table
- **Location**: `service/adapters/supabase_client.py:448-477` (`fetch_tool_analytics`) reads from `/rest/v1/provider_analytics`
- **Evidence**: No migration in `service/supabase/migrations/` creates this table. Planning doc at `docs/superpowers/plans/2026-04-12-provider-analytics-frontend.md:622` acknowledges the table may not exist yet.
- **Mitigation**: Code has `try/except → return None` — intentional forward-reference with graceful degradation
- **Risk**: Future code that assumes `provider_analytics` exists will break silently. `supabase db reset` on clean instance will never create this table.
- **Fix**: Either add migration creating `provider_analytics` table, or remove `fetch_tool_analytics()` if only file-based path (`src/api/routes/provider_analytics.py`) will be used

### HIGH

#### H1: `mcp_tools` Missing `updated_at` Column + Trigger
- **Location**: Migration `001_initial.sql:36-53` — `mcp_tools` has only `created_at`
- **Contrast**: `mcp_servers` has both `created_at` and `updated_at` + trigger (lines 28-29, 137-140)
- **Impact**: `mark_indexed()` PATCH has no timestamp trail. General tool metadata updates are untrackable.
- **Fix**: Single migration adding `updated_at TIMESTAMPTZ DEFAULT now()` + `CREATE TRIGGER set_mcp_tools_updated_at`

#### H2: Missing GRANT SELECT on Views and MVs
- **Granted** (002, 004): `provider_dashboard_snapshot`, `server_tool_counts`, `provider_search_simulations`
- **Missing GRANT**: `provider_tool_dashboard` (012), `tool_operability_view` (011), all 8 MVs
- **Current mitigation**: All adapter code uses service_role key (bypasses GRANT)
- **Risk**: Any future non-service-role access path fails silently
- **Fix**: Single migration with `GRANT SELECT ON <view/mv> TO anon, authenticated;` for each

#### H3: `query_logs` Missing Index on `selected_tool_id`
- **Consumers**: `tool_selection_stats` MV (012:87-96), `provider_search_simulations` VIEW (004), `fetch_tool_simulations()` in adapter
- **Current**: Sequential scan during MV refresh (~OK at <1K rows/day)
- **Fix**: `CREATE INDEX idx_query_logs_selected_tool_id ON query_logs (selected_tool_id) WHERE selected_tool_id IS NOT NULL;`

#### H4: Fresh-Install vs Live-DB Schema Divergence
- **Problem**: Migration 009 creates `mcp_oauth_sessions` (without `_ref` columns) → 010 adds `_ref` columns → 014's `CREATE TABLE IF NOT EXISTS` is a **no-op** because table already exists from 009
- **Result**: Fresh install gets schema from 009+010 (no `CHECK` on `secret_backend`). Live DB gets schema from 014 (with `CHECK`). Different constraints on the same table depending on migration path.
- **Fix**: Add `ALTER TABLE ... ADD CONSTRAINT ... NOT VALID; VALIDATE CONSTRAINT` in a new migration to ensure both paths converge

### MEDIUM

#### M1: Regular VIEWs Doing Raw Aggregation
- `provider_dashboard_snapshot` (002): GROUP BY with avg/min/max/count on every read
- `provider_search_simulations` (004): GROUP BY with avg/count on every read
- Currently read from dashboard (control plane) — tolerable. Would violate P1 (Thin Hot Path) if used on query plane.
- `provider_dashboard_snapshot` is effectively superseded by `provider_tool_dashboard` (012) — dead schema

#### M2: 8 MVs Refreshed Every 5 Minutes Sequential
- `refresh_operational_stats()` (012:296-319) loops through all 8 MVs with `REFRESH MATERIALIZED VIEW CONCURRENTLY`
- Per-MV error handling is good (isolated failures)
- At scale (10K+ events/day): 8 sequential full-table scans every 5 min
- No alerting on refresh duration or failure count

#### M3: Log Tables Have No FK Constraints
- `execution_logs.tool_id`, `execution_logs.server_id`, `query_logs.selected_tool_id` — no FKs
- Intentional for append-only audit logs (avoids FK lock contention, enables out-of-order writes)
- Orphaned references possible but non-harmful for analytics

#### M4: Blocking I/O Pattern in OAuth Adapter
- `supabase_oauth_tokens.py:62-78` (`_fetch_sync`) uses sync `httpx.Client`
- Wrapped in `asyncio.to_thread()` at line 33 — event loop is NOT blocked, but wastes a thread pool thread
- `store()` at line 80 uses async `httpx.AsyncClient` — inconsistent within same class
- Not a functional risk, but violates project's async-only convention

#### M5: Migration 003 Missing + Numbering Collision History
- Migrations jump 002→004. No migration 003 exists or was deleted.
- Migration 011 header says `008_operational_stats.sql` (renumbered)
- Migration 014 consolidates 009+010 content with defensive `CREATE IF NOT EXISTS`
- Cosmetic but erodes confidence in migration ordering

### LOW

#### L1: No Partitioning on Log Tables
- Documented in `docs/design/scalability-strategy.md` as intentional at MLP stage
- Trigger defined: any table >10M rows or MV refresh >5s
- Plan exists (monthly partitioning with pg_partman)

#### L2: `search_tools_fts` Redefined 3 Times
- Created in 001, redefined in 002, redefined in 006 with `status_filter DEFAULT NULL`
- Function evolution is correct but noisy migration trail

#### L3: `_store_sync` Dead Code
- `supabase_oauth_tokens.py:111-139` — docstring says "Sync helper retained for test compatibility"
- Duplicates M4 bug (omits `refresh_token` from payload)
- Should be removed or fixed

---

## End-to-End Data Flow Validation

```
Registration (register Lambda)
  → mcp_servers INSERT/UPSERT (with owner_user_id, provider_id)     ✅
  → mcp_tools INSERT (with tool_id = server_id::tool_name)          ✅
  → mcp_server_auth INSERT (plaintext secrets — C1!)                 ⚠️
  → mcp_oauth_sessions INSERT (refresh_token NOT NULL bug — C2!)     ❌

Indexing (index Lambda)
  → mcp_tools PATCH: pending → indexing → indexed                    ✅
  → content_hash for skip-if-unchanged                               ✅
  → indexed_at timestamp for freshness tracking                      ✅
  → Qdrant upsert (uuid5 deterministic ID)                          ✅

Retrieval (search Lambda / RAG pipeline)
  → Qdrant dense search (primary)                                    ✅
  → search_tools_fts RPC (lexical fallback)                          ✅
  → tool_operability_view for ops score merge                        ✅
  → Confidence branching (gap > 0.15)                                ✅

Logging (query + execution)
  → query_logs INSERT (event_id dedup, stage_metrics, client_id)     ✅
  → execution_logs INSERT (event_id dedup, client_id)                ✅
  → client_id CHECK constraint for data quality                      ✅

Aggregation (pg_cron every 5 min)
  → refresh_operational_stats() → 8 MVs CONCURRENTLY                 ✅
  → Per-MV error isolation                                           ✅

Dashboard (provider analytics)
  → provider_tool_dashboard VIEW (6-way LEFT JOIN on MVs)            ✅
  → tool_daily_stats, tool_client_stats MVs                          ✅
  → provider_analytics table (phantom — C3!)                         ❌
```

**Flow is complete except**: C1 (plaintext secrets), C2 (OAuth INSERT broken), C3 (phantom table).

---

## RALPLAN-DR Summary (Deliberate Mode — Revised)

### Principles
1. **Schema-Code Fidelity**: Every table/view referenced in code must have a corresponding migration
2. **Secrets Never at Rest in DB**: Credentials must use external secret manager references, not plaintext
3. **Precomputed Read Model**: Dashboard/analytics reads from MVs, not raw aggregation
4. **Migration Path Convergence**: Fresh-install and live-DB paths must produce identical schemas
5. **Symmetric Entity Design**: Equivalent entities should have equivalent columns

### Decision Drivers
1. **Security posture** — plaintext `bearer_token`/`api_key` actively read in execute path
2. **Feature correctness** — OAuth registration path broken by `refresh_token NOT NULL`
3. **Schema reliability** — phantom table + path divergence erodes migration trust

### Viable Options

**Option A1: Minimal Schema Fixes (Low blast radius)**
- Fix C2 (`refresh_token DROP NOT NULL`), C3 (add `provider_analytics` migration or remove dead code), H1 (`updated_at` on tools), H2 (GRANT statements), H3 (index on `selected_tool_id`)
- **Scope**: 2-3 new migrations, 0 Python changes
- Pros: Truly minimal, no regression risk on critical paths
- Cons: Defers security hardening (C1)

**Option A2: Security Hardening (Medium blast radius)**
- Fix C1 (`mcp_server_auth` secret refs + handler updates)
- **Scope**: 1 migration + new adapter + register/execute handler changes + backfill
- Pros: Eliminates highest-risk finding, aligns with P2
- Cons: Touches critical execution path (register + execute Lambdas), needs e2e test coverage

**Option B: Comprehensive Schema Cleanup**
- A1 + A2 + migration renumbering, VIEW→MV conversion, dead view removal, schema path convergence, FK additions to log tables
- Pros: Clean, future-proof schema
- Cons: High blast radius, requires careful ordering, extensive testing

### Pre-mortem (3 scenarios — deliberate mode)

**Scenario 1 (Security — System-specific)**: Supabase DB backup is restored to a shared dev environment. The service_role key is distributed to developers for debugging. `mcp_server_auth.bearer_token` and `mcp_server_auth.api_key` values are readable via PostgREST by anyone with the service_role key, since RLS gates by role, not individual identity. All registered MCP server upstream credentials are exposed. Blast radius: every server with `auth_type != 'none'`.

**Scenario 2 (Correctness)**: A provider attempts OAuth-based MCP server registration. `_oauth_session_row()` omits `refresh_token`, INSERT fails with `NOT NULL constraint violation`. The 500 error is logged but the provider sees a generic failure. No alert fires because error monitoring isn't connected to this specific constraint. The OAuth registration feature is silently broken until someone manually tests it.

**Scenario 3 (Scalability)**: At 10K+ events/day, the 5-minute pg_cron job executing 8 sequential `REFRESH MATERIALIZED VIEW CONCURRENTLY` operations exceeds the Supabase pg_cron statement timeout (default 60s on some plans). Partial refresh occurs — some MVs stale, others current. `provider_tool_dashboard` JOIN produces inconsistent data (fresh operational stats + stale selection stats). No alerting exists on `refresh_operational_stats()` failures beyond the `RAISE WARNING` in the function body, which goes to PostgreSQL logs that nobody monitors.

### Expanded Test Plan

**Unit** (reference: `tests/unit/test_mlp_schema_contracts.py`):
- Test `_oauth_session_row()` payload includes all NOT NULL columns from migration 014
- Test `store()` payload matches `mcp_oauth_sessions` column set
- Test all Pydantic models (`MCPServer`, `MCPTool`, `OAuthTokenRecord`) field sets match their DB table column sets
- Test `event_id` uniqueness constraint enforcement on execution_logs/query_logs

**Integration** (on clean Supabase branch):
- Run migrations 001→016 sequentially, assert all 7 tables + 5 views + 8 MVs exist with expected column counts
- Run migrations on LIVE path (skip 009/010, only 014) — verify schema matches fresh-install path
- Verify `search_tools_fts()` RPC returns expected shape with NULL and non-NULL `status_filter`
- Verify `refresh_operational_stats()` completes within 10s on empty MVs
- Verify `provider_tool_dashboard` VIEW is queryable and returns all expected columns

**E2E**:
- Full cycle: register server → insert tools → index → search → execute → verify MV refresh → read dashboard
- OAuth registration path: register with `auth_type=oauth_session` → verify INSERT succeeds (after C2 fix)

**Observability**:
- Monitor `refresh_operational_stats()` duration via pg_cron job status table (`cron.job_run_details`)
- Alert on any MV refresh failure (check `RAISE WARNING` messages in pg logs or add explicit logging)
- Track MV freshness lag: `now() - max(last_called_at)` from `tool_operational_stats`

---

## Recommendation

**Execute A1 immediately** (2-3 migrations, zero Python risk), then **A2 before any production deployment** (security hardening with full e2e test coverage). Defer Option B until post-production stabilization.

| Priority | Finding | Fix | Files Touched |
|----------|---------|-----|---------------|
| NOW | C2: `refresh_token NOT NULL` bug | Migration: `ALTER COLUMN refresh_token DROP NOT NULL` | 1 migration |
| NOW | C3: Phantom `provider_analytics` | Migration creating table OR remove `fetch_tool_analytics()` | 1 migration or 1 Python file |
| NOW | H1: `mcp_tools` missing `updated_at` | Migration: ADD COLUMN + trigger | 1 migration |
| NOW | H2: Missing GRANTs | Migration: GRANT SELECT on all MVs/views | 1 migration |
| NOW | H3: Missing index | Migration: index on `query_logs(selected_tool_id)` | 1 migration |
| PRE-PROD | C1: Plaintext secrets | Migration + new adapter + handler updates + backfill | 1 migration, 3-4 Python files |
| PRE-PROD | H4: Schema path divergence | Migration ensuring 009→014 convergence | 1 migration |
| DEFER | M1: VIEW→MV conversion | Convert raw aggregation views to MVs | 1 migration |
| DEFER | M2: MV refresh monitoring | Add pg_cron duration alerting | Observability config |
| DEFER | M5: Migration cleanup | Renumber/consolidate | Documentation only |

---

## Schema Strengths (What's Done Well)

1. **Precomputed read model**: 8 MVs + combined `provider_tool_dashboard` VIEW — dashboard never hits raw log tables
2. **Idempotent event logging**: `event_id` partial unique index on both log tables — Lambda retries are safe
3. **Content hash**: `content_hash` on `mcp_tools` — skip re-embedding if tool description unchanged
4. **Three-tier freshness**: `source_updated_at`, `indexed_at`, `last_health_check_at` — full provenance chain
5. **Entity lifecycle**: 7-state `index_status` CHECK + `entity_status` on servers — no hard deletes
6. **Per-MV error isolation**: `refresh_operational_stats()` catches per-MV exceptions — one failure doesn't block others
7. **Zero-downtime constraints**: Migration 013 uses `NOT VALID` + `VALIDATE` pattern for client_id CHECK
8. **Batched backfill**: Migration 012 uses `ctid`-limited batches with `pg_sleep` for provider_id backfill
9. **RLS design**: Sensitive tables (auth, oauth, gateway) are service_role-only; catalog tables are anon-readable
10. **Secrets Manager migration path**: OAuth sessions have `_ref` columns + `secret_backend` enum — pattern exists for extension to `mcp_server_auth`
