# Status Lifecycle

## mcp_tools.index_status

State machine for tool indexing lifecycle:

```
pending ──→ indexing ──→ indexed
                    └──→ failed
indexed ──→ deprecated
        ──→ unreachable
        ──→ quarantined
```

| Transition | Trigger | Lambda |
|-----------|---------|--------|
| pending → indexing | Index Lambda claims tool | index/handler.py |
| indexing → indexed | Embedding + Qdrant upsert succeeds | index/handler.py |
| indexing → failed | Any step fails | index/handler.py |
| indexed → deprecated | [Phase 2] Health check detects EOL | TBD |
| indexed → unreachable | [Phase 2] Health check fails N times | TBD |
| indexed → quarantined | [Phase 2] Manual admin action | TBD |

## mcp_servers.entity_status

Business lifecycle of a registered MCP server:

```
active ──→ deprecated ──→ superseded
       ──→ unreachable
       ──→ quarantined
```

| Value | Meaning |
|-------|---------|
| active | Default. Server is operational. |
| deprecated | Server is being phased out. |
| unreachable | Health checks consistently failing. |
| superseded | Replaced by a newer version. |
| quarantined | Manually flagged for investigation. |

Note: entity_status is currently READ-ONLY in application code. No Lambda writes to it. Transitions will be implemented in Phase 2 health check workflows.
