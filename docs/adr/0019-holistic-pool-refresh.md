# ADR-0019: Holistic Pool Refresh (Full 320-Server Sweep)

**Date**: 2026-04-19  
**Status**: Proposed  
**Related**: ADR-0018 (Pool-GT Alignment via Targeted Probe Infrastructure), ADR-0013 (Pool-GT Alignment Policy)

---

## Context

ADR-0018 introduces a targeted probe + reconcile infrastructure in PR #73 to unblock the hybrid retrieval rollout. That PR reconciles the **321 known alignment errors** (yaml-finance, github rename, long-tail) and commits to a follow-up sweep of the **full 320-server pool** to holistically refresh alignment and operator confidence.

This ADR formally proposes that follow-up work.

---

## Decision

**[TBD in follow-up PR]**

---

## Consequences

**[TBD in follow-up PR]**

---

## Acceptance Tripwire (MANDATORY)

> This ADR must be explicitly **Accepted** or **Rejected** within **8 weeks of ADR-0018 merge** (deadline: 2026-06-14), **or the `workflow_dispatch`-only nightly workflow added in PR #73 will be removed as dead code** in a subsequent PR.
>
> If acceptance is blocked or delayed beyond 8 weeks:
> 1. Remove `.github/workflows/pool-refresh-nightly.yml`.
> 2. Remove `scripts/refresh_pool.py`, `scripts/refresh_pool_with_reindex.py`, `scripts/rollback_reconcile.py`, `scripts/check_transport_pin_freshness.py`.
> 3. Archive `data/probes/` to `data/archive/probes-adr0018/`.
> 4. Close ADR-0019 as "Rejected" with rationale.

This tripwire ensures that the infrastructure added in ADR-0018 remains a committed follow-up, not a technical debt artifact.

---

## Follow-up PR Scope (Informational)

The accepted form of ADR-0019 will address:
- Probe all 320 servers in pool (not just targeted_set).
- Commit reconciled ground-truth JSONL with full audit trail.
- Rebuild `base_pool.json` and run `verify_ground_truth.py`.
- Run `validate_pool_gt_alignment.py --pool-sizes 5 20 50 100 200 292` and commit report.
- Enable cron trigger (`schedule:`) on nightly workflow if alignment confidence ≥ threshold.
- Archive Phase 5 notes for future maintainers.

---

## References

- ADR-0018: Pool-GT Alignment via Targeted Probe Infrastructure
- ADR-0013: Pool-GT Alignment Policy
- Plan: `.omc/plans/2026-04-19_pool-gt-reconcile.md`
