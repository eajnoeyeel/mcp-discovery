"""Bias-Max Gemini: description variant tool selection experiment across all 17 clusters.

Tests N clusters x 3 queries x 5 variants x REPS reps.
Uses Gemini free tier with adaptive rate limiting based on API retryDelay headers.

Model fallback chain: gemini-3-flash-preview -> gemini-2.5-flash -> gemini-2.5-flash-lite
Respects retryDelay from 429 responses for adaptive rate limiting.

Phase 0 auto-detection: --clusters all --reps 1 writes to bias_max_gemini_calibration.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from loguru import logger

# ── paths ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CLUSTERS_PATH = ROOT / "data" / "experiments" / "clusters.json"
DESCRIPTIONS_PATH = ROOT / "data" / "experiments" / "descriptions.json"
QUERIES_PATH = ROOT / "data" / "experiments" / "queries.json"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "experiments" / "bias_max_gemini_results.json"
CALIBRATION_OUTPUT_PATH = ROOT / "data" / "experiments" / "bias_max_gemini_calibration.json"

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# ── experiment parameters ──────────────────────────────────────────────
VARIANT_KEYS = ["V_orig", "V_prose", "V_spec", "V_md", "V_xml"]
VARIANT_LABELS = {
    "V_orig": "Control (original)",
    "V_prose": "Prose (natural language)",
    "V_spec": "Spec (semi-formal)",
    "V_md": "Markdown (structured)",
    "V_xml": "XML (tagged)",
}
REPS = 3
BASE_DELAY = 4.5  # seconds between calls when not rate-limited
MAX_RETRIES_PER_CALL = 4  # total attempts across all models
QUOTA_EXHAUSTED_WAIT = 60  # seconds to wait when all models return 429
FLASH_LITE_SHARE_THRESHOLD = 0.20  # abort threshold for flash-lite usage share
NULL_RATE_WARNING_THRESHOLD = 0.10  # warn if null_calls/cluster_total >= 10%


def _safe_name(tool_id: str) -> str:
    """Convert tool_id to a valid Gemini function name (alphanumeric + underscore)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", tool_id)


def _reverse_safe_name(safe: str, mapping: dict[str, str]) -> str:
    """Reverse a safe name back to the original tool_id."""
    return mapping.get(safe, safe)


def _parse_retry_delay(resp: httpx.Response) -> float:
    """Extract retryDelay from Gemini 429 response, default 15s."""
    try:
        details = resp.json().get("error", {}).get("details", [])
        for d in details:
            if "RetryInfo" in d.get("@type", ""):
                delay_str = d.get("retryDelay", "15s")
                return float(delay_str.rstrip("s"))
    except Exception:
        pass
    return 15.0


def load_data() -> tuple[dict, dict, dict]:
    with open(CLUSTERS_PATH) as f:
        clusters_raw = json.load(f)
    with open(DESCRIPTIONS_PATH) as f:
        descriptions = json.load(f)
    with open(QUERIES_PATH) as f:
        queries = json.load(f)

    clusters = {}
    for c in clusters_raw["candidate_clusters"]:
        clusters[c["cluster_id"]] = c

    return clusters, descriptions, queries


def resolve_cluster_ids(clusters_arg: str, clusters: dict) -> list[str]:
    """Resolve --clusters arg to a list of cluster IDs."""
    if clusters_arg.strip().lower() == "all":
        return list(clusters.keys())
    # Accept comma or space separated
    parts = re.split(r"[\s,]+", clusters_arg.strip())
    return [p for p in parts if p]


def build_func_declarations(
    cluster: dict,
    target_tool_id: str,
    variant_desc: str,
) -> tuple[list[dict], dict[str, str]]:
    """Build Gemini function_declarations, swapping the target tool's description."""
    func_decls = []
    safe_to_orig: dict[str, str] = {}

    for tool in cluster["tools"]:
        tid = tool["tool_id"]
        safe = _safe_name(tid)
        safe_to_orig[safe] = tid

        desc = variant_desc if tid == target_tool_id else tool["desc"]
        if not desc or not desc.strip():
            desc = tool["name"]

        func_decls.append(
            {
                "name": safe,
                "description": desc,
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"input": {"type": "STRING"}},
                    "required": ["input"],
                },
            }
        )

    return func_decls, safe_to_orig


