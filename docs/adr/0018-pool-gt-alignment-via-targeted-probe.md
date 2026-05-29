# ADR-0018: Pool↔GT Alignment via Targeted MCP Probe Infrastructure

**Date**: 2026-04-19  
**Status**: accepted  
**Extends**: ADR-0013 (Pool-GT Alignment Policy)  
**Related**: ADR-0017 (Hybrid Retrieval Rollout), ADR-0019 (Holistic Pool Refresh)  

---

## Context

Data-validation CI gate (`.github/workflows/data-validation.yml`, commit `2ff7525`) surfaces **321 pre-existing pool↔GT tool_id alignment errors** blocking PR #73 (hybrid retrieval rollout). Errors span:
- `yahoo-finance::*` (56 synthetic GT rows referencing a server not in the pool)
- `github::get_commit` (tool renamed to `github::list_commits`)
- Long-tail tool renames and server evictions

**Prior art**: ADR-0013 (2026-04-02) introduced GT-first pool ordering and the alignment validator script (`scripts/validate_pool_gt_alignment.py`), but only validates existing pools against existing GT — it does NOT reconcile or probe live MCP servers.

**Baseline protection**: Prod hybrid retrieval is live (R@3 46.8% on `mcp_tools_hybrid`). This PR must NOT invalidate that baseline.

---

## Decision

**Option D' (Hybrid + Commitment)**: Build a targeted probe + reconcile infrastructure in this PR to surface and validate the 321 errors with an audit trail, while committing to the full 320-server sweep via ADR-0019 stub + `workflow_dispatch`-only nightly skeleton in the same PR. This unblocks PR #73 and establishes the deterministic, audit-trailed foundation for the follow-up.

**Rejected alternatives**:
- **A**: Drop 321 rows — no audit trail, abandons "singularity refresh" intent.
- **B**: Full sweep now — scope 10×, baseline invalidated, delays PR #73 indefinitely.
- **C**: Allowlist CI skip — violates audit/determinism principles.

---

## Drivers

1. **Audit-trailed data changes** — Every GT mutation must trace to a probe SHA or explicit manual remap, preserving reproducibility and enabling rollback.
2. **Preserve baseline integrity** — The hybrid rollout's R@3 46.8% baseline is production fact; do not invalidate it unless explicitly approved.
3. **Determinism at CI time** — Failures must be reproducible; expensive operations (live MCP probes) happen at author time, not CI.
4. **Fail closed on unknowns** — TRANSPORT_UNSUPPORTED errors do not auto-drop GT rows; they require manual review or a live probe outcome.
5. **Sufficient surface to unblock PR #73** — Infra + tests + ADRs land in this PR; execution (Phase 5: running probes, committing data) happens in a follow-up author-time step.

---

## Why Option D' (Hybrid + Commitment)

Option D' is the minimal architectural delta that satisfies all drivers:
- **Scope boundary**: Probe harness, reconciler, audit trail, scripts, seed configs, ADRs, nightly skeleton, tests live **in this PR**.
- **Author-time execution**: Running the actual MCP probes, inspecting review_queue, committing reconciled data happens **after team merge**, in Phase 5.
- **Follow-up clarity**: ADR-0019 stub + `workflow_dispatch` nightly skeleton commit to the holistic follow-up without waiting for merge.
- **Baseline safety**: No data commits in this PR; baseline remains untouched until author manually runs Phase 5 and PR #73 CI validates the reconciled state.

---

## Architecture

### Modules (all under `src/mcp_discovery/` + `scripts/` + `data/probes/`)

**Models** (`src/mcp_discovery/models/probe.py`):
- `ProbeResult` — output of a single probe attempt; includes `server_offered_protocol_version: str | None` and `error_kind: ProbeErrorKind | None`.
- `ReconcilePlan` — plan schema (version="1"); orchestrates R2→R1→R4→R3→R5 ordering; includes `manual_remap_sha`, `probe_snapshots_sha`, `generated_at`.
- `RawToolInventory` — flexible tool representation (pydantic `extra="allow"`); stores probe results before MCPTool validation.
- `ProbeErrorKind` — enum: `TRANSPORT_UNSUPPORTED`, `AUTH_REQUIRED`, `TIMEOUT`, `HANDSHAKE_FAILED`, `PROTOCOL_VERSION_MISMATCH`, `UNREACHABLE`, `SCHEMA_INVALID`.
- `TransportSpec` — Pydantic discriminated union; pins MCP server versions explicitly (e.g., `"npx -y @modelcontextprotocol/server-fetch@0.6.2"` — **no `latest`**).

