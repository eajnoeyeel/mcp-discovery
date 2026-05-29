-- ADR-adjacent: close the register → index_replay retry contract at the DB layer.
--
-- service/lambdas/register/handler.py:404 writes `index_status='event_failed'`
-- when EventBridge publish fails, so service/lambdas/index_replay/handler.py
-- can later flip those rows back to 'pending' and retry.
--
-- Migration 007 (entity lifecycle) introduced the CHECK constraint but omitted
-- `event_failed` from the allowed set. Until now, the register handler's
-- event_failed writes hit a CHECK violation that was silently swallowed by a
-- try/except (register/handler.py:408), leaving the replay path with no rows
-- to consume on EventBridge outage. This migration closes the gap.
--
-- Safe to run on envs where `event_failed` was previously rejected: existing
-- rows that were rejected by the old CHECK were never persisted, so no
-- backfill is required.

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

COMMENT ON CONSTRAINT mcp_tools_index_status_check ON mcp_tools IS
  'Lifecycle states per docs/design/status-lifecycle.md + event_failed for '
  'the EventBridge-publish retry contract (register/handler -> index_replay).';
