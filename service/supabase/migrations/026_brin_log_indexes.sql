-- supabase:disable-transaction
-- ============================================================
-- Migration 026: BRIN indexes on log table created_at columns
-- ============================================================
-- execution_logs and query_logs grow unboundedly. Time-range
-- scans (dashboard charts, purge jobs, audit queries) use the
-- created_at column. A GIN/BTree index on an append-only log
-- table wastes write amplification; BRIN is the correct choice:
-- ~128 bytes per 128-page range vs. full BTree overhead.
--
-- pages_per_range=32 (~256 KB per range at default 8 KB pages)
-- balances range granularity vs. index size. Tune upward if
-- table reaches billions of rows and scan speed degrades.
--
-- CONCURRENTLY requires being outside a transaction block
-- (hence supabase:disable-transaction). IF NOT EXISTS makes
-- this re-runnable without error.
--
-- Depends on: 001_initial.sql (execution_logs, query_logs)
-- ============================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS brin_execution_logs_created_at
    ON execution_logs
    USING BRIN (created_at)
    WITH (pages_per_range = 32);

CREATE INDEX CONCURRENTLY IF NOT EXISTS brin_query_logs_created_at
    ON query_logs
    USING BRIN (created_at)
    WITH (pages_per_range = 32);
