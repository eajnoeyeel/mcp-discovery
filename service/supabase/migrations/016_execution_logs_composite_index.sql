-- Migration 016: Composite index on execution_logs for per-tool time-range queries
-- Supports efficient lookups of execution history for a specific tool within a date range
-- (e.g., provider dashboard drill-down: "show tool X's executions in the last 7 days").
-- Forward-only migration.

CREATE INDEX IF NOT EXISTS idx_execution_logs_tool_id_created_at
    ON execution_logs (tool_id, created_at);
