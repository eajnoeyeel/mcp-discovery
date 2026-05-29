# ADR-0021: tool_enrichment_cache Table for ADR-0017 Hybrid Enrichment

**Date**: 2026-04-19
**Status**: accepted
**Deciders**: schema-audit-fixes team

## Context

ADR-0017 (hybrid retrieval rollout, PR#73, R@3=46.8%) introduced a hybrid dense+sparse RRF retrieval path. The enrichment pipeline that generates per-tool sparse signals (keyword extraction, category tags, provider metadata overrides) was identified as a bottleneck: it re-runs on every index refresh, even when the underlying tool description has not changed.

Migration 024 created `tool_enrichment_cache` to store enrichment outputs keyed by `(tool_id, content_hash)`. When the indexer encounters a tool whose `content_hash` matches a cache row, it reuses the cached enrichment payload instead of invoking the enrichment pipeline. Cache invalidation is hash-based: a description change produces a new `content_hash`, which misses the cache and triggers re-enrichment.

At the time of the 2026-04-19 schema audit, `tool_enrichment_cache` is missing RLS policies and an `updated_at` trigger — tracked as finding M2 in that audit and scheduled for migration 025.

## Decision

Create `tool_enrichment_cache` with `(tool_id, content_hash)` as the natural cache key, storing enrichment payload as JSONB, with `created_at` timestamp. Row-level Security and `updated_at` trigger deferred to migration 025 (tracked as M2).

## Alternatives Considered

### Alternative 1: Store enrichment output in-process cache (Lambda memory / ElastiCache)
- **Pros**: Zero DB round-trips for cache hit; no schema change
- **Cons**: Lambda cold starts invalidate in-process cache; ElastiCache adds infrastructure cost and complexity; cache not shared across Lambda instances; no audit trail of enrichment history
- **Why not**: The content_hash-keyed DB cache is already available via `mcp_tools.content_hash`; a DB row is durable across cold starts and instances without additional infrastructure

### Alternative 2: Add enrichment columns directly to `mcp_tools`
- **Pros**: Single table lookup; no JOIN
- **Cons**: `mcp_tools` is a canonical entity table (P10 Data Contract Clarity); embedding enrichment payload JSONB there conflates catalog state with derived computation; makes the column set harder to reason about for non-enrichment consumers
- **Why not**: Enrichment output is a derived artifact, not a canonical property; separation into a cache table keeps `mcp_tools` as a clean catalog entity

### Alternative 3: Re-run enrichment on every index refresh unconditionally
- **Pros**: No caching complexity; always fresh
- **Cons**: Enrichment pipeline (LLM calls for keyword/category extraction) costs ~$0.002/tool/run; at 320-tool pool with 5-min refresh cycles, this is ~$185/day purely on enrichment; also adds latency to the index refresh critical path
- **Why not**: ADR-0017 explicitly flagged enrichment cost as a scale concern; content_hash provides a correct and cheap invalidation signal

## Consequences

### Positive
- Enrichment pipeline skips unchanged tools, reducing LLM API cost proportional to description change rate
- Cache rows provide an audit trail of enrichment history per content_hash
- Hash-based invalidation is correct by construction: stale cache is impossible as long as `content_hash` is faithfully updated on description change

### Negative
- Adds a JOIN (or lookup) in the enrichment path for every tool processed
- Cache table currently lacks RLS (M2) — any service_role consumer can read all enrichment payloads
- No TTL or size cap: if tools churn frequently, cache grows unboundedly (tracked but deferred)

### Risks
- If `content_hash` is not updated when a tool description changes (e.g., via a direct DB PATCH that bypasses the indexer), the enrichment cache will serve stale output — mitigated by the `set_mcp_tools_updated_at` trigger which fires on any UPDATE, prompting the indexer to recompute the hash
