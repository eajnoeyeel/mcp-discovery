-- ADR-0024: event-driven DLQ retry with substrate-independent circuit breaker.
--
-- Adds `retry_count` so the DLQ consumer can enforce a poison-pill circuit
-- breaker across SQS→EventBridge republish hops (SQS ApproximateReceiveCount
-- resets on republish; we need a DB-level counter instead).
--
-- Adds `failed_permanent` to the CHECK constraint as the terminal state once
-- `retry_count >= MAX_RETRY_COUNT`. Tools in this state are surfaced via
-- CloudWatch TerminalFailures metric and require manual triage.
--
-- Adds `increment_retry_and_reset_to_pending(text[])` RPC because PostgREST
-- cannot express `retry_count = retry_count + 1` atomically in a PATCH body.

ALTER TABLE mcp_tools
  ADD COLUMN IF NOT EXISTS retry_count integer NOT NULL DEFAULT 0;

COMMENT ON COLUMN mcp_tools.retry_count IS
  'DLQ republish attempts by index_dlq_consumer. When >= MAX_RETRY_COUNT the '
  'tool transitions to failed_permanent (terminal, requires manual triage).';

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
    'failed_permanent',
    'deprecated',
    'unreachable',
    'quarantined'
  ));

COMMENT ON CONSTRAINT mcp_tools_index_status_check ON mcp_tools IS
  'Lifecycle states per docs/design/status-lifecycle.md + event_failed (register '
  '-> index_replay retry contract) + failed_permanent (DLQ retry exhaustion).';

CREATE OR REPLACE FUNCTION increment_retry_and_reset_to_pending(p_tool_ids text[])
RETURNS TABLE(tool_id text, retry_count integer)
LANGUAGE sql
AS $$
  UPDATE mcp_tools
  SET retry_count = mcp_tools.retry_count + 1,
      index_status = 'pending',
      updated_at = now()
  WHERE mcp_tools.tool_id = ANY(p_tool_ids)
    AND mcp_tools.index_status = 'failed'
  RETURNING mcp_tools.tool_id, mcp_tools.retry_count;
$$;

COMMENT ON FUNCTION increment_retry_and_reset_to_pending(text[]) IS
  'Atomic increment + state flip for DLQ republish. Guards by index_status=failed '
  'so concurrent DLQ messages for the same tool cannot double-increment.';
