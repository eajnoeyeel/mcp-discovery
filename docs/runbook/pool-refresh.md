# Runbook: Pool-GT Alignment Refresh (ADR-0018)

**Last updated**: 2026-04-19  
**Related**: ADR-0013, ADR-0018, ADR-0019, `docs/design/external-dataset-checklist.md`

---

## Overview

This runbook documents the full workflow for refreshing pool↔GT alignment using the targeted probe infrastructure introduced in ADR-0018. Follow this procedure when alignment errors are discovered (e.g., missing servers, tool renames, stale tool_ids).

**Key principle**: All data changes must be audit-traced (probe SHA or manual remap) for reproducibility and rollback.

---

## Prerequisites

- Repo on `feat/hybrid-search-rollout` or later (ADR-0018 merged)
- `.env` configured: `OPENAI_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`
- Node.js ≥25.0 (for MCP stdio probes)
- `uv` package manager installed
- 30–60 minutes for a targeted 320-server sweep

---

## Phase 1: Identify Alignment Errors

```bash
# Run the alignment validator to find errors
uv run python scripts/validate_pool_gt_alignment.py \
  --pool data/raw/mcp_zero_servers.jsonl \
  --gt data/ground_truth/*.jsonl \
  --pool-sizes 5 20 50 100 200 292 \
  --json-out data/results/alignment_report.json
```

**Interpretation**:
- `covered_servers` — how many GT-referenced servers are in the pool
- `missing_servers` — servers referenced in GT but absent from pool
- `query_distribution` — coverage by pool size
- Errors are listed with `correct_server_id` and `correct_tool_id`

---

## Phase 2: Build Targeted Server Set

1. Extract server_ids from alignment errors:
   ```bash
   # Manual inspection or:
   jq '.errors[] | .correct_server_id' data/results/alignment_report.json | sort -u > /tmp/error_servers.txt
   ```

2. Add known problem servers (e.g., `yahoo-finance`, servers with tool renames). Update `data/probes/targeted_set.txt`:
   ```
   github
   yahoo-finance
   ... (more servers)
   ```

3. Verify `data/probes/transports.yaml` has entries for all targeted servers with **version-pinned** transports (no `latest`):
   ```yaml
   github:
     type: stdio
     command: "npx -y @modelcontextprotocol/server-github@0.5.1"
   ```

---

## Phase 3: Probe Live MCP Servers

Run the targeted probe orchestrator:

```bash
uv run python scripts/refresh_pool.py \
  --servers-from data/probes/targeted_set.txt \
  --output-plan /tmp/plan.json \
  --dry-run
```

**Options**:
- `--dry-run` (default): simulate probes, don't write to disk
- `--output-plan PATH`: save `ReconcilePlan` JSON
- `--force` (careful): bypass content-hash cache, re-probe all servers

**Output**:
- `ReconcilePlan` with probe results + reconciliation rules (R2→R1→R4→R3→R5 ordering)
- `review_queue` entries for fuzzy-matched tool renames (0.80–0.88 score band)
- Audit trail entry (SHA256 hash chain)

---

## Phase 4: Review & Approve Reconciliation Plan

1. Inspect the plan:
   ```bash
   jq '.probe_snapshots | keys' /tmp/plan.json  # Servers probed
   jq '.reconciliation.review_queue' /tmp/plan.json  # Manual review needed?
   ```

2. **If review_queue has entries** (fuzzy-matched renames):
   - Inspect each entry: `{query: orig_tool_id, match: suggested_tool_id, score: N.NN}`
   - If the suggestion is correct, add to `data/probes/manual_remaps.yaml`:
     ```yaml
     github::get_commit: github::list_commits  # confirmed rename
     server::old_tool: server::new_tool  # add from review_queue
     ```
   - Re-run refresh_pool to recompute the plan (manual_remap R2 takes priority)

3. **If review_queue is empty**: proceed to Phase 5.

---

## Phase 5: Apply Reconciliation & Commit Data

1. Apply the reconciliation plan:
   ```bash
   uv run python scripts/apply_gt_reconcile.py \
     --plan /tmp/plan.json \
     --dry-run
   ```
   
   Inspect the changes:
   - `Added N rows` — newly reconciled tool_ids from probes
   - `Dropped K rows` — servers no longer in pool, probes failed, or unrecoverable
   - `Renamed M rows` — fuzzy or manual remaps applied

2. Confirm the dry-run output, then apply without `--dry-run`:
   ```bash
   uv run python scripts/apply_gt_reconcile.py --plan /tmp/plan.json
   ```
   
   Creates backups: `data/ground_truth/*.bak-pre-reconcile-<sha>`

