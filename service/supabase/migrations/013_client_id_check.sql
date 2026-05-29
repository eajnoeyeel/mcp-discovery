-- ============================================================
-- Migration 013: Client ID format constraint
-- ============================================================
-- Enforces lowercase alphanumeric + dot/dash/underscore format
-- on client_id columns in log tables. Prevents garbage data from
-- corrupting per-client materialized view aggregations.
--
-- Uses NOT VALID + VALIDATE pattern for zero-downtime application.
-- Depends on: 012_provider_dashboard.sql (client_id column addition)
-- ============================================================

ALTER TABLE execution_logs
    ADD CONSTRAINT chk_execution_logs_client_id
    CHECK (client_id ~ '^[a-z][a-z0-9._-]{1,63}$') NOT VALID;

ALTER TABLE execution_logs
    VALIDATE CONSTRAINT chk_execution_logs_client_id;

ALTER TABLE query_logs
    ADD CONSTRAINT chk_query_logs_client_id
    CHECK (client_id ~ '^[a-z][a-z0-9._-]{1,63}$') NOT VALID;

ALTER TABLE query_logs
    VALIDATE CONSTRAINT chk_query_logs_client_id;
