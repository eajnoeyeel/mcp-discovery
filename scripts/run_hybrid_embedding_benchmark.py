"""Staged hybrid embedding benchmark runner.

This runner produces two explicit outputs:

- ``best_dense_under_control``: the Stage-1 winner under the frozen
  ``Keyword+LLM + SPLADE`` control stack
- ``best_tested_hybrid``: the best measured arm across all executed stages

If the control parity gate fails, the runner writes
``control_parity_failure.json`` and stops in diagnostic mode without emitting a
winner recommendation.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path
from typing import Any

from loguru import logger
from qdrant_client import AsyncQdrantClient

from mcp_discovery.config import Settings

try:
    from scripts.hybrid_benchmark_utils import (
        DEFAULT_K_VALUES,
        DEFAULT_MANIFESTS_DIR,
        DEFAULT_MATRIX_PATH,
        DEFAULT_RESULTS_ROOT,
        ArmEvaluationResult,
        BackendConfigurationError,
        BenchmarkArm,
        BenchmarkMatrix,
        ambiguity_trigger,
        build_or_reuse_arm_collection,
        check_arm_backend_availability,
        control_parity_summary,
        create_artifact_dir,
        format_parity_failure_notes,
        format_results_table,
        get_qdrant_config,
        load_and_filter_gt,
        load_benchmark_matrix,
        load_pool_server_ids,
        make_stage2a_arms,
        make_stage2b_arms,
        now_utc_iso,
        promoted_stage1_arms,
        rank_measured_results,
        run_hybrid_eval_for_arm,
        write_json,
    )
except ModuleNotFoundError:  # pragma: no cover - script execution fallback
    from hybrid_benchmark_utils import (
        DEFAULT_K_VALUES,
        DEFAULT_MANIFESTS_DIR,
        DEFAULT_MATRIX_PATH,
        DEFAULT_RESULTS_ROOT,
        ArmEvaluationResult,
        BackendConfigurationError,
        BenchmarkArm,
        BenchmarkMatrix,
        ambiguity_trigger,
        build_or_reuse_arm_collection,
        check_arm_backend_availability,
        control_parity_summary,
        create_artifact_dir,
        format_parity_failure_notes,
        format_results_table,
        get_qdrant_config,
        load_and_filter_gt,
        load_benchmark_matrix,
        load_pool_server_ids,
        make_stage2a_arms,
        make_stage2b_arms,
        now_utc_iso,
        promoted_stage1_arms,
        rank_measured_results,
        run_hybrid_eval_for_arm,
        write_json,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run staged hybrid embedding benchmark")
    parser.add_argument(
        "--matrix",
        type=Path,
        default=DEFAULT_MATRIX_PATH,
        help="Benchmark matrix JSON path",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Output directory for this run "
            "(default: timestamped under data/results/hybrid_embedding_benchmark)"
        ),
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=DEFAULT_RESULTS_ROOT,
        help="Root directory for timestamped benchmark artifacts",
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=DEFAULT_MANIFESTS_DIR,
        help="Persistent manifest directory used for deterministic collection reuse checks",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Embedding/indexing batch size",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Force rebuild even when collection+manifest already match",
    )
    parser.add_argument(
        "--no-query-cache",
        action="store_true",
        help=(
            "Disable benchmark query-vector precompute/cache. By default, query vectors are "
            "precomputed once per arm so K=3/5/10 share the same embeddings and low-RPM "
            "providers such as Voyage can complete full GT runs."
        ),
    )
    parser.add_argument(
        "--skip-stage2",
        action="store_true",
        help="Stop after Stage 1 even if ambiguity triggers Stage 2",
    )
    parser.add_argument(
        "--stage1-sample",
        action="store_true",
        help=(
            "Rate-limit-safer Stage 1-only mode: if --k-values is omitted, defaults to "
            "Recall@3-only evaluation and skips Stage 2. Combine with --pool-size and/or "
            "--max-queries for a bounded provisional slice."
        ),
    )
    parser.add_argument(
        "--k-values",
        type=int,
        nargs="+",
        default=None,
        help="Override matrix K values",
    )
    parser.add_argument(
        "--pool-size",
        type=int,
        default=None,
        help="Limit the GT-first base pool to the first N servers for bounded sample runs",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=None,
        help="Limit evaluation to a deterministic sample of N covered GT queries",
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=42,
        help="Deterministic sample seed used with --max-queries",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve benchmark arms and manifests without writing collections or running eval",
    )
    parser.add_argument(
        "--no-wandb",
        action="store_true",
        help="Reserved for parity with existing scripts; no W&B integration yet",
    )
    return parser.parse_args()


def _artifact_dir(args: argparse.Namespace) -> Path:
    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        return args.output_dir
    return create_artifact_dir(args.results_root)


def _arm_k_values(matrix: BenchmarkMatrix, args: argparse.Namespace) -> list[int]:
    requested = args.k_values
    if requested is None and args.stage1_sample:
        requested = [3]
    k_values = sorted(int(value) for value in (requested or matrix.k_values or DEFAULT_K_VALUES))
    if 3 not in k_values:
        raise SystemExit("K=3 is required because Stage 1 ranking/control parity use Recall@3")
    return k_values


def _is_bounded_run(args: argparse.Namespace) -> bool:
    return args.pool_size is not None or args.max_queries is not None


def _skip_stage2(args: argparse.Namespace) -> bool:
    return args.skip_stage2 or args.stage1_sample


async def _measure_arm(
    *,
    arm: BenchmarkArm,
    matrix: BenchmarkMatrix,
    settings: Settings,
    qdrant_client: AsyncQdrantClient,
    artifact_dir: Path,
    manifest_dir: Path,
    batch_size: int,
    k_values: list[int],
    pool_server_ids: list[str],
    entries: list,
    force_rebuild: bool,
    dry_run: bool,
    precompute_query_vectors: bool,
    sparse_query_cache: dict[str, dict[str, Any]],
) -> ArmEvaluationResult:
    ok, reason = check_arm_backend_availability(arm, settings)
    collection_name, config_hash = matrix.collection_prefix, ""
    if not ok:
        logger.warning(f"Skipping arm '{arm.arm_id}': {reason}")
        return ArmEvaluationResult(
            arm=arm,
            collection_name="unbuilt",
            manifest_path=None,
            config_hash="unavailable",
            status="skipped",
            note=reason,
        )

    started = time.perf_counter()
    try:
        build_result = await build_or_reuse_arm_collection(
            arm=arm,
            settings=settings,
            input_path=matrix.input_path,
            enriched_path=matrix.enriched_path,
            target=matrix.target,
            qdrant_client=qdrant_client,
            batch_size=batch_size,
            manifest_dir=manifest_dir,
            pool_server_ids=pool_server_ids,
            force_rebuild=force_rebuild,
            dry_run=dry_run,
        )
        collection_name = build_result.collection_name
        config_hash = build_result.config_hash
        if dry_run:
            return ArmEvaluationResult(
                arm=arm,
                collection_name=collection_name,
                manifest_path=build_result.manifest_path,
                config_hash=config_hash,
                status="dry_run",
                note="Dry-run: collection build/evaluation skipped",
                build=build_result,
                runtime_seconds=time.perf_counter() - started,
            )

        eval_metadata: dict[str, Any] = {}
        results_by_k = await run_hybrid_eval_for_arm(
            arm=arm,
            settings=settings,
            qdrant_client=qdrant_client,
            pool_server_ids=pool_server_ids,
            entries=entries,
            k_values=k_values,
            collection_name=collection_name,
            batch_size=batch_size,
            precompute_query_vectors=precompute_query_vectors,
            metadata_out=eval_metadata,
            sparse_query_cache=sparse_query_cache,
        )
        result = ArmEvaluationResult(
            arm=arm,
            collection_name=collection_name,
            manifest_path=build_result.manifest_path,
            config_hash=config_hash,
            status="measured",
            note=None,
            results_by_k=results_by_k,
            build=build_result,
            runtime_seconds=time.perf_counter() - started,
            eval_metadata=eval_metadata,
        )
        return result
    except BackendConfigurationError as exc:
        logger.warning(f"Skipping arm '{arm.arm_id}': {exc}")
        return ArmEvaluationResult(
            arm=arm,
            collection_name=collection_name,
            manifest_path=None,
            config_hash=config_hash or "error",
            status="skipped",
            note=str(exc),
            runtime_seconds=time.perf_counter() - started,
        )
    except Exception as exc:
        logger.exception(f"Arm '{arm.arm_id}' failed")
        return ArmEvaluationResult(
            arm=arm,
            collection_name=collection_name or "error",
            manifest_path=None,
            config_hash=config_hash or "error",
            status="failed",
            note=str(exc),
            runtime_seconds=time.perf_counter() - started,
        )


def _best_dense_under_control(stage1_results: list[ArmEvaluationResult]) -> str | None:
    ranked = rank_measured_results(stage1_results)
    return ranked[0].arm.arm_id if ranked else None


def _best_tested_hybrid(results: list[ArmEvaluationResult]) -> str | None:
    ranked = rank_measured_results(results)
    return ranked[0].arm.arm_id if ranked else None


def _write_markdown_summary(path: Path, payload: dict[str, object]) -> None:
    mode = payload.get("mode") or {}
    lines = [
        "# Hybrid Embedding Benchmark",
        "",
        f"- timestamp: {payload['timestamp']}",
        f"- matrix: {payload['matrix_path']}",
        f"- control arm: {payload['control_arm_id']}",
        f"- best_dense_under_control: {payload.get('best_dense_under_control')}",
        f"- best_tested_hybrid: {payload.get('best_tested_hybrid')}",
        f"- provisional: {mode.get('provisional', False)}",
        f"- pool_size: {mode.get('actual_pool_size')}",
        f"- n_queries: {mode.get('n_queries')}",
        f"- k_values: {mode.get('k_values')}",
        "",
        "## Stage 1",
        "",
        str(payload["stage1_table"]),
    ]
    if payload.get("stage2a"):
        lines.extend(["", "## Stage 2A", "", str(payload["stage2a_table"])])
    if payload.get("stage2b"):
        lines.extend(["", "## Stage 2B", "", str(payload["stage2b_table"])])
    path.write_text("\n".join(lines), encoding="utf-8")


async def main(args: argparse.Namespace) -> None:
    matrix = load_benchmark_matrix(args.matrix)
    artifact_dir = _artifact_dir(args)
    manifest_dir = args.manifest_dir
    settings = Settings()
    k_values = _arm_k_values(matrix, args)
    qdrant_url, qdrant_key = get_qdrant_config(matrix.target, settings)
    qdrant_client = AsyncQdrantClient(url=qdrant_url, api_key=qdrant_key or None)
    pool_server_ids = load_pool_server_ids(pool_size=args.pool_size)
    entries = load_and_filter_gt(
        pool_server_ids,
        max_queries=args.max_queries,
        sample_seed=args.sample_seed,
    )
    if not entries and not args.dry_run:
        raise SystemExit("No GT entries after filtering; aborting benchmark")
    sparse_query_cache: dict[str, dict[str, Any]] = {}

    logger.info(
        f"Hybrid embedding benchmark: matrix={args.matrix} "
        f"artifact_dir={artifact_dir} k_values={k_values} "
        f"pool_size={len(pool_server_ids)} n_queries={len(entries)} "
        f"bounded={_is_bounded_run(args)}"
    )

    try:
        control_arm = matrix.control_arm()
        control_result = await _measure_arm(
            arm=control_arm,
            matrix=matrix,
            settings=settings,
            qdrant_client=qdrant_client,
            artifact_dir=artifact_dir,
            manifest_dir=manifest_dir,
            batch_size=args.batch_size,
            k_values=k_values,
            pool_server_ids=pool_server_ids,
            entries=entries,
            force_rebuild=args.force_rebuild,
            dry_run=args.dry_run,
            precompute_query_vectors=not args.no_query_cache,
            sparse_query_cache=sparse_query_cache,
        )

        stage1_results: list[ArmEvaluationResult] = [control_result]
        parity_summary = None
        if not args.dry_run and control_result.is_measured():
            if _is_bounded_run(args):
                k3 = control_result.metrics_at(3)
                parity_summary = {
                    "skipped": True,
                    "reason": "bounded_slice_not_comparable_to_full_control_baseline",
                    "baseline": matrix.control_baseline,
                    "measured": {
                        "recall_at_3": k3.recall_at_k if k3 is not None else None,
                        "precision_at_1": k3.precision_at_1 if k3 is not None else None,
                        "confusion_rate": k3.confusion_rate if k3 is not None else None,
                    },
                    "pool_size": len(pool_server_ids),
                    "n_queries": len(entries),
                }
            else:
                parity_summary = control_parity_summary(
                    control_result,
                    baseline=matrix.control_baseline,
                    tolerance_pp=float(matrix.stage_rules.get("control_parity_tolerance_pp", 2.0)),
                )

        if args.dry_run:
            remaining_stage1 = [
                arm for arm in matrix.stage1_arms if arm.arm_id != control_arm.arm_id
            ]
        elif _is_bounded_run(args):
            remaining_stage1 = [
                arm for arm in matrix.stage1_arms if arm.arm_id != control_arm.arm_id
            ]
        elif parity_summary and parity_summary["passed"]:
            remaining_stage1 = [
                arm for arm in matrix.stage1_arms if arm.arm_id != control_arm.arm_id
            ]
        else:
            remaining_stage1 = []

        for arm in remaining_stage1:
            stage1_results.append(
                await _measure_arm(
                    arm=arm,
                    matrix=matrix,
                    settings=settings,
                    qdrant_client=qdrant_client,
                    artifact_dir=artifact_dir,
                    manifest_dir=manifest_dir,
                    batch_size=args.batch_size,
                    k_values=k_values,
                    pool_server_ids=pool_server_ids,
                    entries=entries,
                    force_rebuild=args.force_rebuild,
                    dry_run=args.dry_run,
                    precompute_query_vectors=not args.no_query_cache,
                    sparse_query_cache=sparse_query_cache,
                )
            )

        payload: dict[str, Any] = {
            "timestamp": now_utc_iso(),
            "matrix_path": str(args.matrix),
            "artifact_dir": str(artifact_dir),
            "control_arm_id": control_arm.arm_id,
            "mode": {
                "stage1_sample": args.stage1_sample,
                "bounded_slice": _is_bounded_run(args),
                "provisional": _is_bounded_run(args),
                "requested_pool_size": args.pool_size,
                "actual_pool_size": len(pool_server_ids),
                "requested_max_queries": args.max_queries,
                "n_queries": len(entries),
                "sample_seed": args.sample_seed if args.max_queries is not None else None,
                "k_values": k_values,
                "skip_stage2": _skip_stage2(args),
                "query_cache_enabled": not args.no_query_cache,
            },
            "stage1": {
                "results": [result.to_dict() for result in stage1_results],
            },
            "stage1_table": format_results_table(stage1_results),
            "control_parity": parity_summary,
            "best_dense_under_control": _best_dense_under_control(stage1_results),
            "best_tested_hybrid": _best_tested_hybrid(stage1_results),
            "stage2a": None,
            "stage2b": None,
        }

        if args.dry_run:
            write_json(artifact_dir / "dry_run.json", payload)
            return

        parity_gate_failed = (
            parity_summary is None
            or (
                not parity_summary.get("skipped", False)
                and not parity_summary.get("passed", False)
            )
        )
        if parity_gate_failed:
            failure_payload = {
                **payload,
                "diagnostic_mode": True,
                "control_parity_failure_notes": format_parity_failure_notes(
                    control_result=control_result,
                    parity_summary=parity_summary
                    or {
                        "baseline": matrix.control_baseline,
                        "delta_pp": {
                            "recall_at_3": None,
                            "precision_at_1": None,
                            "confusion_rate": None,
                        },
                    },
                ),
                "best_dense_under_control": None,
                "best_tested_hybrid": None,
            }
            write_json(artifact_dir / "control_parity_failure.json", failure_payload)
            logger.warning("Control parity gate failed; stopping in diagnostic mode")
            return

        if not _skip_stage2(args):
            stage1_trigger = ambiguity_trigger(stage1_results)
            payload["stage1"]["ambiguity_trigger"] = stage1_trigger
            if stage1_trigger["triggered"]:
                promoted = promoted_stage1_arms(stage1_results)
                stage2a_arms = make_stage2a_arms(promoted, matrix)[
                    : int(matrix.stage_rules.get("stage2_max_measured_arms", 4))
                ]
                stage2a_results: list[ArmEvaluationResult] = []
                for arm in stage2a_arms:
                    stage2a_results.append(
                        await _measure_arm(
                            arm=arm,
                            matrix=matrix,
                            settings=settings,
                            qdrant_client=qdrant_client,
                            artifact_dir=artifact_dir,
                            manifest_dir=manifest_dir,
                            batch_size=args.batch_size,
                            k_values=k_values,
                            pool_server_ids=pool_server_ids,
                            entries=entries,
                            force_rebuild=args.force_rebuild,
                            dry_run=False,
                            precompute_query_vectors=not args.no_query_cache,
                            sparse_query_cache=sparse_query_cache,
                        )
                    )
                payload["stage2a"] = {
                    "results": [result.to_dict() for result in stage2a_results],
                    "ambiguity_trigger": ambiguity_trigger(stage2a_results),
                }
                payload["stage2a_table"] = format_results_table(stage2a_results)
                combined_after_stage2a = stage1_results + stage2a_results
                payload["best_tested_hybrid"] = _best_tested_hybrid(combined_after_stage2a)

                stage2a_ranked = rank_measured_results(stage2a_results)
                remaining_stage2_budget = int(
                    matrix.stage_rules.get("stage2_max_measured_arms", 4)
                ) - len(stage2a_results)
                stage2a_trigger = payload["stage2a"]["ambiguity_trigger"]
                if stage2a_ranked and stage2a_trigger["triggered"] and remaining_stage2_budget > 0:
                    stage2b_arms = make_stage2b_arms(
                        stage2a_ranked[0],
                        matrix,
                    )[:remaining_stage2_budget]
                    stage2b_results: list[ArmEvaluationResult] = []
                    for arm in stage2b_arms:
                        stage2b_results.append(
                            await _measure_arm(
                                arm=arm,
                                matrix=matrix,
                                settings=settings,
                                qdrant_client=qdrant_client,
                                artifact_dir=artifact_dir,
                                manifest_dir=manifest_dir,
                                batch_size=args.batch_size,
                                k_values=k_values,
                                pool_server_ids=pool_server_ids,
                                entries=entries,
                                force_rebuild=args.force_rebuild,
                                dry_run=False,
                                precompute_query_vectors=not args.no_query_cache,
                                sparse_query_cache=sparse_query_cache,
                            )
                        )
                    payload["stage2b"] = {
                        "results": [result.to_dict() for result in stage2b_results],
                    }
                    payload["stage2b_table"] = format_results_table(stage2b_results)
                    payload["best_tested_hybrid"] = _best_tested_hybrid(
                        stage1_results + stage2a_results + stage2b_results
                    )

        write_json(artifact_dir / "hybrid_embedding_benchmark.json", payload)
        _write_markdown_summary(artifact_dir / "hybrid_embedding_benchmark.md", payload)
        logger.info(
            f"best_dense_under_control={payload.get('best_dense_under_control')} "
            f"best_tested_hybrid={payload.get('best_tested_hybrid')}"
        )
    finally:
        await qdrant_client.close()


if __name__ == "__main__":
    asyncio.run(main(_parse_args()))
