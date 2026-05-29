# ADR-0023: Upstream Secrets to AWS Secrets Manager — Drop Plaintext Columns

**Date**: 2026-04-19
**Status**: accepted
**Deciders**: schema-audit-fixes team

## Context

Audit finding C1 (2026-04-15, carried forward to 2026-04-19): migration 008 introduced `bearer_token` and `api_key` plaintext columns on `mcp_server_auth`. `mcp_oauth_sessions` stores `client_secret`, `access_token`, and `refresh_token` in plaintext. RLS gates these tables by role (`service_role` only), not by individual identity — any holder of the service_role key can read all upstream provider credentials via PostgREST or direct SQL.

The concrete threat: a Supabase backup restored to a dev environment (where service_role keys are distributed to developers for debugging) exposes every registered provider's upstream auth credentials. A service_role key leak has the same blast radius.

`_ref` columns (`bearer_token_ref`, `api_key_ref` on `mcp_server_auth`; `client_secret_ref`, `access_token_ref`, `refresh_token_ref` on `mcp_oauth_sessions`) were added in migrations 010 and 018. The code path for reading secrets via AWS Secrets Manager already exists (`service/supabase/adapters/` secret-ref pattern). worker-backend's changes (task #3 in the schema-audit-fixes team) updated all Lambda write/read paths to use `_ref` columns exclusively.

Current production context: the platform is non-user-facing, running E2E-only against the hybrid search rollout (PR#73, R@3=46.8%). There is no active user soak window that would require a dual-column compatibility period.

## Decision

Drop plaintext columns `bearer_token`, `api_key` from `mcp_server_auth` and `client_secret`, `access_token`, `refresh_token` from `mcp_oauth_sessions` in migration 029. All secrets live in AWS Secrets Manager, referenced by the existing `_ref` columns. The code rollout (worker-backend) precedes migration 029 in apply order.

## Pre-Apply Checklist

Before applying migration 029, an operator MUST verify all three conditions:

- [ ] **(a) Code merged and Lambdas rebuilt**: worker-backend's secret-ref-only code path is merged to main, all affected Lambdas (register, execute, oauth) are rebuilt and deployed. No Lambda in the fleet reads `bearer_token`, `api_key`, `client_secret`, `access_token`, or `refresh_token` directly.
- [ ] **(b) Backfill complete**: every row in `mcp_server_auth` where `auth_type != 'none'` has a non-null `bearer_token_ref` or `api_key_ref`. Every row in `mcp_oauth_sessions` has non-null `_ref` equivalents for any non-null plaintext column. Verify with:
  ```sql
  -- mcp_server_auth: no plaintext row should lack a _ref counterpart
  SELECT COUNT(*) FROM mcp_server_auth
  WHERE auth_type != 'none'
    AND (bearer_token IS NOT NULL AND bearer_token_ref IS NULL)
     OR (api_key IS NOT NULL AND api_key_ref IS NULL);
  -- Expected: 0

  -- mcp_oauth_sessions: no plaintext row should lack a _ref counterpart
  SELECT COUNT(*) FROM mcp_oauth_sessions
  WHERE (client_secret IS NOT NULL AND client_secret_ref IS NULL)
     OR (access_token IS NOT NULL AND access_token_ref IS NULL)
     OR (refresh_token IS NOT NULL AND refresh_token_ref IS NULL);
  -- Expected: 0
  ```
- [ ] **(c) User explicitly approves DDL apply**: migration 029 is a destructive, irreversible column drop. A human operator must confirm apply after reviewing backfill counts.

## Migration 029 (schema — do not apply without checklist)

```sql
-- Migration 029: drop plaintext upstream secret columns
-- PRECONDITION: checklist (a)(b)(c) verified

ALTER TABLE mcp_server_auth
    DROP COLUMN IF EXISTS bearer_token,
    DROP COLUMN IF EXISTS api_key;

ALTER TABLE mcp_oauth_sessions
    DROP COLUMN IF EXISTS client_secret,
    DROP COLUMN IF EXISTS access_token,
    DROP COLUMN IF EXISTS refresh_token;
```

## Rollback Procedure

Rollback requires restoring plaintext columns from Secrets Manager values. The rollback script is at:

```
service/supabase/rollback/029_rollback_restore_plaintext.sql
```

That script re-adds the dropped columns as nullable and populates them from a manual Secrets Manager → plaintext backfill. Operators must:

1. Apply `029_rollback_restore_plaintext.sql` to re-add the nullable columns.
2. Run the backfill script (separate operator tooling) that reads each secret ARN from the `_ref` columns, fetches the plaintext value from AWS Secrets Manager, and writes it back to the plaintext columns.
3. Redeploy the pre-worker-backend Lambda versions that read plaintext columns.

**Warning**: Step 2 writes plaintext credentials back to the database. The rollback procedure restores the C1 vulnerability by design. It should only be used for emergency recovery and must be immediately followed by a re-migration forward.

## Alternatives Considered

### Alternative 1: Retain plaintext columns, add column-level encryption at rest
- **Pros**: No column drop risk; plaintext readable for debugging under controlled conditions
- **Cons**: Supabase does not natively support column-level encryption; requires application-level encrypt/decrypt round-trips that add latency to every auth resolution; still vulnerable to service_role key leak exposing encrypted blobs + encryption key if both are in the same environment
- **Why not**: _ref + Secrets Manager is already implemented; adding column-level encryption doubles the complexity with no incremental security benefit over the existing pattern

### Alternative 2: Add a soak window — keep both plaintext and _ref columns for 30 days
- **Pros**: Dual-column window allows rollback without Secrets Manager backfill
- **Cons**: Extends the C1 vulnerability window by 30 days; the platform is not user-facing (E2E-only per PR#73 rollout) so there is no active traffic that requires the soak period
- **Why not**: Zero user traffic means zero rollback need during soak; the pre-apply checklist (backfill verification + explicit approval) provides the same safety guarantee without the time cost

### Alternative 3: Vault/HashiCorp instead of AWS Secrets Manager
- **Pros**: Vendor-neutral; works outside AWS
- **Cons**: Introduces a new infrastructure dependency; the secret-ref pattern in `service/supabase/adapters/` is already built for Secrets Manager ARNs; migration would require rewriting the adapter
- **Why not**: Secrets Manager is already integrated; adding Vault is a separate infrastructure decision that can be made independently of this column drop

## Consequences

### Positive
- C1 audit finding resolved upon apply of migration 029
- Supabase backup / service_role key leak no longer exposes upstream provider credentials
- Schema is consistent with the `_ref` pattern already established in migrations 010 and 018

### Negative
- Rollback requires a Secrets Manager → plaintext backfill script that must be maintained and tested separately
- If any Lambda deployment was missed during the pre-apply checklist, auth calls will fail with a null column read — mitigated by the backfill verification query in the checklist

### Risks
- Secrets Manager API call failure during Lambda cold start could cause auth resolution failures — mitigated by existing retry logic and the Secrets Manager SDK's local caching (default 5-minute TTL per secret)
- ARN format mismatch between `_ref` values and Secrets Manager region/account could cause silent null reads — mitigated by integration test in `service/rag/tests/` that validates secret resolution before marking a deployment ready

## Follow-ups

- Add `service/supabase/rollback/029_rollback_restore_plaintext.sql` (worker-migrations scope, not this ADR)
- After migration 029 is applied, remove the C1 entry from `docs/audits/2026-04-19-serverless-schema-audit.md` and update finding status to RESOLVED
- Rotate any secrets that existed in plaintext for longer than 30 days post-C1 identification (2026-04-15 audit date)