3. Rebuild pool and validate:
   ```bash
   # Rebuild base_pool.json with GT-first ordering (ADR-0013)
   uv run python scripts/build_base_pool.py
   
   # Quality gate
   uv run python scripts/verify_ground_truth.py
   
   # Full alignment report
   uv run python scripts/validate_pool_gt_alignment.py \
     --pool-sizes 5 20 50 100 200 292 \
     --json-out data/results/alignment_report.json
   ```

4. Verify audit trail integrity:
   ```bash
   uv run python scripts/verify_audit_trail.py data/probes/journal.jsonl
   ```

5. Stage and commit all data:
   ```bash
   git add data/ground_truth/*.jsonl data/probes/journal.jsonl
   git commit -m "data: reconcile pool-GT alignment via targeted probe (plan-hash: <sha>)"
   ```

---

## Phase 6: Validate Baseline Integrity

**Critical**: Ensure the hybrid retrieval baseline (R@3 46.8%) is not invalidated.

```bash
# If you're on the service/ Lambda platform:
cd service/
make local-test-search  # Spot-check search latency + RECALL_AT_3

# Or run E0 baseline:
uv run python scripts/run_e0.py
```

Expected: R@3 ≥ 45% (allows ≤1.8pp drift from 46.8%).

---

## Rollback Procedure

If alignment validation fails (Phase 5) or baseline is invalidated:

1. Restore from backup:
   ```bash
   ls data/ground_truth/*.bak-pre-reconcile-*
   for f in data/ground_truth/*.bak-pre-reconcile-*; do
     mv "$f" "${f%.bak-pre-reconcile-*}.jsonl"
   done
   ```

2. Or use the rollback script:
   ```bash
   uv run python scripts/rollback_reconcile.py \
     --journal data/probes/journal.jsonl \
     --last-entry-count 1
   ```

3. Rebuild and re-validate:
   ```bash
   uv run python scripts/build_base_pool.py
   uv run python scripts/verify_ground_truth.py
   ```

---

## Common Issues

### Issue: `ProbeErrorKind.TRANSPORT_UNSUPPORTED`

**Cause**: Server transport not listed in `data/probes/transports.yaml` or not supported by local probers.

**Fix**:
1. Check if server requires HTTP, stdio, or script probe
2. Add or update `data/probes/transports.yaml`
3. If truly unsupported, add to `manual_remaps.yaml` with a note, or drop via manual reconcile rule

### Issue: `TIMEOUT` on stdio probes

**Cause**: MCP server slow to initialize or unresponsive.

**Fix**:
1. Test manually: `npx -y @modelcontextprotocol/server-X` (check for errors)
2. Increase timeout in `pool_prober.py` (default 30s)
3. Consider scripting the probe or marking as "review_queue"

### Issue: Review queue has many entries (fuzzy score 0.80–0.88)

**Cause**: Tool naming conventions changed or many tools were renamed at once.

**Fix**:
1. Inspect entries: `jq '.reconciliation.review_queue[]' /tmp/plan.json`
2. Batch-add correct remaps to `data/probes/manual_remaps.yaml`
3. Re-run `refresh_pool.py` (manual_remap R2 takes priority)
4. Recompute plan and re-apply

### Issue: Validator still reports errors after apply

**Cause**: Reconciliation didn't cover all error paths (e.g., tool still missing).

**Fix**:
1. Re-run `validate_pool_gt_alignment.py` to get fresh error list
2. Check if new servers need probing or existing servers have newer versions
3. Update `targeted_set.txt` and re-probe

---

## Review & Approval (2-Reviewer Rule)

**Per CODEOWNERS**:
- Changes to `data/ground_truth/` require 2 reviewers
- Changes to `data/probes/manual_remaps.yaml` require approval from maintainer + probe infrastructure owner

**Checklist for reviewers**:
- [ ] Audit trail (journal.jsonl) passes `verify_audit_trail.py`
- [ ] No manual_remap entries without rationale in commit message or issue
- [ ] Alignment report shows coverage ≥ 25%, skew < 50%
- [ ] No hardcoded secrets in reconcile logs

---

## Pin Freshness Maintenance (Nightly Workflow)

After this reconciliation, pin freshness must be monitored:

```bash
uv run python scripts/check_transport_pin_freshness.py \
  --transports data/probes/transports.yaml
```

If pins are >3 months old and new versions available:
1. Update `data/probes/transports.yaml` with new pins (test locally first)
2. Run targeted probe again
3. Evaluate impact on Recall@K baseline
4. Commit if no regression

---

## References

- `docs/design/external-dataset-checklist.md` — Phase 1–4 alignment gates
- `docs/adr/0018-pool-gt-alignment-via-targeted-probe.md` — architecture + rules
- `docs/adr/0013-pool-gt-alignment-policy.md` — GT-first ordering, validation
- `scripts/refresh_pool.py` — probe orchestrator
- `src/mcp_discovery/data/reconcile_rules.py` — R1–R5 reconciliation rules
- `src/mcp_discovery/data/audit_trail.py` — hash chain + verification
