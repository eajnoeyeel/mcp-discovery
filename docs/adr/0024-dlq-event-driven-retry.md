# ADR-0024: Event-driven DLQ retry with substrate-independent circuit breaker

**Status**: Accepted (2026-04-19)
**Supersedes**: — (incremental hardening of the inline-retry DLQ consumer that
shipped with the serverless pivot)

## Context

`service/lambdas/index_dlq_consumer/handler.py` historically executed retry
inline by constructing `IndexService(embedder, qdrant_store)` and calling
`index_rows`. Two problems emerged simultaneously:

1. **Hybrid invariant break.** DLQ instantiated `IndexService` without
   `sparse_embedder` or `llm_client`; on retry it silently fell into the
   dense-only branch of `index_rows`, producing Qdrant points that did not
   participate in hybrid retrieval. Production failure rate happened to be
   ~0% so the invariant violation never surfaced, but it was latent.

2. **No event-driven retry.** The alternative (flip `failed → pending` and
   wait for `IndexReplayFunction` cron) is polling, not event-driven, with
   up to 30 minutes of retry latency. `IndexReplay` itself was also broken —
   its PostgREST filter embedded `now()-interval'30 minutes'` which PostgreSQL
   could not cast (error 22007), crashing every scheduled invocation since
   deployment. (Fixed separately in this same change-set.)

Measurement snapshot (2026-04-19, n=3,078 `mcp_tools`):
indexed=3,051 (99.1%), failed=15 (0.49%, all E2E fixtures), pending=12 (0.39%,
all E2E fixtures). Production failure rate effectively 0%.

## Decision

Convert the DLQ consumer into a pure **event-driven handoff** back to the
primary IndexFunction via EventBridge, with a DB-level circuit breaker to
survive SQS `ApproximateReceiveCount` resets on republish.

```
primary IndexFunction (hybrid)
  ├─ success → Qdrant hybrid point + Supabase indexed
  └─ failure → SQS IndexDLQ
                 │
                 ▼
       index_dlq_consumer (this ADR)
         ├─ retry_count >= MAX_RETRY_COUNT? → failed_permanent (terminal)
         ├─ cooldown active (<2 min since last update)? → skip
         └─ else → EB publish server.registered  (publish-first)
                    → RPC increment_retry_count + flip pending  (DB-atomic)
                    → primary IndexFunction re-runs with full hybrid wiring
```

Safety net: `IndexReplayFunction` (30-min cron) still catches anything that
slipped through the event-driven path (EB publish failure, RPC failure, etc.).

## Drivers

1. **Hybrid invariant parity.** DLQ must not be a Qdrant-write path; routing
   back through primary is the only way to guarantee sparse + LLM enrichment
   on retry.
2. **Event-driven consistency.** The rest of the platform is EventBridge-based
   (register → index). Polling-only retry was architecturally inconsistent.
3. **Substrate-independent circuit breaker.** SQS `ApproximateReceiveCount`
   resets on republish, so a DB-level `retry_count` is required to prevent
   infinite retry loops.
4. **Team risk tolerance.** Recent incidents with Supabase ↔ Qdrant
   consistency argue against aggressive refactors; this is additive and
   reversible.

## Alternatives Considered

| Option | Description | Verdict |
|---|---|---|
| **A. Inline retry in DLQ with full hybrid deps** | Add fastembed + OpenAI + sparse embedder to DLQ Lambda; run IndexService directly. | **Rejected**: duplicates embedding infra, reopens ADR-0017 (arm64 × onnxruntime), Lambda package swells. |
| **B. Flip-only handoff + 30-min cron** | DLQ flips status, IndexReplay picks up. | **Rejected as final state**: polling latency up to 30 min; architecturally inconsistent. Kept as safety net only. |
| **C. Event-driven handoff via EB publish** (chosen) | DLQ publishes server.registered to EB, primary re-runs hybrid path. | **Accepted** with the hardening below. |
| **D. Lambda Destinations (OnFailure → EB)** | Native AWS pattern; custom DLQ consumer deleted. | **Deferred to Phase 2**: requires primary Lambda EventInvokeConfig change (prod risk). ROI low at current failure volume. |
| **E. EventBridge Pipes (SQS → EB direct)** | No Lambda needed; Pipe does filter + route. | **Deferred to Phase 2**: new IAM role + Pipe resource; revisit after Phase 1 has produced metrics. |
| **F. Step Functions orchestration** | State-machine retry. | **Rejected**: single-path retry does not justify state-machine complexity. |

## Why C Over D/E Now

D (Lambda Destinations) and E (EB Pipes) are strictly more AWS-native and
eliminate the DLQ consumer Lambda. C is an incremental move because:

