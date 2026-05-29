# ADR-0024 — Analytics precompute and replay stability (deferred)

- **Status**: Accepted
- **Date**: 2026-04-20
- **Related**: ADR-0022 (MV→view reversal), 2026-04-20 Codex audit findings F3 / F6

## Context

The 2026-04-20 Codex audit of the schema + migration set raised two architectural concerns that, while valid, are not worth fixing at current scale:

**F3 — Provider analytics is read-time aggregation, not precomputed**
- Migrations `020_mv_to_view.sql` + `021_analytics_views_fix.sql` replaced the 8 materialized views with live views and no-opped `refresh_operational_stats()`.
- `dashboard_service.get_provider_dashboard` reads `provider_tool_dashboard` once (single query, ~300 rows), but supplementary per-tool drill-downs (`fetch_tool_daily_stats`, `fetch_tool_client_stats`, `fetch_tool_client_selection_stats`, `fetch_tool_exposure_count`, `fetch_tool_conversion_stats`) fan out one query per tool.
- At current scale (~300 servers, ~3K tools, <1K log rows per table) the live aggregation cost is negligible. Dashboard p95 stays well below the tripwire set in ADR-0022 (200ms / 500K rows).

**F6 — Analytics history is not stable under tool rename / ownership change**
- `mcp_tools` has both an internal UUID (`id`) and a mutable TEXT `tool_id` (format `server_id::tool_name`). Logs use the TEXT `tool_id` as their join key.
- Views like `provider_search_simulations` and `tool_conversion_funnel` join logs back through the current catalog state. If a provider renames a tool or transfers a server, historical analytics are retroactively re-attributed.
- For current alpha reporting this is acceptable; for replay-stable provider analytics (e.g. monthly invoices, compliance auditing) it is not.

## Decision

**Defer both.** Keep the live-view read model (ADR-0022). Do not introduce a snapshot / immutable-log-key design yet. Address when scale or product commitments force it.

## Rationale

- **F3 rebuild cost vs benefit.** Restoring the MV pipeline requires: 8 MV recreations, pg_cron refresh job, monitoring hooks, per-MV error isolation (already patterned in migration 011 — not wasted work, but not small). Net benefit at current scale is invisible.
- **F6 rebuild cost.** Would require: migration adding `tool_uuid` / `provider_id_snapshot` columns to log tables, writer-side changes in every log emitter, view rewrites, backfill strategy for existing 299 rows. Invasive.
- **Scale tripwire already exists** (ADR-0022): when dashboard p95 > 200ms OR `execution_logs.count` > 500K, revisit. Add F3/F6 to the scope of that revisit.
- **Metric correctness is handled separately.** The F7 dedup fix (`fetch_tool_conversion_stats` counts distinct `query_log_id`) is applied — this closes the only read-time correctness bug. F3/F6 are performance / replay-stability concerns, not correctness.

## Consequences

Positive
- No premature investment. Engineering focus stays on the auth-team OAuth completion + Lambda deploy path.
- Scale tripwire in ADR-0022 is now explicitly scoped to cover F3/F6 as well.

Negative
- Two known architectural debts sit on the ADR list. If we ship paid provider analytics before the tripwire fires, they will block.
- `dashboard_service` N+1 pattern is documented but not enforced; a careless new view read could push p95 over the tripwire without the team noticing.

## Follow-ups

- **Monitoring**: add a weekly cron job that runs `EXPLAIN ANALYZE` on `provider_tool_dashboard` with realistic filters, logs p95; alert when > 150ms (early-warning threshold for the 200ms tripwire).
- **F6 pre-work**: next time we add a column to `query_logs` or `execution_logs`, include `provider_id` snapshot in the same migration. Defers the backfill cost.
- **Auth handoff gate**: before merging the 029 / 030 drops, the auth team re-checks dashboard latency to make sure refs-only resolution did not add hidden N+1.
