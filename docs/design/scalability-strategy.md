# Scalability Strategy

> MCP Discovery Platform — partitioning, indexing, and archival plan for operational data.

## 1. Current State

### Tables and Growth Projections

| Table | Row Growth | Current Indexes |
|-------|-----------|-----------------|
| `execution_logs` | ~100-1K/day (MLP), ~10K/day (scale) | `(created_at)`, `(tool_id)`, `(tool_id, created_at)` (migration 016) |
| `query_logs` | ~100-1K/day (MLP), ~10K/day (scale) | `(created_at)` |
| `mcp_tools` | Slow growth (~hundreds) | `(server_id)`, `(index_status)`, `(content_hash)`, GIN `(fts)` |
| `mcp_servers` | Slow growth (~tens) | `(server_id)` UNIQUE |

### Hot Query Patterns

| Query | Tables | Index Used |
|-------|--------|-----------|
| MV refresh: `tool_operational_stats_7d` | `execution_logs` | `(created_at)` range scan → GROUP BY `tool_id` |
| MV refresh: `tool_daily_stats` | `execution_logs` | `(created_at)` range scan → GROUP BY `tool_id, date` |
| Provider drill-down (planned) | `execution_logs` | `(tool_id, created_at)` composite — per-tool time-range |
| Search audit | `query_logs` | `(created_at)` range scan |
| Pending tool queue | `mcp_tools` | `(index_status)` equality |
| Failed tool retry (DLQ consumer) | `mcp_tools` | `(server_id)` + `(index_status)` |

## 2. Indexing Strategy

### Migration 016: Composite Index

```sql
CREATE INDEX idx_execution_logs_tool_id_created_at
    ON execution_logs (tool_id, created_at);
```

**Rationale**: Existing single-column indexes cover current MV refresh patterns (time-range first, then group by tool). The composite index supports the inverse access pattern — per-tool time-range queries — needed for provider dashboard drill-down.

**Trade-off**: Marginal write overhead on every execution log INSERT. Acceptable given current volume (~1K/day).

### Future: Partial Index for Active Tools

When tool count exceeds 1K, consider a partial index on frequently queried tools:

```sql
-- Example: index only tools with recent activity
CREATE INDEX idx_execution_logs_active_tools
    ON execution_logs (tool_id, created_at)
    WHERE created_at > now() - interval '90 days';
```

## 3. Partitioning Plan

### Phase 1: MLP (current) — No Partitioning

At current volume (< 1M rows/table), single-table storage with indexes is sufficient. Premature partitioning adds operational complexity without measurable benefit.

**Trigger for Phase 2**: Any table exceeds 10M rows or MV refresh latency exceeds 5s.

### Phase 2: Time-Range Partitioning

When triggered, partition high-growth tables by month:

```sql
-- execution_logs: monthly partitions
CREATE TABLE execution_logs (
    id BIGSERIAL,
    tool_id TEXT NOT NULL,
    server_id TEXT NOT NULL,
    success BOOLEAN DEFAULT true,
    latency_ms FLOAT,
    error_message TEXT,
    params JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
) PARTITION BY RANGE (created_at);

-- Monthly partitions
CREATE TABLE execution_logs_2026_04 PARTITION OF execution_logs
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
```

**query_logs**: Same monthly partitioning strategy.

**mcp_tools / mcp_servers**: No partitioning needed — slow growth, small tables.

### Implementation Approach

Use `pg_partman` for automated partition management:
- Auto-create future partitions (2 months ahead)
- Auto-detach old partitions beyond retention window
- No application code changes required — Supabase queries work transparently

## 4. Archival Strategy

### Retention Tiers

| Tier | Duration | Storage | Access |
|------|----------|---------|--------|
| Hot | 0-30 days | Supabase (live table) | Real-time queries, MV refresh |
| Warm | 30-90 days | Supabase (attached partition) | Ad-hoc queries, historical analytics |
| Cold | 90-365 days | Detached partition / S3 export | Compliance, audit |
| Archived | > 365 days | S3 Glacier / deleted | Regulatory only |

### Archival Process

1. **Monthly cron** (or Lambda on schedule): export partitions older than 90 days to S3 as Parquet
2. **Detach** exported partitions from the live table
3. **Drop** detached partitions after S3 export verification
4. **MV refresh** only touches hot + warm tiers (last 30-90 days)

### MLP Simplification

At MLP stage, archival is manual:
- `DELETE FROM execution_logs WHERE created_at < now() - interval '90 days'` (quarterly)
- `DELETE FROM query_logs WHERE created_at < now() - interval '90 days'` (quarterly)
- No S3 export until production scale

## 5. DLQ Replay Strategy

The IndexDLQ consumer (`IndexDLQConsumerFunction`) handles failed indexing retries automatically:

- **SQS retention**: 14 days (maximum)
- **Circuit breaker**: Messages received ≥ 3 times are consumed but not retried
- **State machine**: `failed` → `indexing` → `indexed` (no reset to `pending`, avoiding race with IndexFunction)

For persistent failures beyond the circuit breaker:
1. CloudWatch alarm on DLQ queue depth (post-MLP)
2. Manual investigation via SQS console or `aws sqs receive-message`
3. Root cause fix → re-register server to trigger fresh indexing

## 6. Decision Log

| Decision | Rationale |
|----------|-----------|
| No partitioning at MLP | < 1M rows, premature optimization |
| Monthly partitions at scale | Matches 30-day MV refresh window, simple to manage |
| 90-day hot+warm retention | Balances analytics needs with storage cost |
| Composite index now | Low cost, supports planned provider drill-down |
| DLQ consumer over manual replay | Automatic recovery for transient failures |