- Primary Lambda `IndexFunctionImage` EventInvokeConfig change touches prod.
- Current failure volume does not justify config-change risk this cycle.
- C reuses the existing EventBridge wiring already proven by `register` and
  `index_replay` Lambdas.
- **Phase 2** (documented roadmap item): migrate to Destinations or Pipes
  next quarter; delete `index_dlq_consumer` Lambda entirely.

## Consequences

### New surface

- `mcp_tools.retry_count integer NOT NULL DEFAULT 0` column.
- `index_status='failed_permanent'` terminal state added to CHECK constraint.
- `increment_retry_and_reset_to_pending(text[])` Postgres RPC for atomic
  increment + state flip (PostgREST cannot express `col = col + 1` in PATCH).

### Observability

CloudWatch EMF metrics under namespace `McpDiscovery/IndexDLQ`:

| Metric | Dimensions | Meaning |
|---|---|---|
| `RedispatchSuccess` | — | Tools successfully republished to primary. |
| `RedispatchFailures` | `Phase` ∈ {`publish`, `rpc_update`} | EB or DB step failed. |
| `TerminalFailures` | `Reason` ∈ {`retry_count_exhausted`, `sqs_circuit_breaker`} | Tools flipped to failed_permanent. |
| `CooldownSkipped` | — | Record skipped due to per-server thundering-herd guard. |

Existing `IndexDLQDepthAlarm` remains. Add a CloudWatch alarm on
`TerminalFailures > 0` (per 1h) for manual triage trigger.

### Pre-mortem response

| Failure mode | Mitigation |
|---|---|
| Republish thundering-herd (same server, N concurrent) | `COOLDOWN_SECONDS=120` per-server guard + primary's existing optimistic claim lock. |
| Poison pill (SQS receive_count resets on republish → infinite loop) | `MAX_RETRY_COUNT=5` DB-level ceiling → `failed_permanent`. |
| EB publish failure orphans tools in `pending` | Publish-first ordering: RPC only runs on publish success. If publish fails, exception raises and SQS re-delivers. Safety net: IndexReplay cron catches missed transitions within 30 min. |
| SQS `MAX_RECEIVE_COUNT` trip silently drops message | Circuit-breaker branch flips remaining `failed` tools to `failed_permanent` before returning; `TerminalFailures` metric surfaces to alarm. |
| RPC fails after publish → duplicate EB event on SQS retry | Primary IndexFunction's optimistic claim lock (`index_status=eq.pending`) handles duplicate-trigger idempotency; Qdrant point IDs are deterministic UUID5 so upsert is also idempotent. |

### Irreversibility footprint

- Migration 033 is additive and reversible (rollback script at
  `service/supabase/rollback/033_rollback_mcp_tools_retry_count.sql`). Must
  first migrate any `failed_permanent` rows back to `failed` before running
  the rollback.
- Lambda package shrank from ~20 runtime deps to 13 (removed openai,
  qdrant-client, numpy, grpcio, protobuf, pydantic-settings, python-dotenv,
  sniffio; added boto3 + s3transfer + jmespath + python-dateutil).
- No Qdrant changes. No frontend changes. No dashboard code changes.

## Follow-ups

1. **Phase 2 migration to Lambda Destinations or EventBridge Pipes.** Gate on
   observed failure volume from Phase 1 metrics. Target: next quarter.
2. **CloudWatch alarm on `TerminalFailures` and `RedispatchFailures`.**
   Wire into SAM template next deploy.
3. **IndexReplay filter fix.** Separately shipped in same change-set
   (client-computed ISO threshold replaces broken PostgreSQL expression).

## Roadmap Visual

```
Phase 1 (this ADR, shipped)
  ├─ Event-driven DLQ → EB handoff
  ├─ retry_count + failed_permanent
  ├─ EMF metrics
  └─ IndexReplay filter bug fix (safety net restored)

Phase 2 (next quarter, tracked separately)
  ├─ CloudWatch alarms on new metrics
  ├─ Evaluate failure volume from Phase 1 telemetry
  └─ Migrate: DLQ consumer Lambda → Lambda Destinations OR EventBridge Pipes
```

## Verification

- `uv run ruff check service/ tests/` — clean.
- `uv run pytest tests/unit/mlp/test_mlp_index_dlq_consumer.py -v` — all tests
  covering: circuit breakers (SQS + DB), cooldown, publish-first ordering,
  EMF structure, local_direct vs AWS builder, Supabase helper wire format.
- Migration 033 applied and verified against live Supabase:
  column present, CHECK constraint includes `failed_permanent`, RPC function
  registered with `TABLE(tool_id text, retry_count integer)` return type.
