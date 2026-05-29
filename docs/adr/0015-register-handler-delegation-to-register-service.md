# ADR-0015: Register handler delegates to RegisterService

**Date**: 2026-04-17 (proposed) / 2026-04-18 (accepted)
**Status**: accepted
**Deciders**: 이연재

## Context

`service/services/register_service.py::RegisterService.register()` is a complete
registration pipeline (validation, upsert, provider linking via
`_get_or_create_provider`, `MetadataDiscoveryService` injection, parameter
metadata normalization, `content_hash` computation, EventBridge publish with
`EventPublishError`). It has **zero production references** — grep and Serena
`find_referencing_symbols` both confirm the method is called only from 11 test
sites.

The live `/register` Lambda in `service/lambdas/register/handler.py` builds a
`RegisterService` instance at line 130 but never invokes `.register()`. Instead
it duplicates ~332 lines of inline logic: auth validation, provider creation
via `ProviderService`, Supabase inserts via `_supabase_insert`, and the
EventBridge publish with its `except` branch that marks tools `event_failed`
and returns HTTP 202 so `index_replay` Lambda can retry.

Six other handler/service pairs (bridge, catalog, dashboard, execute, index,
search) all delegate business logic to their service class. Register is the
only outlier.

Both options preserve compliance with `docs/design/serverless-architecture-principles.md`
(P5 idempotency, P6 designed degraded modes, P9 canonicalization). Neither
rewire nor removal is mandated by the Serverless Architecture Principles; this
is a convention-and-reuse call, not a principle-compliance call.

## Decision

Rewire `service/lambdas/register/handler.py::_async_handler` (and
`service/api/local_app.py::register_server`) to delegate to
`RegisterService.register()`, wrapping the call in
`try/except EventPublishError` at the HTTP boundary to preserve the
202 + `event_failed` → `index_replay` retry contract.

Do **not** delete `RegisterService.register()`.

Schedule as a follow-up PR after the current 11-commit transplant lands. This
ADR is the decision record; implementation is separate.

## Alternatives Considered

### Alternative 1: Remove `RegisterService.register()`

- **Pros**: Eliminates dead code on live path; no behavior change; smallest diff.
- **Cons**: Deletes teammate's registration pipeline helpers
  (`MetadataDiscoveryService` injection, `_get_or_create_provider`,
  `_normalize_parameter_metadata`, `_normalize_published_parameter_metadata`,
  `content_hash` computation). Future callers (bulk import, CLI, provider
  automation) would re-implement this logic inline. Entrenches register as the
  one handler/service pair that diverges from the codebase convention.
- **Why not**: Destroys ~150 lines of working pipeline code whose reuse
  potential is already demonstrated by 3 other services (`ExecuteService`,
  `IndexService`, `SearchService`) each being called from 2–3 Lambdas.

### Alternative 2: Keep current inline handler (status quo)

- **Pros**: No work; `event_failed` marking is co-located with its producer
  (supports P6 visibility — the designed degraded mode is visible in one file).
- **Cons**: `RegisterService.register()` remains dead code; duplicated
  registration logic must be maintained in two places if teammate's service
  updates are later mirrored into the handler (or vice versa); register stays
  divergent from the other seven handler/service pairs.
- **Why not**: The ongoing maintenance cost of duplicated pipelines (especially
  the newer `MetadataDiscoveryService` + parameter-metadata additions) will
  grow as teammate's work evolves. The convention drift compounds.

### Alternative 3: Rewire (chosen)

- **Pros**: Preserves teammate's pipeline as reusable library code; restores
  the codebase-wide handler→service delegation convention; makes
  `RegisterService.register()` available to future Lambdas (bulk import,
  CLI tooling, provider onboarding automation) for free; keeps the P6 degraded
  mode intact by catching `EventPublishError` at the HTTP boundary.
- **Cons**: Distributes the 202 + `event_failed` degraded-mode logic across
  two layers (service raises, handler catches + marks). Requires a focused
  follow-up PR.
- **Why chosen**: Teammate-code preservation (the real business value) combined
  with convention alignment outweighs the mild P6 visibility cost. The index
  handler already uses the same hybrid pattern (delegates to `IndexService`,
  keeps `event_failed` logic at handler layer), so the distribution is an
  established codebase pattern, not a new one.

## Consequences

### Positive

- `RegisterService.register()` leaves dead-code status; becomes live on the
  `/register` path plus available for future callers.
- Register handler shrinks by roughly 200 lines (duplicated Supabase insert +
  publish logic removed).
- Handler/service delegation convention restored across all 8 pairs.
- `index_replay` retry contract preserved unchanged.
- Teammate's `MetadataDiscoveryService`, provider linking, and parameter
  metadata normalization become first-class production code paths.

### Negative

- 202 + `event_failed` logic is distributed across service (`raise`) and
  handler (`except` + mark + return 202), reducing single-file visibility of
  the designed degraded mode. Mitigated by adding inline comments in both
  locations pointing to this ADR and to `service/lambdas/index_replay/handler.py`
  as the consumer.
- One additional follow-up PR required after the current transplant lands.

### Risks

- **Risk**: Rewire silently drops a teammate inline feature that was never
  ported into `RegisterService.register()`.
  **Mitigation**: Before the rewire PR, `git diff` the inline handler path
  against `RegisterService.register()` line-by-line; file an issue for each
  handler-only feature so the service grows to parity before the cutover.

