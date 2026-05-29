-- ============================================================
-- Migration 035: Atomic MCP Auth Requirement Replacement RPC
-- ============================================================
-- Re-registration must not expose a delete-before-insert window for
-- delegated client auth.  This RPC swaps all auth requirements for one
-- server inside a single database transaction; any validation/insert
-- failure rolls the delete back with the rest of the function call.
-- ============================================================

CREATE OR REPLACE FUNCTION public.replace_mcp_auth_requirements(
    p_server_id TEXT,
    p_requirements JSONB DEFAULT '[]'::jsonb
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_requirements JSONB := COALESCE(p_requirements, '[]'::jsonb);
    v_result JSONB := '[]'::jsonb;
BEGIN
    IF p_server_id IS NULL OR btrim(p_server_id) = '' THEN
        RAISE EXCEPTION 'p_server_id is required';
    END IF;

    IF jsonb_typeof(v_requirements) <> 'array' THEN
        RAISE EXCEPTION 'p_requirements must be a JSON array';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(v_requirements) AS requirement(row)
        WHERE requirement.row->>'server_id' IS DISTINCT FROM p_server_id
    ) THEN
        RAISE EXCEPTION 'all auth requirement rows must match p_server_id';
    END IF;

    DELETE FROM public.mcp_auth_requirements
    WHERE server_id = p_server_id;

    WITH inserted AS (
        INSERT INTO public.mcp_auth_requirements (
            server_id,
            tool_id,
            provider_key,
            auth_kind,
            required_scopes,
            scope_mode
        )
        SELECT
            p_server_id,
            NULLIF(requirement.row->>'tool_id', ''),
            requirement.row->>'provider_key',
            COALESCE(NULLIF(requirement.row->>'auth_kind', ''), 'oauth'),
            COALESCE(requirement.row->'required_scopes', '[]'::jsonb),
            COALESCE(NULLIF(requirement.row->>'scope_mode', ''), 'default')
        FROM jsonb_array_elements(v_requirements) AS requirement(row)
        RETURNING server_id, tool_id, provider_key, auth_kind, required_scopes, scope_mode
    )
    SELECT COALESCE(jsonb_agg(to_jsonb(inserted)), '[]'::jsonb)
    INTO v_result
    FROM inserted;

    RETURN v_result;
END;
$$;

REVOKE ALL ON FUNCTION public.replace_mcp_auth_requirements(TEXT, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.replace_mcp_auth_requirements(TEXT, JSONB) TO service_role;
