-- ============================================================
-- Migration 036: OAuth Provider Bootstrap Automation
-- ============================================================
-- Adds draft-vs-active provider OAuth bootstrap state, active registry
-- metadata needed for Discovery/DCR/manual OAuth clients, and mandatory
-- OAuth state replay protection primitives.
-- ============================================================

ALTER TABLE oauth_provider_registry
    ADD COLUMN IF NOT EXISTS issuer TEXT,
    ADD COLUMN IF NOT EXISTS metadata_url TEXT,
    ADD COLUMN IF NOT EXISTS protected_resource_metadata_url TEXT,
    ADD COLUMN IF NOT EXISTS registration_endpoint TEXT,
    ADD COLUMN IF NOT EXISTS client_secret_ref TEXT,
    ADD COLUMN IF NOT EXISTS token_endpoint_auth_method TEXT NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS scopes_supported JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS grant_types_supported JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS response_types_supported JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS code_challenge_methods_supported JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS bootstrap_mode TEXT NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS bootstrap_status TEXT NOT NULL DEFAULT 'enabled',
    ADD COLUMN IF NOT EXISTS bootstrap_diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_discovered_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'oauth_provider_registry_token_auth_method_check'
    ) THEN
        ALTER TABLE oauth_provider_registry
            ADD CONSTRAINT oauth_provider_registry_token_auth_method_check
            CHECK (token_endpoint_auth_method IN ('none', 'client_secret_post', 'client_secret_basic'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'oauth_provider_registry_bootstrap_mode_check'
    ) THEN
        ALTER TABLE oauth_provider_registry
            ADD CONSTRAINT oauth_provider_registry_bootstrap_mode_check
            CHECK (bootstrap_mode IN ('manual', 'discovery', 'dcr'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'oauth_provider_registry_bootstrap_status_check'
    ) THEN
        ALTER TABLE oauth_provider_registry
            ADD CONSTRAINT oauth_provider_registry_bootstrap_status_check
            CHECK (bootstrap_status IN ('draft', 'validated', 'enabled', 'failed', 'disabled'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'oauth_provider_registry_enabled_status_check'
    ) THEN
        ALTER TABLE oauth_provider_registry
            ADD CONSTRAINT oauth_provider_registry_enabled_status_check
            CHECK (enabled IS FALSE OR bootstrap_status = 'enabled');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS oauth_provider_bootstrap_drafts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider_key       TEXT NOT NULL,
    bootstrap_mode     TEXT NOT NULL CHECK (bootstrap_mode IN ('manual', 'discovery', 'dcr')),
    status             TEXT NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft', 'validated', 'enabled', 'failed', 'disabled', 'promoted')),
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
    diagnostics        JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key    TEXT,
    promoted_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_user_id, idempotency_key)
);

DROP TRIGGER IF EXISTS set_oauth_provider_bootstrap_drafts_updated_at ON oauth_provider_bootstrap_drafts;
CREATE TRIGGER set_oauth_provider_bootstrap_drafts_updated_at
    BEFORE UPDATE ON oauth_provider_bootstrap_drafts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

ALTER TABLE oauth_provider_bootstrap_drafts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users_manage_own_oauth_provider_bootstrap_drafts" ON oauth_provider_bootstrap_drafts;
CREATE POLICY "Users_manage_own_oauth_provider_bootstrap_drafts"
    ON oauth_provider_bootstrap_drafts FOR ALL
    TO authenticated
    USING ((select auth.uid()) = owner_user_id)
    WITH CHECK ((select auth.uid()) = owner_user_id);

DROP POLICY IF EXISTS "service_role_all_oauth_provider_bootstrap_drafts" ON oauth_provider_bootstrap_drafts;
CREATE POLICY "service_role_all_oauth_provider_bootstrap_drafts"
    ON oauth_provider_bootstrap_drafts FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_oauth_provider_bootstrap_drafts_owner_status
    ON oauth_provider_bootstrap_drafts(owner_user_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_oauth_provider_bootstrap_drafts_provider_key
    ON oauth_provider_bootstrap_drafts(provider_key);

CREATE TABLE IF NOT EXISTS oauth_state_nonces (
    nonce_hash       TEXT PRIMARY KEY,
    code_verifier    TEXT,
    required_scopes  JSONB NOT NULL DEFAULT '[]'::jsonb,
    user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider_key     TEXT NOT NULL REFERENCES oauth_provider_registry(provider_key) ON DELETE CASCADE,
    issuer           TEXT,
    redirect_uri     TEXT NOT NULL,
    tool_id          TEXT NOT NULL,
    pending_execution_id UUID,
    expires_at       TIMESTAMPTZ NOT NULL,
    consumed_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE oauth_state_nonces
    ADD COLUMN IF NOT EXISTS code_verifier TEXT;

ALTER TABLE oauth_state_nonces
    ADD COLUMN IF NOT EXISTS required_scopes JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE oauth_state_nonces ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_oauth_state_nonces" ON oauth_state_nonces;
CREATE POLICY "service_role_all_oauth_state_nonces"
    ON oauth_state_nonces FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_oauth_state_nonces_user_provider
    ON oauth_state_nonces(user_id, provider_key, expires_at DESC);

CREATE OR REPLACE FUNCTION public.promote_oauth_provider_bootstrap_draft(
    p_draft_id UUID,
    p_owner_user_id UUID
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_draft oauth_provider_bootstrap_drafts%ROWTYPE;
    v_meta JSONB;
    v_result JSONB;
BEGIN
    SELECT * INTO v_draft
    FROM public.oauth_provider_bootstrap_drafts
    WHERE id = p_draft_id
      AND owner_user_id = p_owner_user_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'OAuth provider bootstrap draft not found';
    END IF;

    IF v_draft.status NOT IN ('validated', 'enabled') THEN
        RAISE EXCEPTION 'OAuth provider bootstrap draft is not validated';
    END IF;

    v_meta := v_draft.metadata;

    IF COALESCE(v_meta->>'provider_key', '') = ''
       OR COALESCE(v_meta->>'authorize_url', '') = ''
       OR COALESCE(v_meta->>'token_url', '') = ''
       OR COALESCE(v_meta->>'client_id', '') = ''
       OR COALESCE(v_meta->>'redirect_uri', '') = '' THEN
        RAISE EXCEPTION 'OAuth provider bootstrap draft is missing required metadata';
    END IF;

    IF COALESCE(v_meta->>'token_endpoint_auth_method', 'none') IN ('client_secret_post', 'client_secret_basic')
       AND COALESCE(v_meta->>'client_secret_ref', '') = '' THEN
        RAISE EXCEPTION 'OAuth provider bootstrap draft is missing client_secret_ref';
    END IF;

    INSERT INTO public.oauth_provider_registry (
        provider_key,
        display_name,
        authorize_url,
        token_url,
        client_id,
        redirect_uri,
        default_scopes,
        scope_aliases,
        supports_refresh_token,
        pkce_required,
        enabled,
        metadata,
        issuer,
        metadata_url,
        protected_resource_metadata_url,
        registration_endpoint,
        client_secret_ref,
        token_endpoint_auth_method,
        scopes_supported,
        grant_types_supported,
        response_types_supported,
        code_challenge_methods_supported,
        bootstrap_mode,
        bootstrap_status,
        bootstrap_diagnostics,
        last_discovered_at
    ) VALUES (
        v_meta->>'provider_key',
        COALESCE(NULLIF(v_meta->>'display_name', ''), v_meta->>'provider_key'),
        v_meta->>'authorize_url',
        v_meta->>'token_url',
        v_meta->>'client_id',
        v_meta->>'redirect_uri',
        COALESCE(v_meta->'default_scopes', '[]'::jsonb),
        COALESCE(v_meta->'scope_aliases', '{}'::jsonb),
        COALESCE((v_meta->>'supports_refresh_token')::boolean, false),
        COALESCE((v_meta->>'pkce_required')::boolean, true),
        true,
        COALESCE(v_meta->'metadata', '{}'::jsonb),
        NULLIF(v_meta->>'issuer', ''),
        NULLIF(v_meta->>'metadata_url', ''),
        NULLIF(v_meta->>'protected_resource_metadata_url', ''),
        NULLIF(v_meta->>'registration_endpoint', ''),
        NULLIF(v_meta->>'client_secret_ref', ''),
        COALESCE(NULLIF(v_meta->>'token_endpoint_auth_method', ''), 'none'),
        COALESCE(v_meta->'scopes_supported', '[]'::jsonb),
        COALESCE(v_meta->'grant_types_supported', '[]'::jsonb),
        COALESCE(v_meta->'response_types_supported', '[]'::jsonb),
        COALESCE(v_meta->'code_challenge_methods_supported', '[]'::jsonb),
        COALESCE(NULLIF(v_meta->>'bootstrap_mode', ''), v_draft.bootstrap_mode),
        'enabled',
        COALESCE(v_draft.diagnostics, '{}'::jsonb),
        now()
    )
    ON CONFLICT (provider_key) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        authorize_url = EXCLUDED.authorize_url,
        token_url = EXCLUDED.token_url,
        client_id = EXCLUDED.client_id,
        redirect_uri = EXCLUDED.redirect_uri,
        default_scopes = EXCLUDED.default_scopes,
        scope_aliases = EXCLUDED.scope_aliases,
        supports_refresh_token = EXCLUDED.supports_refresh_token,
        pkce_required = EXCLUDED.pkce_required,
        enabled = true,
        metadata = EXCLUDED.metadata,
        issuer = EXCLUDED.issuer,
        metadata_url = EXCLUDED.metadata_url,
        protected_resource_metadata_url = EXCLUDED.protected_resource_metadata_url,
        registration_endpoint = EXCLUDED.registration_endpoint,
        client_secret_ref = EXCLUDED.client_secret_ref,
        token_endpoint_auth_method = EXCLUDED.token_endpoint_auth_method,
        scopes_supported = EXCLUDED.scopes_supported,
        grant_types_supported = EXCLUDED.grant_types_supported,
        response_types_supported = EXCLUDED.response_types_supported,
        code_challenge_methods_supported = EXCLUDED.code_challenge_methods_supported,
        bootstrap_mode = EXCLUDED.bootstrap_mode,
        bootstrap_status = 'enabled',
        bootstrap_diagnostics = EXCLUDED.bootstrap_diagnostics,
        last_discovered_at = EXCLUDED.last_discovered_at,
        updated_at = now()
    RETURNING to_jsonb(oauth_provider_registry.*) INTO v_result;

    UPDATE public.oauth_provider_bootstrap_drafts
    SET status = 'promoted', promoted_at = now()
    WHERE id = p_draft_id;

    RETURN v_result;
END;
$$;

REVOKE ALL ON FUNCTION public.promote_oauth_provider_bootstrap_draft(UUID, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.promote_oauth_provider_bootstrap_draft(UUID, UUID) TO service_role;

CREATE OR REPLACE FUNCTION public.consume_oauth_state_nonce(
    p_nonce_hash TEXT,
    p_provider_key TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_nonce oauth_state_nonces%ROWTYPE;
BEGIN
    SELECT * INTO v_nonce
    FROM public.oauth_state_nonces
    WHERE nonce_hash = p_nonce_hash
      AND provider_key = p_provider_key
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'OAuth state nonce not found';
    END IF;

    IF v_nonce.consumed_at IS NOT NULL THEN
        RAISE EXCEPTION 'OAuth state nonce already consumed';
    END IF;

    IF v_nonce.expires_at <= now() THEN
        RAISE EXCEPTION 'OAuth state nonce expired';
    END IF;

    UPDATE public.oauth_state_nonces
    SET consumed_at = now()
    WHERE nonce_hash = p_nonce_hash;

    RETURN to_jsonb(v_nonce);
END;
$$;

REVOKE ALL ON FUNCTION public.consume_oauth_state_nonce(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.consume_oauth_state_nonce(TEXT, TEXT) TO service_role;
