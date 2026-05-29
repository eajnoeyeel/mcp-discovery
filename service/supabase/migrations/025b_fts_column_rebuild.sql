-- ============================================================
-- Migration 025b: FTS column rebuild (L1)
-- ============================================================
-- Before: fts generated from tool_name + description only
-- (migration 001). After 020/021 added parameter_notes and
-- usage_hints, those fields were NOT in FTS — recall loss on
-- parameter-heavy queries.
--
-- Fix: shadow-column rename-swap pattern. Include all four text
-- fields in the new tsvector.
--
-- Note: PostgreSQL rejects subqueries in GENERATED expressions
-- (ERROR 0A000). usage_hints (JSONB) is flattened via `::text`
-- cast — the english tsvector parser ignores brackets/quotes so
-- the array elements index correctly without a subquery.
--
-- At current scale (~3k rows) CREATE INDEX is sub-second so the
-- CONCURRENTLY directive and its disable-transaction requirement
-- are not needed. Migration runs in a normal transaction.
--
-- Depends on: 001_initial.sql (mcp_tools.fts, idx_mcp_tools_fts),
--             020a_http_mcp_metadata_overrides.sql (parameter_notes,
--             usage_hints)
-- ============================================================

ALTER TABLE mcp_tools
    ADD COLUMN IF NOT EXISTS fts_v2 TSVECTOR
        GENERATED ALWAYS AS (
            to_tsvector(
                'english',
                coalesce(tool_name,       '') || ' ' ||
                coalesce(description,     '') || ' ' ||
                coalesce(parameter_notes, '') || ' ' ||
                coalesce(usage_hints::text, '')
            )
        ) STORED;

CREATE INDEX IF NOT EXISTS idx_mcp_tools_fts_v2
    ON mcp_tools USING GIN (fts_v2);

ALTER TABLE mcp_tools
    DROP COLUMN IF EXISTS fts CASCADE;

ALTER TABLE mcp_tools
    RENAME COLUMN fts_v2 TO fts;

ALTER INDEX IF EXISTS idx_mcp_tools_fts_v2
    RENAME TO idx_mcp_tools_fts;