def call_gemini(
    query: str,
    func_decls: list[dict],
    safe_to_orig: dict[str, str],
    model_usage: dict[str, int],
) -> tuple[str | None, float]:
    """Call Gemini and return (chosen_tool_id, extra_delay_needed).

    Tries models in order. On 429/503, extracts retryDelay and returns it
    so the caller can sleep appropriately before the next call.
    """
    payload = {
        "contents": [
            {"parts": [{"text": f"Use the single most appropriate tool: {query}"}]}
        ],
        "tools": [{"function_declarations": func_decls}],
        "tool_config": {"function_calling_config": {"mode": "ANY"}},
    }

    # Phase 1: Try each model once (fast pass)
    for model in GEMINI_MODELS:
        url = f"{GEMINI_BASE_URL}/{model}:generateContent"
        try:
            resp = httpx.post(
                url,
                params={"key": GEMINI_API_KEY},
                json=payload,
                timeout=30.0,
            )
            if resp.status_code in (429, 503):
                continue  # try next model

            resp.raise_for_status()
            data = resp.json()

            candidates = data.get("candidates", [])
            if not candidates:
                return None, 0.0
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                fc = part.get("functionCall")
                if fc:
                    model_usage[model] = model_usage.get(model, 0) + 1
                    safe_name = fc["name"]
                    return _reverse_safe_name(safe_name, safe_to_orig), 0.0
            return None, 0.0

        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP {e.response.status_code} from {model}")
            continue
        except Exception:
            continue

    # All models returned 429/503 — return None with suggested extra delay
    return None, QUOTA_EXHAUSTED_WAIT


def _check_flash_lite_share(model_usage: dict[str, int], results: list[dict]) -> bool:
    """Return True if flash-lite share exceeds threshold."""
    total_model_calls = sum(model_usage.values())
    if total_model_calls == 0:
        return False
    flash_lite_calls = model_usage.get("gemini-2.5-flash-lite", 0)
    return (flash_lite_calls / total_model_calls) > FLASH_LITE_SHARE_THRESHOLD


