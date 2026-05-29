-- ============================================================
-- MCP Discovery Platform — Initial Schema Migration
-- ============================================================
-- Creates the core tables for the MLP service layer:
--   mcp_servers      — registered MCP server metadata
--   mcp_tools        — individual tools belonging to servers
--   query_logs       — search query audit trail
--   execution_logs   — tool execution audit trail
-- ============================================================

-- ---------- Extensions ----------

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()

-- ============================================================
-- 1. mcp_servers
-- ============================================================

CREATE TABLE mcp_servers (
    id            UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    server_id     TEXT         UNIQUE NOT NULL,
    name          TEXT         NOT NULL,
    description   TEXT,
    url           TEXT,
    tags          TEXT[],
    index_status  TEXT         DEFAULT 'pending'
                               CHECK (index_status IN ('pending', 'indexed', 'failed')),
    created_at    TIMESTAMPTZ  DEFAULT now(),
    updated_at    TIMESTAMPTZ  DEFAULT now()
);

-- ============================================================
-- 2. mcp_tools
-- ============================================================

CREATE TABLE mcp_tools (
    id            UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    tool_id       TEXT         UNIQUE NOT NULL,          -- format: server_id::tool_name
    server_id     TEXT         NOT NULL
                               REFERENCES mcp_servers(server_id),
    tool_name     TEXT         NOT NULL,
    description   TEXT,
    input_schema  JSONB,
    geo_score     JSONB,                                 -- {clarity, disambiguation, parameter_coverage, boundary, stats, precision, total}
    index_status  TEXT         DEFAULT 'pending'
                               CHECK (index_status IN ('pending', 'indexed', 'failed')),
    created_at    TIMESTAMPTZ  DEFAULT now(),

    -- Full-text search: auto-generated tsvector from tool_name + description
    fts           TSVECTOR    GENERATED ALWAYS AS (
                      to_tsvector('english', coalesce(tool_name, '') || ' ' || coalesce(description, ''))
                  ) STORED
);

-- ============================================================
-- 3. query_logs
-- ============================================================

CREATE TABLE query_logs (
    id              BIGSERIAL    PRIMARY KEY,
    query           TEXT         NOT NULL,
    selected_tool_id TEXT,
    confidence      FLOAT,
    latency_ms      FLOAT,
    strategy        TEXT,
    alternatives    JSONB,                               -- array of {tool_id, score}
    created_at      TIMESTAMPTZ  DEFAULT now()
);

-- ============================================================
-- 3b. execution_logs — tool execution audit trail
-- ============================================================

CREATE TABLE execution_logs (
    id           BIGSERIAL    PRIMARY KEY,
    tool_id      TEXT         NOT NULL,
    server_id    TEXT         NOT NULL,
    success      BOOLEAN      DEFAULT true,
    latency_ms   FLOAT,
    error_message TEXT,
    params       JSONB,
    created_at   TIMESTAMPTZ  DEFAULT now()
);

-- ============================================================
-- 4. Indexes
-- ============================================================

-- Full-text search on tools
CREATE INDEX idx_mcp_tools_fts ON mcp_tools USING GIN (fts);

-- Server-filtered tool queries (e.g. Sequential Strategy Layer 2)
CREATE INDEX idx_mcp_tools_server_id ON mcp_tools (server_id);

-- Pending tool queue for batch indexing
CREATE INDEX idx_mcp_tools_index_status ON mcp_tools (index_status);

-- Time-range queries on query logs
CREATE INDEX idx_query_logs_created_at ON query_logs (created_at);

-- Execution logs: time-range and per-tool queries
CREATE INDEX idx_execution_logs_created_at ON execution_logs (created_at);
CREATE INDEX idx_execution_logs_tool_id ON execution_logs (tool_id);

-- ============================================================
-- 5b. Full-text search RPC function
-- ============================================================
-- Called by Search Lambda lexical fallback: POST /rest/v1/rpc/search_tools_fts

CREATE OR REPLACE FUNCTION search_tools_fts(
    search_query TEXT,
    result_limit INT DEFAULT 5,
    status_filter TEXT DEFAULT 'indexed'
)
RETURNS SETOF mcp_tools
LANGUAGE sql STABLE
AS $$
    SELECT * FROM mcp_tools
    WHERE index_status = status_filter
      AND fts @@ plainto_tsquery('english', search_query)
    ORDER BY ts_rank(fts, plainto_tsquery('english', search_query)) DESC
    LIMIT result_limit;
$$;

-- ============================================================
-- 5c. updated_at trigger for mcp_servers
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_updated_at
    BEFORE UPDATE ON mcp_servers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- 6. Row-Level Security (RLS)
-- ============================================================

-- Enable RLS on public-facing tables
ALTER TABLE mcp_servers ENABLE ROW LEVEL SECURITY;
ALTER TABLE mcp_tools   ENABLE ROW LEVEL SECURITY;

-- anon: read-only access for public browsing
CREATE POLICY "anon_read_servers"
    ON mcp_servers FOR SELECT
    TO anon
    USING (true);

CREATE POLICY "anon_read_tools"
    ON mcp_tools FOR SELECT
    TO anon
    USING (true);

-- authenticated: read access
CREATE POLICY "authenticated_read_servers"
    ON mcp_servers FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "authenticated_read_tools"
    ON mcp_tools FOR SELECT
    TO authenticated
    USING (true);

-- service_role: full access (Supabase grants this by default;
-- explicit policies ensure clarity)
CREATE POLICY "service_role_all_servers"
    ON mcp_servers FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_all_tools"
    ON mcp_tools FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- RLS for query_logs (service_role only — contains sensitive query data)
ALTER TABLE query_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_query_logs"
    ON query_logs FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- RLS for execution_logs (service_role only — contains execution params)
ALTER TABLE execution_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_execution_logs"
    ON execution_logs FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
