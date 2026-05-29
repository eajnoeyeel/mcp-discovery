-- ============================================================
-- Migration 034: Enforce Deterministic MCP Auth Requirements
-- ============================================================
-- The runtime resolves a single effective delegated auth requirement
-- per tool: exact tool row first, then a server-level fallback row.
-- Duplicate rows make that resolution nondeterministic.
-- ============================================================

BEGIN;

WITH ranked_tool_rows AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY tool_id
            ORDER BY updated_at DESC, created_at DESC, id DESC
        ) AS row_rank
    FROM mcp_auth_requirements
    WHERE tool_id IS NOT NULL
)
DELETE FROM mcp_auth_requirements
WHERE id IN (
    SELECT id
    FROM ranked_tool_rows
    WHERE row_rank > 1
);

WITH ranked_server_defaults AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY server_id
            ORDER BY updated_at DESC, created_at DESC, id DESC
        ) AS row_rank
    FROM mcp_auth_requirements
    WHERE tool_id IS NULL
)
DELETE FROM mcp_auth_requirements
WHERE id IN (
    SELECT id
    FROM ranked_server_defaults
    WHERE row_rank > 1
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_auth_requirements_tool_id
    ON mcp_auth_requirements(tool_id)
    WHERE tool_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_auth_requirements_server_default
    ON mcp_auth_requirements(server_id)
    WHERE tool_id IS NULL;

COMMIT;
