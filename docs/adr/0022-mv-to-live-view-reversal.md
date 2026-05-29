# ADR-0022: MV-to-Live-View Reversal — Analytics Precomputed Read Model

**Date**: 2026-04-19
**Status**: accepted
**Deciders**: schema-audit-fixes team

## Context

Migrations 011 and 012 built the original precomputed read model: 8 materialized views (MVs) plus a `refresh_operational_stats()` function invoked by pg_cron every 5 minutes. This satisfied P2 (Precomputed Reads) and kept the dashboard hot path free of raw aggregation.

Migrations `020_mv_to_view.sql` and `021_analytics_views_fix.sql` reversed that design: the MVs were dropped and replaced with regular VIEWs, and `refresh_operational_stats()` was effectively no-opped (the function body was left in place but the VIEWs it attempted to `REFRESH MATERIALIZED VIEW` no longer exist as MVs). No ADR was written at the time explaining the reversal.

The reversal contradicts `docs/design/serverless-architecture-principles.md` P1 ("hot path must not depend on raw aggregation") and P2 ("all analytics are precomputed in materialized views"). At the time of the reversal, dashboard volume was well under 10K events/day; pg_cron was masking intermittent refresh failures silently (no alerting on `cron.job_run_details`), and the operational overhead of maintaining MV indexes during low-volume development outweighed the aggregation cost.

PR#73 (hybrid dense+sparse RRF, R@3=46.8%) is the current pre-migration E2E anchor. All dashboard reads validated against the post-020/021 live-VIEW schema.

## Decision

Accept live VIEWs at current development scale (<10K events/day) where dashboard aggregation cost is negligible and the pg_cron failure surface is a net negative. Restore MVs and pg_cron when the scale tripwire is hit.

**Scale tripwire (restoration trigger — either condition)**:
- Dashboard p95 latency > 200ms (measured at the `provider_tool_dashboard` or funnel view query level), OR
- `execution_logs` row count > 500,000

When the tripwire is hit, apply the restoration SQL below.

## Restoration SQL