**Probers** (`src/mcp_discovery/data/probers/`):
- `base.py` — `Prober` ABC with `probe(server_id, spec)` and `supports(spec)`.
- `stdio_prober.py` — launches stdio servers; delegates to `MCPDirectConnector.parse_tools`.
- `http_prober.py` — connects to HTTP transports; delegates to `MCPDirectConnector.parse_tools`.
- `script_prober.py` — fallback (TRANSPORT_UNSUPPORTED); documents manual probe requirements.
- `pool_prober.py` — orchestrator: `ProberRegistry` dict, split semaphore (stdio=2, http=8), secret-scan, content-hash cache.

**Reconciliation** (`src/mcp_discovery/data/`):
- `transport_spec.py` — YAML loader; rejects `@pkg@latest` pins.
- `transports.yaml` — seed for targeted_set servers; version-pinned.
- `reconcile_rules.py` — 5 pure functions: `manual_remap`, `exact_id_match`, `server_renamed`, `rename_via_fuzzy`, `drop_if_server_missing`.
- `gt_reconciler.py` — orchestrator; applies rules in order R2→R1→R4→R3→R5.
- `audit_trail.py` — `AuditJournal` with SHA256 hash chain; rebase-safe (over JSONL line content, not git blobs).

**Scripts** (`scripts/`):
- `refresh_pool.py` — orchestrator; **refuses** baseline-impacting operations with `BASELINE_IMPACT_REFUSED`.
- `refresh_pool_with_reindex.py` — escape hatch; requires `--confirm-baseline-resuperseded ADR-NNNN` (regex validation + file existence check).
- `apply_gt_reconcile.py` — consumes `ReconcilePlan`; writes `*.bak-pre-reconcile-<sha>` backups.
- `rollback_reconcile.py` — inverts a plan via inverse journal entries.
- `verify_audit_trail.py` — CLI wrapper for chain verification.
- `check_transport_pin_freshness.py` — advisory; consumed by nightly workflow.

**Data Seeds** (`data/probes/`):
- `transports.yaml` — explicit versions for all targeted_set servers.
- `manual_remaps.yaml` — seed: `github::get_commit → github::list_commits`.
- `targeted_set.txt` — plain-text list of server_ids implicated in 321 errors.
- `journal.jsonl` — append-only audit log (CODEOWNERS: main only).

### Key Design Constraints

- **Prober ABC** ensures all concrete probers share a consistent interface; no dynamic registration (unlike `StrategyRegistry` — probers are a small, closed set).
- **Split semaphore**: `stdio_sem = asyncio.Semaphore(2)`, `http_sem = asyncio.Semaphore(8)`. ScriptProber uses `stdio_sem` for fairness.
- **Secret-scan** (pre-write): keyword + high-entropy adjacency `(?i)\b(token|key|auth|secret|bearer)\b.*?[A-Za-z0-9_\-]{32,}` — NOT bare keywords. Fail-write on match; log key name only (value redacted).
- **Content-hash cache**: `data/probes/.cache/<sha256(spec.model_dump_json())>.json`, 24h TTL, gitignored. `--force` bypasses.
- **Hash chain** (audit trail): `AuditJournal.append(entry)` computes `sha256(prev_hash + current_line_json)`. Rebase-safe: verification over JSONL line content, NOT git blobs.
- **Sandbox for stdio**: `asyncio.create_subprocess_exec` with `env = {"PATH": ..., "HOME": tempdir}`, `--ignore-scripts`, hard timeout, no shell, no inherited PATH beyond node/npm. Protocol-only: `initialize` + `tools/list` (never `tools/call`).
- **MCPTool validation preserved**: `RawToolInventory` allows `extra="allow"` for probe flexibility; `MCPTool` at `models/core.py:66` remains `extra="forbid"` (unchanged).

### Reconciliation Rules (5 pure functions, applied R2→R1→R4→R3→R5)

1. **R2 manual_remap** — entry in `data/probes/manual_remaps.yaml` → apply (**first priority**, wins all other rules).
2. **R1 exact_id_match** — GT `correct_tool_id` exists in pool → preserve.
3. **R4 server_renamed** — explicit server-level remap via `manual_remaps.yaml` → apply.
4. **R3 rename_via_fuzzy** — fuzzy `difflib.SequenceMatcher.ratio() ≥ 0.88` on normalized names → auto-rename. Band 0.80–0.88 → review_queue (manual review required).
5. **R5 drop_if_server_missing** — server not in pool AND probe failed/not attempted → drop GT row with `notes += "[reconcile: <reason> sha=<probe_sha>]"`.

