# ADR-0020: query_logs Schema Evolution — Column Rename, execution FK, and Analytics Views

**Date**: 2026-04-19
**Status**: accepted
**Deciders**: schema-audit-fixes team

## Context

Migration 022 made three coordinated changes to the analytics layer that required a single ADR to capture as a unit:
1. `query_logs.selected_tool_id` was renamed to `recommended_tool_id` to accurately reflect that the column records which tool was recommended by the retrieval pipeline, not which tool was ultimately executed.
2. `execution_logs.query_log_id` FK was added to link each execution event back to the originating query, enabling funnel analysis without a JOIN on `event_id`.
3. Two new views — `tool_exposure_facts` and `tool_conversion_funnel` — were created on top of the renamed column and the new FK to support dashboard funnel metrics.

PR#73 (hybrid dense+sparse RRF, R@3=46.8%) landed on main immediately before these migrations and serves as the pre-migration E2E anchor: all recall metrics and dashboard reads were validated against the pre-022 schema before the rename was applied.

The rename was blocked until PR#73 merged because the frontend `useToolDashboard` hook and the Python `RAGService` both referenced `selected_tool_id`. Deferring the rename past PR#73 would have required a two-step deprecation column approach; doing it in the same migration batch kept the schema and code in sync.

## Decision

Rename `query_logs.selected_tool_id` → `recommended_tool_id`, add `execution_logs.query_log_id` FK referencing `query_logs.id`, and create `tool_exposure_facts` / `tool_conversion_funnel` views in migration 022. Update all TypeScript and Python callsites atomically in the same PR.

## Alternatives Considered

### Alternative 1: Add `recommended_tool_id` as a new column, keep `selected_tool_id`
- **Pros**: Zero-downtime rollout; old code continues to work during deploy
- **Cons**: Dual-write overhead; migration complexity; stale column accumulates data indefinitely; schema drift finding H1 from 2026-04-15 audit would persist
- **Why not**: All callsites are Lambda-deployed atomically; there is no rolling deploy across heterogeneous instances that would require a dual-column window

### Alternative 2: Defer rename to a separate migration after PR#73 stabilization
- **Pros**: Smaller blast radius per PR
- **Cons**: Creates a post-PR#73 window where schema and code names diverge; frontend dashboard fetch would need a compatibility shim; TS type generation would produce confusing dual names
- **Why not**: The rename is a correctness fix (the tool is "recommended", not "selected"); delaying it creates more confusion than the short-lived rename window

## Consequences

### Positive
- Column name accurately reflects pipeline semantics (recommendation, not confirmed selection)
- `execution_logs.query_log_id` enables direct funnel queries without correlated subqueries on `event_id`
- `tool_exposure_facts` and `tool_conversion_funnel` views provide dashboard funnel metrics under P2 (Precomputed Reads)
- TS drift finding H1 from 2026-04-15 audit resolved

### Negative
- Any external tooling or Supabase saved queries using `selected_tool_id` must be updated manually
- `tool_exposure_facts` and `tool_conversion_funnel` are regular VIEWs (not MVs); at high log volume they aggregate on read (tracked as finding H4 in 2026-04-19 audit)

### Risks
- If a Lambda deployment partially fails mid-rename window, logs written during the window will drop into neither column — mitigated by atomic Lambda deployment and pre-migration snapshot backup
