"""Phase 4c: Gemini — description variant tool selection experiment.

Tests 5 clusters x 3 queries x 5 variants x 3 reps = 225 calls.
Uses Gemini free tier with adaptive rate limiting based on API retryDelay headers.

Selected clusters (5-10 tools, most likely to show format effects):
  get_003  (5 tools)  — Hologres query plan
  get_004  (5 tools)  — Wikipedia summary
  delete_011 (6 tools) — ElevenLabs delete job
  search_007 (8 tools) — Gitee search users
  weather_021 (9 tools) — Weather alerts

Model fallback chain: gemini-3-flash-preview -> gemini-2.5-flash -> gemini-2.5-flash-lite
Respects retryDelay from 429 responses for adaptive rate limiting.
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

# ── paths ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CLUSTERS_PATH = ROOT / "data" / "experiments" / "clusters.json"
DESCRIPTIONS_PATH = ROOT / "data" / "experiments" / "descriptions.json"
QUERIES_PATH = ROOT / "data" / "experiments" / "queries.json"
OUTPUT_PATH = ROOT / "data" / "experiments" / "phase4_gemini_results.json"

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODELS = ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# ── experiment parameters ──────────────────────────────────────────────
SELECTED_CLUSTERS = ["get_003", "get_004", "delete_011", "search_007", "weather_021"]
VARIANT_KEYS = ["V_orig", "V_prose", "V_md", "V_xml", "V_spec"]
VARIANT_LABELS = {
    "V_orig": "Control (original)",
    "V_prose": "Prose (natural language)",
    "V_md": "Markdown (structured)",
    "V_xml": "XML (tagged)",
    "V_spec": "Spec (semi-formal)",
}
REPS = 3
BASE_DELAY = 4.5  # seconds between calls when not rate-limited
MAX_RETRIES_PER_CALL = 4  # total attempts across all models
QUOTA_EXHAUSTED_WAIT = 60  # seconds to wait when all models return 429


def _log(msg: str) -> None:
    """Print with immediate flush for unbuffered output."""
    print(msg, flush=True)


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
            _log(f"    [HTTP {e.response.status_code}]")
            return None, 0.0
        except Exception:
            continue

    # All models returned 429/503 — return None with suggested extra delay
    return None, QUOTA_EXHAUSTED_WAIT


def main(reps_override: int = REPS, resume: bool = False) -> None:
    reps = reps_override
    clusters, descriptions, queries = load_data()

    # Resume support: load existing results and build skip set
    results: list[dict] = []
    done_keys: set[str] = set()
    if resume and OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            existing = json.load(f)
        results = existing.get("results", [])
        for r in results:
            done_keys.add(f"{r['cluster']}|{r['variant']}|{r['query_id']}")
        _log(f"Resuming: {len(results)} conditions already done, {len(done_keys)} keys loaded")

    model_usage: dict[str, int] = {}
    null_count = 0
    total_conditions = len(SELECTED_CLUSTERS) * len(VARIANT_KEYS) * 3  # 3 queries each
    remaining = total_conditions - len(done_keys)
    total_calls = remaining * reps
    call_count = 0
    start_time = time.time()

    _log(f"Phase 4c: Gemini — {total_calls} calls planned ({reps} reps, {remaining} conditions)")
    _log(f"Models: {GEMINI_MODELS}")
    _log(f"Selected clusters: {SELECTED_CLUSTERS}")
    _log("=" * 60)

    for cluster_id in SELECTED_CLUSTERS:
        cluster = clusters[cluster_id]
        target_tool_id = cluster["target_tool_id"]
        desc_data = descriptions["clusters"][cluster_id]
        query_data = queries["clusters"][cluster_id]
        query_list = query_data["queries"]

        _log(f"\n--- {cluster_id} (target={target_tool_id}, {cluster['size']} tools) ---")

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

                    chosen, extra_delay = call_gemini(
                        query_text, func_decls, safe_to_orig, model_usage
                    )
                    picks.append(chosen)
                    if chosen is None:
                        null_count += 1
                    elif chosen == target_tool_id:
                        hits += 1

                    # Progress every 5 calls, first 3, or at end
                    if call_count % 5 == 0 or call_count <= 3 or call_count == total_calls:
                        elapsed = time.time() - start_time
                        rpm = call_count / (elapsed / 60) if elapsed > 0 else 0
                        hit_mark = "HIT" if chosen == target_tool_id else ("NULL" if chosen is None else "miss")
                        _log(
                            f"  [{call_count}/{total_calls}] {hit_mark} "
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

        # Save partial results after each cluster
        _save_output(results, model_usage, null_count, call_count, start_time, clusters, reps)

    _print_summary(results, model_usage, null_count, call_count, start_time, clusters)


def _save_output(
    results: list[dict],
    model_usage: dict[str, int],
    null_count: int,
    call_count: int,
    start_time: float,
    clusters: dict,
    reps: int = REPS,
) -> None:
    """Save current results to disk (supports partial saves)."""
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
    for cid in SELECTED_CLUSTERS:
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

    output = {
        "test": "phase4c — Gemini description variant tool selection",
        "model": GEMINI_MODELS[0],
        "model_fallback_chain": GEMINI_MODELS,
        "model_usage": model_usage,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reps_per_condition": reps,
        "selected_clusters": SELECTED_CLUSTERS,
        "cluster_selection_criteria": "5-10 tools per cluster, most likely to show format effects",
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

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)


def _print_summary(
    results: list[dict],
    model_usage: dict[str, int],
    null_count: int,
    call_count: int,
    start_time: float,
    clusters: dict,
) -> None:
    elapsed_total = time.time() - start_time
    total_hits = sum(r["hits"] for r in results)
    total_reps = sum(r["reps"] for r in results)

    _log("\n" + "=" * 60)
    _log(f"Done! {call_count} calls in {elapsed_total:.0f}s ({null_count} nulls)")
    _log(f"Overall hit rate: {total_hits}/{total_reps} = {total_hits/total_reps:.1%}")

    _log("\nVariant hit rates:")
    for vk in VARIANT_KEYS:
        v_results = [r for r in results if r["variant"] == vk]
        v_hits = sum(r["hits"] for r in v_results)
        v_reps = sum(r["reps"] for r in v_results)
        rate = v_hits / v_reps if v_reps > 0 else 0.0
        _log(f"  {vk:8s} ({VARIANT_LABELS[vk]:25s}): {rate:.1%} ({v_hits}/{v_reps})")

    _log("\nCluster hit rates:")
    for cid in SELECTED_CLUSTERS:
        c_results = [r for r in results if r["cluster"] == cid]
        if not c_results:
            continue
        c_hits = sum(r["hits"] for r in c_results)
        c_reps = sum(r["reps"] for r in c_results)
        rate = c_hits / c_reps if c_reps > 0 else 0.0
        _log(f"  {cid:15s} ({clusters[cid]['size']:2d} tools): {rate:.1%} ({c_hits}/{c_reps})")

    _log(f"\nModel usage: {model_usage}")
    _log(f"Results written to: {OUTPUT_PATH}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 4c: Gemini tool selection experiment")
    parser.add_argument("--reps", type=int, default=REPS, help=f"Reps per condition (default {REPS})")
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from existing partial results (skip completed cluster+variant+query combos)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(reps_override=args.reps, resume=args.resume)
