-- ============================================================
-- Migration 015: Expand mcp_servers.index_status constraint
-- ============================================================
-- Preemptive alignment: mcp_tools.index_status was expanded to
-- 7 values in migration 007, but mcp_servers was left at the
-- original 3 values from 001. This closes the asymmetry to
-- prevent CHECK violations if entity lifecycle is extended.
--
-- Depends on: 001_initial.sql (mcp_servers)
-- ============================================================

ALTER TABLE mcp_servers
    DROP CONSTRAINT IF EXISTS mcp_servers_index_status_check;

ALTER TABLE mcp_servers
    ADD CONSTRAINT mcp_servers_index_status_check
    CHECK (index_status IN (
        'pending', 'indexing', 'indexed', 'failed',
        'deprecated', 'unreachable', 'quarantined'
    )) NOT VALID;

ALTER TABLE mcp_servers
    VALIDATE CONSTRAINT mcp_servers_index_status_check;
