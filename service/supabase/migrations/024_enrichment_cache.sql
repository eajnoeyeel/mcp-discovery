CREATE TABLE tool_enrichment_cache (
    content_hash      TEXT        PRIMARY KEY,
    tool_id           TEXT        NOT NULL,
    sparse_input      TEXT        NOT NULL,
    enrichment_model  TEXT        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tool_enrichment_cache_tool_id ON tool_enrichment_cache (tool_id);
COMMENT ON TABLE tool_enrichment_cache IS 'P5 idempotency cache for LLM enrichment (ADR-0017).';
