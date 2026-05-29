# ADR-0017: Hybrid Retrieval Rollout (Dense + SPLADE + Qdrant RRF)

**Date**: 2026-04-18
**Status**: Accepted
**Supersedes**: extends ADR-0003 (Pipeline Strategy Pattern) and ADR-0005 (Gap-Based Confidence Branching)
**Related**: ADR-0004 (Qdrant Cloud Vector Store), ADR-0010 (Server Description Source for Embedding)
**Design Spec**: [`docs/superpowers/specs/2026-04-18-hybrid-search-retrieval-design.md`](../superpowers/specs/2026-04-18-hybrid-search-retrieval-design.md)

---

## Context

The live retrieval path is dense-only (`FlatStrategy` with `sparse_embedder=None` at `service/shared/runtime.py:44-48`), even though:

- The 2026-04-11 hybrid experiment (`docs/experiments/hybrid-search-report.md`) established Recall@3 **21.5% → 46.6%** (+25.1pp) using the Keyword+LLM sparse input recipe.
- The sparse-branch code path at `src/mcp_discovery/pipeline/flat.py:44-49` is implemented but dead in production — `sparse_embedder` is never injected.
- Enriched 2,898-tool corpus `data/enriched/tool_profiles.jsonl` is committed and ready to index.
- Hosting feature onboarding is imminent; launching hosting into a dense-only retrieval world forfeits experiment-prod parity and the thesis "higher description quality → higher tool selection rate."

Five principle audit gaps (P5/P6/P7/P8/P12 per `docs/design/serverless-architecture-principles.md`) also require closure.

---

## Decision

Adopt **Option A**: inline SPLADE in Search + Index Lambdas using Lambda **container image** packaging, with Qdrant server-side RRF fusion over a blue/green-cut `mcp_tools_hybrid` collection. Pre-design **Option B** (dedicated Sparse Embedder Lambda with Provisioned Concurrency) as the documented automatic fallback activated by measurable validation-gate failures.

Changes are confined to:
- Lambda runtime wiring (`service/shared/runtime.py`, `service/lambdas/{search,index}/handler.py`, `service/services/index_service.py`, `service/rag/service.py`).
- Four additive/scoped extensions in `src/mcp_discovery/*` (read-only rule explicitly relaxed for this rollout; see Consequences).
- New `src/mcp_discovery/indexing/enrichment.py` module (Control Plane concern; no collision with existing `description/` Client-Optimization package).
- New Supabase table `tool_enrichment_cache` keyed by content hash (P5 idempotency).
- SAM template: SearchFunction + IndexFunction `PackageType: Image`; rest of fleet unchanged.

---

## Drivers

1. **Experiment-prod parity** — Reproduce `hybrid-search-report.md` §6.2 Keyword+LLM R@3 ≥ 45% (46.6% experiment, −1.6pp tolerance for pool drift) in staging against production infrastructure.
2. **Completeness before hosting** — New hosted tools must enter the hybrid index on registration; otherwise hosting launches into a split retrieval world and forfeits the "description quality → selection" validation the platform promises providers.
3. **Operational safety** — Reversible (blue/green env-var flip), observable (stage_metrics + `source_path`), degradable (rule-based sparse + dense-only fallbacks). A broken hybrid rollout in a pre-hosting product is a credibility event.

---

## Alternatives Considered

| Alternative | Verdict | Rationale |
|-------------|---------|-----------|
| **A-ZIP**: Option A packaging as Lambda ZIP | Rejected | SPLADE ONNX model (~266-532 MB) exceeds combined ZIP+Layer 250 MB unzipped limit. |
| **B**: Dedicated Sparse Embedder Lambda | Preserved as fallback | Higher operational overhead (new Lambda, provisioned concurrency ~$10-15/mo, +5-10ms network hop). Acceptable if Option A fails measurement gates; pre-specified template deltas ready for ≤1-day pivot. |
| **C**: Keep dense-only + Qdrant BM25 | Rejected | Experiment §3.2 showed BM25 independence prediction R@3 = 43.8% vs SPLADE 48.9%. Discards vocabulary expansion; violates Driver #1. |
| **Pure LLM enrichment (no keyword prefix)** | Rejected | Experiment §6.2 showed Confusion 28.2% (+6.6pp worse) and P@1 25.6% (-6.3pp worse) than Keyword+LLM. |
| **Client-side RRF fusion** | Rejected | Doubles network cost, re-implements tested Qdrant server-side logic, loses prefetch optimisation. |
| **ParallelStrategy + sparse** | Rejected | `recall-k-baseline-report.md` showed ParallelStrategy R@3 20.1% vs Flat 21.5% — Flat is correct base. |

---

## Why Option A (Container Image) Chosen

Container-image Option A is the smallest architectural delta from the validated experiment while honouring all P1-P12 constraints and AWS Well-Architected principles. Container packaging (10 GB limit) is the only deploy mode that actually fits SPLADE within Lambda limits. It reuses every committed asset (`tool_profiles.jsonl`, `build_hybrid_index.py`, existing `QdrantStore.hybrid_search` + `upsert_tools_hybrid`) and leaves a one-env-var rollback path. The P5/P6/P7/P8/P12 principle-audit gaps are explicitly closed in the design spec §4. Option B is pre-specified so any Phase-2 validation failure pivots in ≤ 1 day without redesign effort.

