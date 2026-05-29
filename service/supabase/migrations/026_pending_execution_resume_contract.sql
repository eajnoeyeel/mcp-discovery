-- ============================================================
-- Migration 026: Pending Execution Resume Contract
-- ============================================================
-- Brings existing pending_executions tables in line with the
-- delegated OAuth resume implementation. Safe to run after 025.
-- ============================================================

ALTER TABLE pending_executions
    ADD COLUMN IF NOT EXISTS connection_id UUID
        REFERENCES user_provider_connections(id)
        ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS result_json JSONB,
    ADD COLUMN IF NOT EXISTS error_message TEXT;

ALTER TABLE pending_executions
    DROP CONSTRAINT IF EXISTS pending_executions_status_check;

ALTER TABLE pending_executions
    ALTER COLUMN status SET DEFAULT 'waiting_for_connect';

UPDATE pending_executions
SET status = 'waiting_for_connect'
WHERE status IN ('pending', 'consumed');

ALTER TABLE pending_executions
    ADD CONSTRAINT pending_executions_status_check
    CHECK (status IN (
        'waiting_for_connect',
        'ready_to_resume',
        'resuming',
        'resumed',
        'failed',
        'expired'
    ));
