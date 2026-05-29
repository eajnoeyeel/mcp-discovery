-- Rollback for 033_mcp_tools_retry_count.sql
-- Safe to run iff no rows currently hold index_status='failed_permanent'.
--
-- Pre-check:
--   SELECT COUNT(*) FROM mcp_tools WHERE index_status = 'failed_permanent';
-- If count > 0, migrate those rows to 'failed' first before dropping the state.

DROP FUNCTION IF EXISTS increment_retry_and_reset_to_pending(text[]);

ALTER TABLE mcp_tools
  DROP CONSTRAINT IF EXISTS mcp_tools_index_status_check;

ALTER TABLE mcp_tools
  ADD CONSTRAINT mcp_tools_index_status_check
  CHECK (index_status IN (
    'pending',
    'indexing',
    'indexed',
    'failed',
    'event_failed',
    'deprecated',
    'unreachable',
    'quarantined'
  ));

ALTER TABLE mcp_tools
  DROP COLUMN IF EXISTS retry_count;