---

## Consequences

### Positive
- Recall@3 baseline rises from 21.5% to ~46.6% (Keyword+LLM actual).
- `source_path` and `ScoreBreakdown` become explainable to Provider Dashboard drill-downs.
- `stage_metrics` gains per-stage latency decomposition (`dense_embed_ms`, `sparse_embed_ms`, `qdrant_hybrid_ms`, `total_ms`, `cache_hit`, `sparse_used`).
- LLM enrichment is idempotent (P5) via `tool_enrichment_cache` content-hash skip; bounds OpenAI cost and survives retry.
- Rollout is reversible with a single SAM env-var flip; old `mcp_tools` collection preserved ≥7 days.

### Negative / Trade-offs
- **CI/CD bifurcation**: SearchFunction + IndexFunction migrate to container-image deployment; the other 11 Lambdas remain ZIP. `service/build/` Makefile targets must handle both modes. ECR repository must be provisioned and managed (image retention, scanning).
- **Cold start regression**: +500 ms typical for container image vs ZIP; projected cold p95 ~1.8 s (within 2 s gate). Mitigated by existing 5-min warming rule on SearchFunction.
- **`src/mcp_discovery/*` read-only rule relaxation (scoped)**: Four files receive additive, backward-compatible changes with no behavioural drift to existing callers:
  1. `retrieval/qdrant_store.py:279` — `upsert_tools_hybrid` gains keyword-only `extra_payloads: list[dict] | None = None`.
  2. `models/core.py` — `ScoreBreakdown` gains `dense_score`, `sparse_score`, `rrf_score` as `float | None = None`; shared `SourcePathLiteral` alias applied to both `SearchResult.source_path` and `FindBestToolResponse.source_path` (which previously had divergent Literal annotations).
  3. `pipeline/confidence.py:20` — `compute_confidence` gains keyword-only `strategy_hint: str = "dense"`.
  4. `pipeline/flat.py:44-46` — synchronous `sparse_embedder.embed_one(query)` replaced with `asyncio.gather(dense_task, asyncio.to_thread(sparse_fn, query))` so SPLADE CPU work never blocks the event loop. Strategy ABC signature unchanged.

  Plus one new package `src/mcp_discovery/indexing/` with `enrichment.py` — purely additive.

  Scope of relaxation: **additive parameters, optional fields, and new modules only; no behavioural change to existing callers**. Future work remains bound by the read-only rule unless an ADR revisits it.
- **Index Lambda runtime**: cold p95 ~5 s, warm p95 ~5 s (LLM enrichment dominates). Acceptable because Index is Control Plane (async, not user-visible).
- **Qdrant Cloud named-vector storage overhead**: projected ≤40% of 1 GiB free-tier RAM. Explicit action threshold defined (reduce prefetch_limit or upgrade tier if RAM >70%).
- **Option B standby cost** (if triggered): ~$10-15/mo Provisioned Concurrency.

### North Star update
Post-rollout, root `CLAUDE.md` and `docs/design/north-star-realignment.md` R@3 target rises from 21.5% to **46.6%** (Keyword+LLM actual). Recorded in design spec §14.

---

## Follow-ups

- Remove blue `mcp_tools` collection 7+ days after prod rollout.
- Dense-only code paths gated by `MCP_DISCOVERY_SPARSE_DISABLED` flag for one release, then removed.
- Backfill `tool_enrichment_cache` for tools absent from current `tool_profiles.jsonl` (delta enrichment during Phase 1).
- Recalibrate `confidence_gap_threshold_hybrid` based on RRF distribution file `data/results/rrf_distribution.json` produced during validation (design spec §4.8). Conservative fallback `0.005` if distribution lacks a clean elbow.
- Post-hosting: reassess Option B if registration burst patterns cause SearchFunction or IndexFunction pressure.
- Separate design work: Provider Dashboard E4v2b conditional description rules (not part of this rollout).

---

## Acceptance Criteria (condensed — full list in design spec §9)

- Pool-filtered R@3 ≥ 45%, P@1 ≥ 28%, Confusion ≤ 26%, MRR ≥ 0.35 (against `mcp_tools_hybrid` staging).
- SearchFunction cold p95 ≤ 2 s, warm p95 ≤ 400 ms, container image ≤ 600 MB.
- IndexFunction handles 100-tool burst with DLQ depth < 5.
- E2E: register → EventBridge → Index → Search retrieval ≤ 30 s p95.
- Rollback drill performed in staging before prod flip.
- `source_path ∈ {hybrid_semantic, dense_only_degraded, lexical_fallback, mixed, semantic, freshness}` correctly emitted.

---

## References

- Design spec: [`docs/superpowers/specs/2026-04-18-hybrid-search-retrieval-design.md`](../superpowers/specs/2026-04-18-hybrid-search-retrieval-design.md)
- Planner draft + iteration history: `.omc/plans/2026-04-18-hybrid-search-retrieval-design.md`
- Experiment evidence: `docs/experiments/hybrid-search-report.md`
- Baseline evidence: `docs/experiments/recall-k-baseline-report.md`
- Oracle: `docs/design/serverless-architecture-principles.md`
- Existing library code: `src/mcp_discovery/pipeline/flat.py`, `src/mcp_discovery/retrieval/qdrant_store.py`, `src/mcp_discovery/embedding/fastembed_sparse.py`