```sql
-- Step 1: Recreate MVs (run inside a transaction where possible)

CREATE MATERIALIZED VIEW tool_operational_stats AS
SELECT
    tool_id,
    COUNT(*) FILTER (WHERE status = 'success') AS success_count,
    COUNT(*) FILTER (WHERE status = 'error')   AS error_count,
    COUNT(*)                                   AS total_count,
    AVG(latency_ms)                            AS avg_latency_ms,
    now()                                      AS refreshed_at
FROM execution_logs
GROUP BY tool_id
WITH DATA;

CREATE UNIQUE INDEX ON tool_operational_stats (tool_id);

CREATE MATERIALIZED VIEW tool_operational_stats_7d AS
SELECT
    tool_id,
    COUNT(*) FILTER (WHERE status = 'success') AS success_count,
    COUNT(*) FILTER (WHERE status = 'error')   AS error_count,
    COUNT(*)                                   AS total_count,
    AVG(latency_ms)                            AS avg_latency_ms,
    now()                                      AS refreshed_at
FROM execution_logs
WHERE created_at >= now() - interval '7 days'
GROUP BY tool_id
WITH DATA;

CREATE UNIQUE INDEX ON tool_operational_stats_7d (tool_id);

CREATE MATERIALIZED VIEW tool_selection_stats AS
SELECT
    recommended_tool_id AS tool_id,
    COUNT(*) AS selection_count,
    now()    AS refreshed_at
FROM query_logs
WHERE recommended_tool_id IS NOT NULL
GROUP BY recommended_tool_id
WITH DATA;

CREATE UNIQUE INDEX ON tool_selection_stats (tool_id);

CREATE MATERIALIZED VIEW tool_exposure_stats AS
SELECT
    tool_id,
    COUNT(*) AS exposure_count,
    now()    AS refreshed_at
FROM tool_exposure_facts
GROUP BY tool_id
WITH DATA;

CREATE UNIQUE INDEX ON tool_exposure_stats (tool_id);

CREATE MATERIALIZED VIEW tool_exposure_stats_7d AS
SELECT
    tool_id,
    COUNT(*) AS exposure_count,
    now()    AS refreshed_at
FROM tool_exposure_facts
WHERE created_at >= now() - interval '7 days'
GROUP BY tool_id
WITH DATA;

CREATE UNIQUE INDEX ON tool_exposure_stats_7d (tool_id);

CREATE MATERIALIZED VIEW tool_daily_stats AS
SELECT
    tool_id,
    date_trunc('day', created_at) AS day,
    COUNT(*) AS call_count,
    now()    AS refreshed_at
FROM execution_logs
GROUP BY tool_id, date_trunc('day', created_at)
WITH DATA;

CREATE UNIQUE INDEX ON tool_daily_stats (tool_id, day);

CREATE MATERIALIZED VIEW tool_client_stats AS
SELECT
    tool_id,
    client_id,
    COUNT(*) AS call_count,
    now()    AS refreshed_at
FROM execution_logs
WHERE client_id IS NOT NULL
GROUP BY tool_id, client_id
WITH DATA;

CREATE UNIQUE INDEX ON tool_client_stats (tool_id, client_id);

CREATE MATERIALIZED VIEW tool_client_selection_stats AS
SELECT
    recommended_tool_id AS tool_id,
    client_id,
    COUNT(*) AS selection_count,
    now()    AS refreshed_at
FROM query_logs
WHERE recommended_tool_id IS NOT NULL AND client_id IS NOT NULL
GROUP BY recommended_tool_id, client_id
WITH DATA;

CREATE UNIQUE INDEX ON tool_client_selection_stats (tool_id, client_id);

-- Step 2: Restore refresh_operational_stats() to invoke REFRESH on all 8 MVs

CREATE OR REPLACE FUNCTION refresh_operational_stats()
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_mv TEXT;
    v_mvs TEXT[] := ARRAY[
        'tool_operational_stats',
        'tool_operational_stats_7d',
        'tool_selection_stats',
        'tool_exposure_stats',
        'tool_exposure_stats_7d',
        'tool_daily_stats',
        'tool_client_stats',
        'tool_client_selection_stats'
    ];
BEGIN
    FOREACH v_mv IN ARRAY v_mvs LOOP
        BEGIN
            EXECUTE format('REFRESH MATERIALIZED VIEW CONCURRENTLY %I', v_mv);
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'refresh_operational_stats: failed to refresh % — %', v_mv, SQLERRM;
        END;
    END LOOP;
END;
$$;

-- Step 3: Re-register pg_cron job (if dropped)
SELECT cron.schedule(
    'refresh-operational-stats',
    '*/5 * * * *',
    'SELECT refresh_operational_stats()'
);

-- Step 4: Drop the live VIEWs that replaced the MVs (after confirming MV data is populated)
-- DROP VIEW IF EXISTS tool_operational_stats CASCADE;
-- (repeat for each view that was created by 020/021 to replace an MV)
```

## Alternatives Considered

### Alternative 1: Revert 020/021 immediately and restore MVs now
- **Pros**: Restores P2 compliance; eliminates H4 audit finding
- **Cons**: At <10K events/day the aggregation cost is immeasurable; introducing pg_cron back at development scale re-exposes the silent-failure surface that motivated 020/021
- **Why not**: The scale tripwire approach defers the complexity to the point where it actually matters

### Alternative 2: Keep live VIEWs permanently and remove P2 from the principles doc
- **Pros**: Simpler; no future migration needed
- **Cons**: P2 is load-bearing for production scalability; removing it would require re-evaluating P1 and the entire control-plane architecture
- **Why not**: P2 is correct at scale; the deviation is tactical, not strategic

## Consequences

### Positive
- Dashboard aggregation is simple and correct at current volume
- No pg_cron silent-failure surface during development
- Restoration SQL is documented and ready to apply when the tripwire is hit

### Negative
- Live VIEWs violate P1 and P2 as written — formally accepted as a time-limited deviation
- `refresh_operational_stats()` is a no-op in the current schema state (function exists but refreshes non-existent MVs); any caller that checks cron.job_run_details will see failures
- No automated alerting on the tripwire conditions (p95 latency, row count) — operators must monitor manually until observability is wired up

### Risks
- If dashboard is accidentally used in a query-plane (hot) path before the MV restoration, p95 latency will spike with no prior warning — mitigated by architecture review gate before any query-plane dashboard integration

## Follow-ups

- Wire `cron.job_run_details` monitoring to alert on `refresh_operational_stats` failures (currently produces `RAISE WARNING` that goes to PostgreSQL logs only)
- Add row-count metric on `execution_logs` to Grafana/observability dashboard to automate tripwire detection
- When tripwire is hit: apply restoration SQL above as migration 030 (or next available number), then drop the live VIEWs
