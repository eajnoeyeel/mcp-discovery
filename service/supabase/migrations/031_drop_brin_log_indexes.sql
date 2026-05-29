-- ============================================================
-- Migration 031: Drop BRIN log indexes (F8 — 2026-04-20 audit)
-- ============================================================
-- BRIN + B-tree on the same column is redundant write amplification.
-- execution_logs.created_at and query_logs.created_at already have
-- B-tree indexes from migration 001 (idx_execution_logs_created_at,
-- idx_query_logs_created_at). BRIN was added preemptively in
-- migration 026 for future append-only scale, but at current size
-- (~300 rows per table) BRIN buys nothing over the existing B-trees.
--
-- Drop BRIN. B-trees remain and continue to serve range scans.
-- Revisit BRIN when either log table crosses ~100K rows.
--
-- Depends on: 026_brin_log_indexes.sql
-- ============================================================

DROP INDEX IF EXISTS brin_execution_logs_created_at;
DROP INDEX IF EXISTS brin_query_logs_created_at;