def main(
    reps_override: int = REPS,
    resume: bool = False,
    clusters_arg: str = "all",
    output_path_override: Path | None = None,
) -> None:
    reps = reps_override
    clusters, descriptions, queries = load_data()

    selected_clusters = resolve_cluster_ids(clusters_arg, clusters)
    logger.info(f"Selected clusters ({len(selected_clusters)}): {selected_clusters}")

    # Phase 0 auto-detection
    is_phase0 = clusters_arg.strip().lower() == "all" and reps == 1
    if output_path_override is not None:
        output_path = output_path_override
    elif is_phase0:
        output_path = CALIBRATION_OUTPUT_PATH
        logger.info("Phase 0 calibration detected: output -> bias_max_gemini_calibration.json")
    else:
        output_path = DEFAULT_OUTPUT_PATH

    # Resume support: load existing results and build skip set
    results: list[dict] = []
    done_keys: set[str] = set()
    if resume and output_path.exists():
        with open(output_path) as f:
            existing = json.load(f)
        results = existing.get("results", [])
        for r in results:
            done_keys.add(f"{r['cluster']}|{r['variant']}|{r['query_id']}")
        logger.info(
            f"Resuming: {len(results)} conditions already done, {len(done_keys)} keys loaded"
        )

    model_usage: dict[str, int] = {}
    null_count = 0
    total_conditions = len(selected_clusters) * len(VARIANT_KEYS) * 3  # 3 queries each
    remaining = total_conditions - len(done_keys)
    total_calls = remaining * reps
    call_count = 0
    start_time = time.time()
    provisional = False

    logger.info(
        f"Bias-Max Gemini — {total_calls} calls planned ({reps} reps, {remaining} conditions)"
    )
    logger.info(f"Models: {GEMINI_MODELS}")
    logger.info(f"Selected clusters: {selected_clusters}")
    logger.info("=" * 60)

    for cluster_id in selected_clusters:
        if cluster_id not in clusters:
            logger.warning(f"Cluster {cluster_id!r} not found in clusters.json, skipping")
            continue

        cluster = clusters[cluster_id]
        target_tool_id = cluster["target_tool_id"]
        desc_data = descriptions["clusters"].get(cluster_id)
        query_data = queries["clusters"].get(cluster_id)

        if desc_data is None or query_data is None:
            logger.warning(f"Missing descriptions or queries for cluster {cluster_id}, skipping")
            continue

        query_list = query_data["queries"]

        logger.info(f"--- {cluster_id} (target={target_tool_id}, {cluster['size']} tools) ---")

        cluster_null_count = 0
        cluster_total_calls = 0

        for variant_key in VARIANT_KEYS:
            variant_desc = desc_data[variant_key]

            func_decls, safe_to_orig = build_func_declarations(
                cluster, target_tool_id, variant_desc
            )

            for q_entry in query_list:
                query_id = q_entry["id"]
                query_text = q_entry["query"]

                # Skip if already done (resume mode)
                key = f"{cluster_id}|{variant_key}|{query_id}"
                if key in done_keys:
                    continue

                picks: list[str | None] = []
                hits = 0

                for rep in range(reps):
                    call_count += 1
                    cluster_total_calls += 1

                    chosen, extra_delay = call_gemini(
                        query_text, func_decls, safe_to_orig, model_usage
                    )
                    picks.append(chosen)
                    if chosen is None:
                        null_count += 1
                        cluster_null_count += 1
                    elif chosen == target_tool_id:
                        hits += 1

                    # Progress every 5 calls, first 3, or at end
                    if call_count % 5 == 0 or call_count <= 3 or call_count == total_calls:
                        elapsed = time.time() - start_time
                        rpm = call_count / (elapsed / 60) if elapsed > 0 else 0
                        if chosen == target_tool_id:
                            hit_mark = "HIT"
                        elif chosen is None:
                            hit_mark = "NULL"
                        else:
                            hit_mark = "miss"
                        logger.info(
                            f"[{call_count}/{total_calls}] {hit_mark} "
                            f"rpm={rpm:.1f} nulls={null_count} "
                            f"{variant_key} {query_id}"
                        )

                    # Rate limit: use base delay or extra delay from 429 response
                    if call_count < total_calls:
                        delay = max(BASE_DELAY, extra_delay * 0.5)
                        time.sleep(delay)

                results.append(
                    {
                        "cluster": cluster_id,
                        "target": target_tool_id,
                        "variant": variant_key,
                        "label": VARIANT_LABELS[variant_key],
                        "query_id": query_id,
                        "query": query_text,
                        "hits": hits,
                        "reps": reps,
                        "hit_rate": hits / reps,
                        "picks": picks,
                    }
                )

        # null_rate check after each cluster
        if cluster_total_calls > 0:
            null_rate = cluster_null_count / cluster_total_calls
            if null_rate >= NULL_RATE_WARNING_THRESHOLD:
                logger.warning(
                    f"High null rate for cluster {cluster_id}: "
                    f"{cluster_null_count}/{cluster_total_calls} = {null_rate:.1%}"
                )

        # flash-lite share check after each cluster
        if _check_flash_lite_share(model_usage, results):
            provisional = True
            logger.warning("WARNING: PROVISIONAL RUN - flash-lite > 20%")

        # Save partial results after each cluster
        _save_output(
            results, model_usage, null_count, call_count, start_time,
            clusters, reps, selected_clusters, output_path, provisional,
        )

    _print_summary(
        results, model_usage, null_count, call_count, start_time,
        clusters, selected_clusters, output_path, provisional,
    )