- **Risk**: Rewire changes auth ordering or `ProviderService` wiring such that
  the `/register` integration path produces a subtly different HTTP response
  shape on specific error paths.
  **Mitigation**: Add integration tests covering the four error paths
  (`ValidationError` → 400, auth mismatch → 403, `EventPublishError` → 202,
  unexpected → 500) before the cutover commit, then assert they still pass
  after.

- **Risk**: Migration-number collisions
  (`service/supabase/migrations/020_*` × 2, `021_*` × 2) are applied in
  filesystem sort order; unrelated but surfaces during the follow-up work.
  **Mitigation**: Track separately (already in `progress.txt` Follow-up #3);
  do not bundle into the register-rewire PR.

## References

- `service/services/register_service.py::RegisterService.register()` (the
  method being rewired against).
- `service/lambdas/register/handler.py::_async_handler` lines 400–422 (the
  current inline publish + `event_failed` marking).
- `service/lambdas/index_replay/handler.py` (consumer of `event_failed`).
- `docs/design/serverless-architecture-principles.md` §P5, §P6, §P9 (neutral
  on this decision; both options are compliant).
- Commit `fbe677a` — restored `EventPublishError` + `content_hash` in the
  service, making this rewire viable.
- Commit `ffde203` — hoisted bridge handler import; established the PR #57
  hygiene that this ADR extends.

## Acceptance (2026-04-18)

Rewire landed in seven atomic commits. Handler is now transport-only; business
logic lives in `RegisterService.register()`; persistence primitives live in
`SupabaseClient`. Zero behavior regressions — all 1660 unit tests pass and
`make doctor && make lock && make build && make smoke` green.

### Commit trail

| Commit | Tag | Scope |
|--------|-----|-------|
| `5e345e1` | C1  | `upsert_server` absorbs both schema-compat fallbacks (`owner_user_id`, `repository_url`). |
| `6f348d5` | C1.5| `upsert_server_auth` + `upsert_oauth_session` adapter methods (A9 protocol extension). |
| `43da8e9` | C2  | `insert_tools` switches to `resolution=merge-duplicates` for idempotent re-registration. |
| `fd9e207` | C3  | `RegisterService.register()` delegates persistence to adapter; accepts `provider_id` kwarg. |
| `06dffda` | C4  | Handler `_async_handler` delegates to `RegisterService.register()` (A10 transitional pass-through). |
| `8174935` | C4.5| P6 cohesion — `mark_tools_event_failed_for_server` moves from handler to service (A3, A14). |
| `6afa6bb` | C5  | Cleanup dead helpers, restore Secrets Manager graceful degradation, AST invariant test (A5, A8). |

### A8 grep-invariant (enforced)

The handler module must not define `_supabase_insert`, `_supabase_patch`,
`_auth_row`, `_oauth_session_row`, `_is_missing_owner_column_error`, or
`_is_missing_repository_url_column_error`. This is asserted statically by
`tests/unit/mlp/test_mlp_handlers.py::TestRegisterHandlerAstInvariants::test_no_direct_supabase_insert_in_handler_module`,
which parses the handler module's AST and fails if any forbidden helper
resurfaces. Row construction lives in `service/adapters/supabase_client.py`;
orchestration lives in `service/services/register_service.py`.

### A12 plaintext-drop exit criteria (deferred)

`SupabaseClient.upsert_server_auth` and `upsert_oauth_session` currently
dual-write plaintext columns (`bearer_token`, `api_key`, `oauth_client_secret`,
`oauth_refresh_token`) alongside the `*_ref` columns added in migrations 017
and 018. Plaintext columns remain until:

1. All production rows have non-null `*_ref` values (tracked via a migration-gate
   SQL audit: `SELECT count(*) FROM mcp_server_auth WHERE bearer_token IS NOT NULL
   AND bearer_token_ref IS NULL;`).
2. `service/adapters/aws_secrets_manager.py` covers the full staging soak
   window without Secrets Manager-provisioning failures (current graceful
   degradation path in `RegisterService.register` falls back to plaintext-only
   storage).
3. A follow-up migration drops the plaintext columns and adds a NOT NULL check
   on the `*_ref` columns.
4. `execute` Lambda's `_fetch_server_auth` path reads only `*_ref` columns
   (current path tolerates both — see `TestFetchServerAuthRefColumns` in
   `tests/unit/core/test_schema_audit_fixes.py`).

This exit gate is intentionally **not** bundled into the register-rewire PR;
it requires cross-cutting changes to `execute` + `index_replay` + local-runtime
auth/resume paths and a separate ADR.

### Deferred follow-ups (not blockers for acceptance)

- **F2** (schema audit): migration-number collisions
  (`service/supabase/migrations/020_*` × 2, `021_*` × 2) — resolution tracked
  separately in ADR-0016 (proposed).
- **F3b** (schema audit): `MetadataDiscoveryService` upstream parameter metadata
  normalization could move into `service/validation/` for reuse across bulk
  import and CLI paths.
- **F4** (convention): update `service/api/local_app.py::register_server` to
  use the same `RegisterService.register()` delegation — currently still has
  the old inline pattern. Symmetric change to C4 but local-runtime-only.
