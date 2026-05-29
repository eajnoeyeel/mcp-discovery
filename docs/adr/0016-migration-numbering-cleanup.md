# ADR-0016: Migration numbering cleanup (duplicate 020/021 filenames)

**Date**: 2026-04-17
**Status**: proposed
**Deciders**: 이연재

> ⚠️ **NOT EXECUTED — COORDINATION REQUIRED**
>
> This ADR records a **proposed** cleanup only. Do NOT rename any files in
> `service/supabase/migrations/` until the Coordination Checklist at the bottom
> of this document is fully satisfied in a dedicated follow-up PR.
>
> The target filenames are already applied in shared prod Supabase and are
> referenced by the `supabase_migrations.schema_migrations` table under their
> current names. Renaming on disk without a coordinated DB-side update will
> cause the Supabase CLI to treat the renamed files as unseen migrations and
> attempt re-application on the next `supabase db push`, risking duplicate
> `CREATE TABLE` / `ALTER TABLE` DDL against shared infrastructure.

## Context

`service/supabase/migrations/` currently contains duplicate numeric prefixes:

- `020_http_mcp_metadata_overrides.sql` collides with `020_mv_to_view.sql`
- `021_http_mcp_parameter_metadata.sql` collides with `021_analytics_views_fix.sql`

Both 020s and both 021s are already applied in shared prod Supabase. The
Supabase CLI uses the filename as the version key in
`supabase_migrations.schema_migrations`; two files sharing a numeric prefix
are applied in filesystem sort order (alphabetical on full filename), which
means `020_http_*` runs before `020_mv_*`, and `021_analytics_*` runs before
`021_http_*`. This has worked to date because all four migrations are
idempotent (ALTER TABLE IF NOT EXISTS etc.), but:

1. Supabase CLI tooling, `alembic`-style migration frameworks, and developer
   intuition all assume **monotonic unique prefixes**. Future tooling changes
   or a new developer running migrations for the first time on a fresh env
   may land in a non-deterministic ordering.
2. `git log service/supabase/migrations/` becomes ambiguous when two
   migrations share a prefix. Bisecting which migration introduced a given
   schema change requires opening the file.
3. Onboarding contributors shouldn't have to discover the duplication
   empirically after their first failed push.

## Decision

Reserve new monotonic unique numbers for the non-canonical siblings and
rename:

- `020_mv_to_view.sql` → `024_mv_to_view.sql`
- `021_analytics_views_fix.sql` → `025_analytics_views_fix.sql`

(`022_metric_semantic_redesign.sql` and `023_mcp_tools_add_event_failed_status.sql`
are already taken, hence 024/025.)

The HTTP-MCP metadata migrations (`020_http_mcp_metadata_overrides.sql` and
`021_http_mcp_parameter_metadata.sql`) retain their current numbers since
their ordering aligns with the feature-commit chronology of the parameter-
metadata discovery work.

This decision is **proposed** and does not land file renames in the same PR
as this ADR.

## Alternatives Considered

### Alternative 1: Leave as-is

- **Pros**: Zero risk; no coordination overhead; migrations are already
  idempotent.
- **Cons**: Future collision at 020/021 (e.g., a new developer adds a third
  020_*.sql); tooling hazard grows as the migration directory expands; PR
  diffs touching these migrations are ambiguous.
- **Why not**: Technical debt that compounds. Costs trend up while
  coordination cost stays roughly constant.

### Alternative 2: Rename the HTTP-MCP migrations instead

- **Pros**: Smaller rename delta if those migrations have fewer downstream
  references.
- **Cons**: Their numbering aligns with the chronological order of the
  parameter-metadata feature rollout (content_hash computation, metadata
  discovery, replay path). Renaming fragments the feature's git archaeology.
- **Why not**: The analytics/MV siblings were added later and are
  peripheral to the main HTTP-MCP lineage.

### Alternative 3: Rewrite history to fix numbering at commit time

- **Pros**: Clean git log; no runtime coordination.
- **Cons**: Migrations are already applied in shared prod; a git history
  rewrite doesn't update `supabase_migrations.schema_migrations`. Rewriting
  history on main also invalidates every outstanding PR branch.
- **Why not**: Addresses only the symptom in git log, leaves the DB state
  unchanged.

## Consequences

### Positive

- Monotonic unique prefixes restored across `service/supabase/migrations/`.
- Supabase CLI ordering becomes deterministic.
- `git log service/supabase/migrations/` becomes unambiguous for future
  bisection.
- Future collision-prevention CI check (see Follow-ups) can land without
  legacy exceptions.

### Negative / risks

- Requires a one-time `UPDATE supabase_migrations.schema_migrations SET
  version = '023_mv_to_view' WHERE version = '020_mv_to_view'` (and sibling
  `021_analytics_views_fix` → `024_analytics_views_fix`), coordinated across
  **every** environment (local dev, staging, prod).
- Window of risk during coordination: a mis-sequenced push of the file
  rename without the matching DB-side `UPDATE` will trigger re-application
  of already-applied DDL against prod.
- Teammates with in-flight PR branches touching these migration files will
  need to rebase.

### Risks mitigation

- Coordination Checklist below sequences the DB-side `UPDATE` **before** the
  filename rename lands on main.
- Staging dry-run gates execution.
- Execution lands as a dedicated PR authored by a single owner, not bundled
  into unrelated feature work.

## Coordination Checklist

**Prerequisite to transitioning this ADR from `proposed` to `accepted`.**

- [ ] Snapshot `supabase_migrations.schema_migrations` contents in every
      environment (local dev, staging, prod). Record the exact `version`
      strings for the four affected migrations.
- [ ] Author the matched data migration. SQL shape:
      ```sql
      UPDATE supabase_migrations.schema_migrations
        SET version = '023_mv_to_view'
        WHERE version = '020_mv_to_view';
      UPDATE supabase_migrations.schema_migrations
        SET version = '024_analytics_views_fix'
        WHERE version = '021_analytics_views_fix';
      ```
      (Exact version-string format depends on Supabase CLI version; verify
      against staging snapshot.)
- [ ] Staging dry-run: apply the `UPDATE` migration followed by the file
      rename, then run `supabase db diff` and confirm zero pending changes.
- [ ] Announce a team freeze window on migration pushes during execution.
- [ ] Identify rollback owner and document rollback SQL.
- [ ] Author **ADR-0017** transitioning this ADR (0016) from `proposed` to
      `accepted`, linking the staging dry-run evidence and the
      post-rename `schema_migrations` snapshot.
- [ ] The rename + UPDATE lands in a single PR authored by the checklist
      owner.

## Follow-ups

1. After execution (ADR-0017), add
   `tests/unit/test_migration_numbering.py` asserting unique numeric
   prefixes under `service/supabase/migrations/`. Wire into CI.
2. Consider a repo-level pre-commit hook scanning new migration files
   for duplicate prefixes.
3. Document the migration-numbering convention in `service/CLAUDE.md` or
   `CONVENTIONS.md` so future migrations don't recreate the collision.

## References

- `service/supabase/migrations/020_http_mcp_metadata_overrides.sql`
- `service/supabase/migrations/020_mv_to_view.sql` (rename target)
- `service/supabase/migrations/021_http_mcp_parameter_metadata.sql`
- `service/supabase/migrations/021_analytics_views_fix.sql` (rename target)
- `progress.txt` Follow-up #3 (source of this ADR)
- ADR-0015 (related: also a 2026-04-17 proposed follow-up from the same
  transplant; coordination status independent)
