-- ============================================================
-- Migration 025c: Auto-provision provider on user signup
-- ============================================================
-- Currently a providers row must be created manually (or via
-- migration 012 backfill). New users who register via the
-- Supabase Auth flow have no providers row, so provider-scoped
-- dashboard queries return empty results until an operator
-- inserts the row.
--
-- This migration attaches a trigger to auth.users (Supabase's
-- internal user table) so that every new signup automatically
-- receives a providers row. SECURITY DEFINER + search_path=''
-- prevents privilege escalation from the trigger context.
--
-- Depends on: 012_provider_dashboard.sql (providers table)
-- ============================================================

BEGIN;

CREATE OR REPLACE FUNCTION auto_provision_provider()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    INSERT INTO public.providers (user_id)
    VALUES (NEW.id)
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION auto_provision_provider() IS
    'Trigger function: creates a providers row for every new auth.users '
    'signup. ON CONFLICT DO NOTHING is idempotent against manual backfills.';

DROP TRIGGER IF EXISTS trg_auto_provision_provider ON auth.users;

CREATE TRIGGER trg_auto_provision_provider
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION auto_provision_provider();

COMMIT;