def _save_output(
    results: list[dict],
    model_usage: dict[str, int],
    null_count: int,
    call_count: int,
    start_time: float,
    clusters: dict,
    reps: int = REPS,
    selected_clusters: list[str] | None = None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    provisional: bool = False,
) -> None:
    """Save current results to disk (supports partial saves)."""
    if selected_clusters is None:
        selected_clusters = list(clusters.keys())

    elapsed_total = time.time() - start_time
    total_hits = sum(r["hits"] for r in results)
    total_reps = sum(r["reps"] for r in results)

    variant_summary = {}
    for vk in VARIANT_KEYS:
        v_results = [r for r in results if r["variant"] == vk]
        v_hits = sum(r["hits"] for r in v_results)
        v_reps = sum(r["reps"] for r in v_results)
        variant_summary[vk] = {
            "label": VARIANT_LABELS[vk],
            "hits": v_hits,
            "reps": v_reps,
            "hit_rate": v_hits / v_reps if v_reps > 0 else 0.0,
        }

    cluster_summary = {}
    for cid in selected_clusters:
        c_results = [r for r in results if r["cluster"] == cid]
        if not c_results:
            continue
        c_hits = sum(r["hits"] for r in c_results)
        c_reps = sum(r["reps"] for r in c_results)
        cluster_summary[cid] = {
            "target": clusters[cid]["target_tool_id"],
            "pool_size": clusters[cid]["size"],
            "hits": c_hits,
            "reps": c_reps,
            "hit_rate": c_hits / c_reps if c_reps > 0 else 0.0,
        }

    output: dict = {
        "test": "bias-max — Gemini description variant tool selection",
        "model": GEMINI_MODELS[0],
        "model_fallback_chain": GEMINI_MODELS,
        "model_usage": model_usage,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reps_per_condition": reps,
        "selected_clusters": selected_clusters,
        "variants": list(VARIANT_LABELS.keys()),
        "variant_labels": VARIANT_LABELS,
        "total_calls": call_count,
        "null_calls": null_count,
        "elapsed_seconds": round(elapsed_total, 1),
        "overall_hit_rate": total_hits / total_reps if total_reps > 0 else 0.0,
        "variant_summary": variant_summary,
        "cluster_summary": cluster_summary,
        "results": results,
    }

    if provisional:
        output["provisional"] = True

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)


def _print_summary(
    results: list[dict],
    model_usage: dict[str, int],
    null_count: int,
    call_count: int,
    start_time: float,
    clusters: dict,
    selected_clusters: list[str],
    output_path: Path,
    provisional: bool = False,
) -> None:
    elapsed_total = time.time() - start_time
    total_hits = sum(r["hits"] for r in results)
    total_reps = sum(r["reps"] for r in results)

    print("=" * 60, flush=True)
    print(f"Done! {call_count} calls in {elapsed_total:.0f}s ({null_count} nulls)", flush=True)
    if total_reps > 0:
        rate = total_hits / total_reps
        print(f"Overall hit rate: {total_hits}/{total_reps} = {rate:.1%}", flush=True)

    if provisional:
        print("WARNING: PROVISIONAL RUN - flash-lite > 20%", flush=True)

    print("\nVariant hit rates:", flush=True)
    for vk in VARIANT_KEYS:
        v_results = [r for r in results if r["variant"] == vk]
        v_hits = sum(r["hits"] for r in v_results)
        v_reps = sum(r["reps"] for r in v_results)
        rate = v_hits / v_reps if v_reps > 0 else 0.0
        print(f"  {vk:8s} ({VARIANT_LABELS[vk]:25s}): {rate:.1%} ({v_hits}/{v_reps})", flush=True)

    print("\nCluster hit rates:", flush=True)
    for cid in selected_clusters:
        c_results = [r for r in results if r["cluster"] == cid]
        if not c_results:
            continue
        c_hits = sum(r["hits"] for r in c_results)
        c_reps = sum(r["reps"] for r in c_results)
        rate = c_hits / c_reps if c_reps > 0 else 0.0
        pool_size = clusters[cid]["size"] if cid in clusters else "?"
        print(f"  {cid:15s} ({pool_size:2} tools): {rate:.1%} ({c_hits}/{c_reps})", flush=True)

    print(f"\nModel usage: {model_usage}", flush=True)
    print(f"Results written to: {output_path}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bias-Max Gemini tool selection experiment")
    parser.add_argument(
        "--reps", type=int, default=REPS, help=f"Reps per condition (default {REPS})"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from existing partial results (skip completed cluster+variant+query combos)",
    )
    parser.add_argument(
        "--clusters", type=str, default="all",
        help='Cluster IDs to run: comma/space-separated, or "all" for all 17 (default: all)',
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Override output path (default: auto-detected based on phase)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    output_override = Path(args.output) if args.output else None
    main(
        reps_override=args.reps,
        resume=args.resume,
        clusters_arg=args.clusters,
        output_path_override=output_override,
    )