**Idempotence invariant**: `reconcile(reconcile(x)) == reconcile(x)` when `manual_remaps.yaml` is stable.

**Fuzzy calibration**: derived from 14 known rename pairs; 0.88 separates all 14 TPs from FP cluster at 0.82–0.85. Test fixtures lock this with ≥3 TP + ≥3 FP.

---

## Consequences

### Positive
- **Audit trail**: Every GT change traces to probe SHA or manual_remap, enabling rollback and reproducibility.
- **Determinism**: live probes happen at author time; CI remains deterministic.
- **Baseline safety**: No data commits in this PR; R@3 46.8% baseline untouched until Phase 5.
- **Infrastructure ready**: After merge, author can reconcile 321 errors with one command (`refresh_pool.py --servers-from data/probes/targeted_set.txt`).
- **Commitment artifact**: ADR-0019 stub + nightly skeleton document follow-up; no dead code (workflow_dispatch-only, tripwire acceptance gate).

### Negative / Trade-offs
- **Author-time effort**: Phase 5 (running probes, inspecting review_queue, committing data) is manual; not automated by CI.
- **Scope split**: Probe harness + tests land now; data reconciliation happens later. Requires discipline to not forget Phase 5.
- **Review queue maintenance**: If fuzzy band (0.80–0.88) surfaces review_queue entries, author must manually edit `manual_remaps.yaml` and re-run.

---

## Phase 5 (Author-time, documented in runbook)

After team PR merges, author runs locally:
```bash
uv run python scripts/refresh_pool.py \
  --servers-from data/probes/targeted_set.txt \
  --output-plan /tmp/plan.json

# Inspect review_queue; edit manual_remaps.yaml if needed
uv run python scripts/apply_gt_reconcile.py --plan /tmp/plan.json

# Rebuild GT-first base_pool.json (ADR-0013)
uv run python scripts/build_base_pool.py

# Quality gate
uv run python scripts/verify_ground_truth.py

# Full alignment report
uv run python scripts/validate_pool_gt_alignment.py \
  --pool-sizes 5 20 50 100 200 292 \
  --json-out data/results/alignment_report.json

# Commit data with plan-hash in message
git add data/ground_truth/*.jsonl data/probes/journal.jsonl
git commit -m "data: reconcile pool-GT alignment (plan-hash: <sha>)"
```

---

## Verification

**Team-verifiable** (this PR):
- All new modules pass ≥80% coverage unit tests.
- No `print()`, `logging`, or `requests` in new code (only `loguru`).
- `ruff check` and `ruff format --check` pass.
- Prober ABC + 3 concretes + registry wired and tested.
- `ReconcilePlan.schema_version == "1"` (Literal type).
- Fuzzy calibration ≥6 fixtures (≥3 TP + ≥3 FP) pass at 0.88.
- `PROTOCOL_VERSION_MISMATCH` enum + `server_offered_protocol_version` field exist.
- Rollback script tested.
- Split semaphore verified (stdio=2, http=8).
- `transports.yaml` seeded; versions pinned (no `latest`).
- Secret-scan regex tested (keyword+high-entropy, NOT bare "API key").
- `.gitignore` updated: `data/probes/.cache/`, `data/probes/snapshots/*`.
- Integration roundtrip test (3-server fixture) passes.

**Author-verifiable** (Phase 5, NOT team):
- Validator exits 0 on reconciled HEAD.
- Every GT change traces to probe SHA or manual_remap.
- Qdrant-indexed tool set bit-identical (baseline untouched).
- `base_pool.json` rebuilt (GT-first order preserved).
- Alignment report thresholds met (25% / 20 / 50% skew).

---

## Acceptance Criteria

- AC1-AC36: See plan (full list in `.omc/plans/2026-04-19_pool-gt-reconcile.md`). Team verifies AC6-AC32; author verifies AC1-AC5, AC33-AC36 in Phase 5.

---

## References

- ralplan iter 2 consensus (Planner + Architect + Critic)
- ADR-0013: Pool-GT Alignment Policy
- ADR-0017: Hybrid Retrieval Rollout (extends baseline decision)
- ADR-0019: Holistic Pool Refresh (stub + tripwire in follow-up PR)
- Plan: `.omc/plans/2026-04-19_pool-gt-reconcile.md`
- Current validator: `scripts/validate_pool_gt_alignment.py`
- Canonical tool parser: `src/mcp_discovery/data/mcp_connector.py:19`
- Strict MCPTool: `src/mcp_discovery/models/core.py:66`
