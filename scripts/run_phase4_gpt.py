"""Phase 4a (GPT): Description variant selection experiment.

For each of 17 clusters x 3 queries x 5 description variants, test
GPT-4o-mini's tool selection 10 times. Record hit/miss for each trial.

Usage:
    uv run python scripts/run_phase4_gpt.py
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

import openai

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
CLUSTERS_PATH = PROJECT_ROOT / "data" / "experiments" / "clusters.json"
DESCRIPTIONS_PATH = PROJECT_ROOT / "data" / "experiments" / "descriptions.json"
QUERIES_PATH = PROJECT_ROOT / "data" / "experiments" / "queries.json"
RESULTS_PATH = PROJECT_ROOT / "data" / "experiments" / "phase4_gpt_results.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MODEL = "gpt-4o-mini"
REPS = 10
VARIANTS = ("V_orig", "V_prose", "V_md", "V_xml", "V_spec")
DUMMY_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {"input": {"type": "string"}},
    "required": ["input"],
}


# ---------------------------------------------------------------------------
# Data Containers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolEntry:
    tool_id: str
    name: str
    desc: str


@dataclass(frozen=True)
class ClusterData:
    cluster_id: str
    tools: tuple[ToolEntry, ...]
    target_tool_id: str


@dataclass(frozen=True)
class QueryData:
    query_id: str
    query: str


@dataclass
class TrialResult:
    cluster_id: str
    query_id: str
    variant: str
    hits: int = 0
    trials: int = 0
    picks: list[str] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        return self.hits / self.trials if self.trials > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "query_id": self.query_id,
            "variant": self.variant,
            "hits": self.hits,
            "trials": self.trials,
            "hit_rate": round(self.hit_rate, 4),
            "picks": self.picks,
        }


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_clusters() -> dict[str, ClusterData]:
    raw = json.loads(CLUSTERS_PATH.read_text())
    clusters: dict[str, ClusterData] = {}
    for entry in raw["candidate_clusters"]:
        cid = entry["cluster_id"]
        tools = tuple(
            ToolEntry(tool_id=t["tool_id"], name=t["name"], desc=t["desc"])
            for t in entry["tools"]
        )
        clusters[cid] = ClusterData(
            cluster_id=cid,
            tools=tools,
            target_tool_id=entry["target_tool_id"],
        )
    return clusters


def load_descriptions() -> dict[str, dict[str, str]]:
    """Returns {cluster_id: {variant_name: description_text}}."""
    raw = json.loads(DESCRIPTIONS_PATH.read_text())
    return raw["clusters"]


def load_queries() -> dict[str, list[QueryData]]:
    """Returns {cluster_id: [QueryData, ...]}."""
    raw = json.loads(QUERIES_PATH.read_text())
    result: dict[str, list[QueryData]] = {}
    for cid, cdata in raw["clusters"].items():
        result[cid] = [
            QueryData(query_id=q["id"], query=q["query"])
            for q in cdata["queries"]
        ]
    return result


# ---------------------------------------------------------------------------
# Tool list builder
# ---------------------------------------------------------------------------
def _sanitize_fn_name(tool_id: str) -> str:
    """Convert tool_id to a valid function name: replace :: with __."""
    return tool_id.replace("::", "__").replace("-", "_").replace(".", "_")


def build_tools_payload(
    cluster: ClusterData,
    target_tool_id: str,
    variant_desc: str,
) -> list[dict[str, Any]]:
    """Build OpenAI tools array. Target tool gets variant_desc, others get original."""
    tools: list[dict[str, Any]] = []
    for t in cluster.tools:
        desc = variant_desc if t.tool_id == target_tool_id else t.desc
        tools.append({
            "type": "function",
            "function": {
                "name": _sanitize_fn_name(t.tool_id),
                "description": desc,
                "parameters": DUMMY_PARAMS,
            },
        })
    return tools


def _fn_name_to_tool_id(fn_name: str, cluster: ClusterData) -> str:
    """Reverse-map a sanitized function name back to the original tool_id."""
    for t in cluster.tools:
        if _sanitize_fn_name(t.tool_id) == fn_name:
            return t.tool_id
    return fn_name


# ---------------------------------------------------------------------------
# Single API call
# ---------------------------------------------------------------------------
def call_gpt(
    client: openai.OpenAI,
    query: str,
    tools: list[dict[str, Any]],
) -> str | None:
    """Call GPT-4o-mini with tool_choice=required. Returns the function name chosen."""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a tool router. Given a user query, select the "
                        "single most appropriate tool by calling it."
                    ),
                },
                {"role": "user", "content": query},
            ],
            tools=tools,
            tool_choice="required",
            temperature=1.0,
            max_tokens=50,
        )
        tool_calls = response.choices[0].message.tool_calls
        if tool_calls and len(tool_calls) > 0:
            return tool_calls[0].function.name
        return None
    except Exception as e:
        logger.warning(f"API call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Main experiment loop
# ---------------------------------------------------------------------------
def run_experiment() -> dict[str, Any]:
    client = openai.OpenAI()

    clusters = load_clusters()
    descriptions = load_descriptions()
    queries = load_queries()

    # Only process clusters present in all three files
    common_ids = set(clusters.keys()) & set(descriptions.keys()) & set(queries.keys())
    cluster_ids = sorted(common_ids)
    logger.info(f"Loaded {len(cluster_ids)} clusters (intersected across all input files)")

    total_expected = len(cluster_ids) * 3 * len(VARIANTS) * REPS
    logger.info(f"Total API calls planned: {total_expected}")

    results: list[TrialResult] = []
    call_count = 0
    start_time = time.monotonic()

    for cid in cluster_ids:
        cluster = clusters[cid]
        cluster_descs = descriptions[cid]
        cluster_queries = queries[cid]

        for qdata in cluster_queries:
            for variant in VARIANTS:
                variant_desc = cluster_descs[variant]
                tools_payload = build_tools_payload(
                    cluster, cluster.target_tool_id, variant_desc
                )
                target_fn = _sanitize_fn_name(cluster.target_tool_id)

                trial = TrialResult(
                    cluster_id=cid,
                    query_id=qdata.query_id,
                    variant=variant,
                )

                for _rep in range(REPS):
                    chosen_fn = call_gpt(client, qdata.query, tools_payload)

                    # Retry once on failure
                    if chosen_fn is None:
                        time.sleep(1.0)
                        chosen_fn = call_gpt(client, qdata.query, tools_payload)

                    if chosen_fn is not None:
                        chosen_tool_id = _fn_name_to_tool_id(chosen_fn, cluster)
                        trial.picks.append(chosen_tool_id)
                        trial.trials += 1
                        if chosen_fn == target_fn:
                            trial.hits += 1
                    else:
                        trial.picks.append("ERROR")
                        trial.trials += 1

                    call_count += 1
                    if call_count % 50 == 0:
                        elapsed = time.monotonic() - start_time
                        logger.info(
                            f"Progress: {call_count}/{total_expected} calls "
                            f"({call_count / total_expected * 100:.1f}%) "
                            f"| elapsed {elapsed:.0f}s"
                        )

                results.append(trial)

    elapsed_total = time.monotonic() - start_time
    logger.info(f"Completed {call_count} calls in {elapsed_total:.1f}s")

    # ------------------------------------------------------------------
    # Aggregate summary by variant
    # ------------------------------------------------------------------
    summary_by_variant: dict[str, dict[str, Any]] = {}
    for v in VARIANTS:
        v_results = [r for r in results if r.variant == v]
        total_hits = sum(r.hits for r in v_results)
        total_trials = sum(r.trials for r in v_results)
        hit_rates = [r.hit_rate for r in v_results if r.trials > 0]
        avg_hit_rate = sum(hit_rates) / len(hit_rates) if hit_rates else 0.0
        summary_by_variant[v] = {
            "total_hits": total_hits,
            "total_trials": total_trials,
            "avg_hit_rate": round(avg_hit_rate, 4),
        }

    output = {
        "model": MODEL,
        "reps_per_condition": REPS,
        "total_trials": call_count,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed_total, 1),
        "results": [r.to_dict() for r in results],
        "summary_by_variant": summary_by_variant,
    }

    return output


def main() -> None:
    logger.info(f"Phase 4a (GPT) — {MODEL}, {REPS} reps per condition")

    output = run_experiment()

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    logger.info(f"Results written to {RESULTS_PATH}")

    # Print summary
    logger.info("=== Summary by Variant ===")
    for v, stats in output["summary_by_variant"].items():
        logger.info(
            f"  {v:8s}: hits={stats['total_hits']:4d}/{stats['total_trials']:4d} "
            f"avg_hit_rate={stats['avg_hit_rate']:.4f}"
        )


if __name__ == "__main__":
    main()
