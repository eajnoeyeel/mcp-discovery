# ADR-0014: Metric Semantic Redesign

**Date**: 2026-04-17
**Status**: accepted

## Decision

Rename `query_logs.selected_tool_id` to `recommended_tool_id` and add
`execution_logs.query_log_id` FK to `query_logs(id)`, enabling a
four-fact analytics funnel: recommendation, exposure, execution, and
conversion (real selection). Implemented via migration 022, with
Pydantic alias and dual-write transition for backward compatibility.

## Drivers

1. `selected_tool_id` semantically implies user choice but actually
   records the rank-1 recommendation. This misleads dashboard consumers
   and every downstream view inherits the misnomer.
2. Without a FK between `execution_logs` and `query_logs`, we cannot
   measure conversion (recommendation-to-execution rate). With an LLM
   as the selector (via MCP bridge), conversion is a genuine
   preference signal once data accumulates.
3. The 012/021 migration chain already converted analytics MVs to
   live views, so recreating them under the new column name is a
   drop-and-create rather than a refresh-pipeline change.

## Alternatives considered

1. **Keep the misleading name, add a separate `recommended_tool_id`
   column** — rejected; redundant and does not fix the misnomer in
   existing views.
2. **Two separate migrations (022 rename, 023 FK + new views)** —
   rejected; intermediate state risk where views reference a
   half-renamed column.
3. **Soft rename via view aliasing (keep physical column, create
   alias views)** — rejected; doubles view count and Python/TS code
   still references the wrong name.
4. **Include exposure metric as part of this scope** — accepted;
   exposure (top-K appearance) is distinct from recommendation
   (rank-1), and the `alternatives` JSONB already holds the data.
   A `tool_exposure_facts` view unnests it.

## Why chosen

Single-migration rename + FK is the cleanest path:
- Atomic rollback on failure.
- Pydantic alias preserves backward compat for serialized JSONL.
- Dual-write in `_build_payload` eliminates the INSERT-failure window
  that deploy-ordering alone cannot prevent.
- Views recreated in the same transaction — no half-migrated state.

## Consequences

- ~24 actionable files updated across Python, TypeScript, SQL.
- JSONL in `data/experiments/synthetic_traffic.jsonl` updated to the
  new field name for consistency. Backward-read is preserved via the
  Pydantic alias on `QueryLogEntry`.
- `conversion_rate` is initially NULL for all tools until execution
  data with `query_log_id` accumulates. Dashboard renders an
  "Awaiting execution data" placeholder in the NULL state.
- MCP protocol surface adds optional `query_log_id` field to
  `execute_tool` input schema; `find_best_tool` response includes
  `query_log_id`. This is additive and does not break existing clients.
- Live ranking pipeline is completely untouched (Principle 1). The
  `compute_operability_float()` function, FlatStrategy, and operability
  merge continue to use `success_rate`, `timeout_rate`, `avg_latency_ms`
  from execution logs — no change.

## Follow-ups

- Remove dual-write key in a follow-up commit after migration 022 is
  verified in production (write only `recommended_tool_id`).
- Issue #60: Register handler → RegisterService delegation (separate
  scope; deferred post metric-semantic-redesign).
- Phase B: Feed `conversion_rate` into ranking (requires separate ADR
  + threshold analysis + anti-gaming safeguards + cold-start
  protection; contingent on execution data volume).
- Remove stale MV-staleness references that still mention the retired
  sync-service path (follow-up from 021; not blocking).
- Choose single operability source of truth in live search path
  (separate live-search concern).
