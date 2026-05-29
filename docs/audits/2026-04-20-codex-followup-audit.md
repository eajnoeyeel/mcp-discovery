# Codex follow-up audit — 2026-04-20

External audit run via Codex CLI + `backend-patterns` skill, pointing at the post-2026-04-19 state of the schema. 8 findings raised; 2 were already in the auth-team handoff queue (F1 OAuth contract after 029, F2 `030` fixture delete scope); 6 were validated and triaged here.

## Findings — validated

| # | Severity | Area | Fix decision |
|---|---|---|---|
| **F3** | High | Live-view analytics, N+1 on dashboard drill-downs | **Deferred** — ADR-0024 |
| **F4** | High | Analytics views granted SELECT to anon/authenticated | **Fixed** — migration 032 revokes |
| **F5** | High | `is_published` never filtered in public catalog reads | **Fixed** — adapter `public_only=True` default |
| **F6** | Medium | Mutable `tool_id` / `server_id` in logs — no replay stability | **Deferred** — ADR-0024 |
| **F7** | Medium | `tool_conversion_funnel` LEFT JOIN inflates recommendation_count | **Fixed** — adapter dedupes by `query_log_id` |
| **F8** | Medium | BRIN + B-tree duplicate on log `created_at` | **Fixed** — migration 031 drops BRIN |

## What we actually changed

### DB (applied live via Supabase MCP)

- `drop_brin_log_indexes_redundant` — drops `brin_execution_logs_created_at`, `brin_query_logs_created_at`. B-tree from migration 001 remains.
- `revoke_analytics_view_public_grants` — removes SELECT from anon/authenticated on 12 analytics views (`tool_operational_stats`/`_7d`, `tool_selection_stats`, `tool_exposure_stats`/`_7d`, `tool_daily_stats`, `tool_client_stats`/`_selection_stats`, `tool_exposure_facts`, `tool_conversion_funnel`, `provider_search_simulations`, `tool_operability_view`). `provider_tool_dashboard` stays REVOKEd from migration 028. `server_tool_counts` remains public (non-sensitive).
- Corresponding local migrations: `031_drop_brin_log_indexes.sql`, `032_revoke_analytics_view_grants.sql`.

### Code

- `service/adapters/supabase_client.py`:
  - `fetch_tool_conversion_stats` — selects `query_log_id,funnel_outcome`, dedupes per `query_log_id`; converted-wins for multi-execution recommendations (F7).
  - `fetch_servers(*, public_only=True)`, `fetch_server(*, public_only=True)` — default filter `is_published=eq.true`. Internal callers pass `public_only=False` explicitly (F5).
  - `fetch_owned_tool_detail`, `fetch_owned_server_tools` — `public_only=False` (owner path sees unpublished).
- `service/services/dashboard_service.py` — provider drill-down uses `public_only=False`.
- Tests:
  - `tests/unit/test_schema_audit_20_findings.py` (new) — 9 tests covering F5 defaults, opt-in, F7 dedup semantics.
  - `tests/unit/mlp/test_mlp_catalog_dashboard.py` — fetch_server assertion updated for owner path.
  - `tests/unit/mlp/test_mlp_supabase_client.py` — conversion funnel fixtures updated with `query_log_id` keys.

### Docs

- `docs/adr/0024-analytics-precompute-and-replay-stability-deferral.md` — ADR for F3 + F6 deferrals.
- This file (`2026-04-20-codex-followup-audit.md`) — audit record.

## Pre-mortem scenarios cleared before applying

- **S1 (F5 hides live data)**: `SELECT count(*) FROM mcp_servers WHERE is_published IS NOT TRUE` returned `0`. No existing row gets hidden.
- **S2 (F4 breaks frontend)**: `grep -R '/rest/v1/\(tool_\|provider_\|server_\)' service/frontend/src` returned no matches. Frontend does not read analytics views directly; service-role adapters bypass REVOKE.
- **S3 (F7 partial rollout)**: adapter-only fix, no SQL change, single commit atomicity.

## Verification (live)

```sql
-- F8: BRIN gone
SELECT count(*) FROM pg_indexes
 WHERE indexname IN ('brin_execution_logs_created_at','brin_query_logs_created_at');
-- → 0

-- F4: grants revoked
SELECT has_table_privilege('anon',           'tool_conversion_funnel',   'SELECT');  -- false
SELECT has_table_privilege('authenticated',  'tool_selection_stats',     'SELECT');  -- false
SELECT has_table_privilege('service_role',   'tool_selection_stats',     'SELECT');  -- true
```

All confirmed.

## Handoff notes

- **Auth team** (already holding 029/030): before applying `029`, re-read `ADR-0024` — the scale tripwire that would force F3/F6 work should be monitored after the OAuth path lands.
- **Deploy**: Lambda deploy (per service/CLAUDE.md) remains the operator's responsibility. Refs-only adapter code still unreleased to prod until `sam deploy` runs with stack config.
