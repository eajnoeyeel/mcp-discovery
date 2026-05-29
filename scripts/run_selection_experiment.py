"""Per-client description optimization A/B experiment.

Runs a controlled experiment comparing raw descriptions (control) vs
vendor-optimized descriptions (treatment) across Gemini, Claude, and GPT.

Prerequisites:
  - data/enriched/per_client_variants.jsonl (run generate_per_client_variants.py first)
  - Experiment queries JSON file

Usage:
    PYTHONPATH=src uv run --group experiment python scripts/run_selection_experiment.py \
        --queries-file data/experiment/selection_queries.json
    PYTHONPATH=src uv run --group experiment python scripts/run_selection_experiment.py \
        --queries-file data/experiment/selection_queries.json --dry-run

Output:
    data/results/selection_experiment.json
"""

import argparse
import asyncio
import hashlib
import json
import random
import time
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from mcp_discovery.config import Settings
from mcp_discovery.description.base import VendorStyle
from mcp_discovery.description.variant_store import VariantStore
from mcp_discovery.scripts_helpers.selection_experiment import (
    ExperimentConfig,
    TrialResult,
    compute_experiment_summary,
    compute_mcnemar_summary,
)

load_dotenv()

VARIANTS_PATH = Path("data/enriched/per_client_variants.jsonl")
OUTPUT_PATH = Path("data/results/selection_experiment.json")

SELECTION_PROMPT = """\
You are an AI assistant selecting the best tool for a user's task.

Given a user query and {top_k} candidate tools, select the ONE tool that best \
matches the user's intent.

## User Query
{query}

## Candidate Tools
{candidates}

Respond with ONLY the tool_id of the best match. No explanation."""


async def _call_vendor_llm(
    vendor: VendorStyle,
    prompt: str,
    settings: Settings,
    temperature: float,
) -> tuple[str, int]:
    """Call a vendor's LLM and return (response_text, token_usage)."""
    if vendor == VendorStyle.GPT:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=50,
        )
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return text.strip(), tokens

    elif vendor == VendorStyle.CLAUDE:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        text = response.content[0].text if response.content else ""
        tokens = (
            (response.usage.input_tokens + response.usage.output_tokens) if response.usage else 0
        )
        return text.strip(), tokens

    elif vendor == VendorStyle.GEMINI:
        import google.generativeai as genai

        genai.configure(api_key=settings.google_api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = await asyncio.to_thread(
            model.generate_content,
            prompt,
            generation_config=genai.GenerationConfig(temperature=temperature, max_output_tokens=50),
        )
        text = response.text or ""
        tokens = response.usage_metadata.total_token_count if response.usage_metadata else 0
        return text.strip(), tokens

    raise ValueError(f"Unknown vendor: {vendor}")


def _format_candidates(
    candidates: list[dict],
    condition: str,
    vendor: VendorStyle,
    variant_map: dict[str, dict[str, str]],
) -> str:
    """Format candidate tools for the selection prompt.

    Candidates must be pre-shuffled by the caller (_prepare_candidate_prompt)
    to control position bias.
    """
    lines: list[str] = []
    for i, cand in enumerate(candidates, 1):
        tool_id = cand["tool_id"]
        if condition == "treatment" and tool_id in variant_map:
            desc = variant_map[tool_id].get(vendor.value, cand.get("description", ""))
        else:
            desc = cand.get("description", "")
        lines.append(f"{i}. **{tool_id}**: {desc}")
    return "\n".join(lines)


def _stable_shuffle_seed(query_id: str, vendor: str, condition: str, rep: int) -> int:
    """Return a deterministic seed stable across Python processes."""
    key = "\x1f".join([query_id, vendor, condition, str(rep)])
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")


def _ordered_candidates(candidates: list[dict], shuffle_seed: int | None = None) -> list[dict]:
    """Return copied candidates in prompt order."""
    ordered = [dict(c) for c in candidates]
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(ordered)
    return ordered


def _prepare_candidate_prompt(
    candidates: list[dict],
    condition: str,
    vendor: VendorStyle,
    variant_map: dict[str, dict[str, str]],
    shuffle_seed: int | None = None,
) -> tuple[str, list[dict]]:
    """Build prompt text and return the exact candidate order used for parsing."""
    ordered = _ordered_candidates(candidates, shuffle_seed)
    return _format_candidates(ordered, condition, vendor, variant_map), ordered


def _match_response_to_tool_id(response: str, candidates: list[dict]) -> str:
    """Match LLM response text to a candidate tool_id (best effort).

    Handles formats: bare tool_id, numbered ("1."), quoted, backtick-wrapped.
    """
    response_clean = response.strip().strip('"').strip("'").strip("`").strip()

    # Exact match
    for cand in candidates:
        if cand["tool_id"] == response_clean:
            return cand["tool_id"]

    # Number-based match ("1", "1.", "1. tool_id")
    for i, cand in enumerate(candidates, 1):
        if response_clean == str(i) or response_clean.startswith(f"{i}."):
            return cand["tool_id"]

    # Substring match
    for cand in candidates:
        if cand["tool_id"] in response_clean:
            return cand["tool_id"]

    # Tool name match (after ::)
    for cand in candidates:
        tool_name = cand["tool_id"].split("::")[-1]
        if tool_name in response_clean:
            return cand["tool_id"]

    return response_clean


async def run_experiment(
    queries: list[dict],
    config: ExperimentConfig,
    variant_store: VariantStore,
    settings: Settings,
) -> list[TrialResult]:
    """Run the full A/B experiment across all queries, vendors, and conditions."""
    all_variants = variant_store.load_all()
    variant_map: dict[str, dict[str, str]] = {}
    for v in all_variants:
        variant_map.setdefault(v.tool_id, {})[v.vendor.value] = v.description

    all_trials: list[TrialResult] = []
    total = len(queries) * len(config.vendors) * config.repetitions * 2
    logger.info(
        f"Running {total} trials ({len(queries)} queries x {len(config.vendors)} vendors"
        f" x {config.repetitions} reps x 2 conditions)"
    )

    trial_count = 0
    for q_entry in queries:
        query_id = q_entry["query_id"]
        query = q_entry["query"]
        target_tool_id = q_entry["target_tool_id"]
        candidates = q_entry["candidates"]

        for vendor in config.vendors:
            for condition in ("control", "treatment"):
                for rep in range(1, config.repetitions + 1):
                    trial_count += 1
                    shuffle_seed = _stable_shuffle_seed(query_id, vendor.value, condition, rep)
                    candidate_text, ordered_candidates = _prepare_candidate_prompt(
                        candidates,
                        condition,
                        vendor,
                        variant_map,
                        shuffle_seed=shuffle_seed,
                    )
                    prompt = SELECTION_PROMPT.format(
                        top_k=len(candidates),
                        query=query,
                        candidates=candidate_text,
                    )

                    t_start = time.perf_counter()
                    try:
                        response_text, tokens = await _call_vendor_llm(
                            vendor, prompt, settings, config.temperature
                        )
                    except ImportError as e:
                        raise RuntimeError(
                            "Missing experiment vendor SDK. Run with "
                            "`uv run --group experiment ...`."
                        ) from e
                    except Exception as e:
                        logger.warning(f"Trial {trial_count}/{total} failed: {e}")
                        response_text, tokens = "", 0
                    latency_ms = (time.perf_counter() - t_start) * 1000.0

                    selected = _match_response_to_tool_id(response_text, ordered_candidates)

                    trial = TrialResult(
                        query_id=query_id,
                        recommended_tool_id=selected,
                        target_tool_id=target_tool_id,
                        vendor=vendor.value,
                        condition=condition,
                        rep=rep,
                        latency_ms=latency_ms,
                        token_usage=tokens,
                    )
                    all_trials.append(trial)

                    if trial_count % 10 == 0:
                        logger.info(f"Progress: {trial_count}/{total} trials")

    return all_trials


async def main() -> None:
    parser = argparse.ArgumentParser(description="Per-client description A/B experiment")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reps", type=int, default=3, help="Repetitions per condition")
    parser.add_argument(
        "--queries-file", type=str, default=None, help="Path to experiment queries JSON"
    )
    args = parser.parse_args()

    config = ExperimentConfig(repetitions=args.reps)
    settings = Settings()
    variant_store = VariantStore(path=VARIANTS_PATH)

    if not args.queries_file:
        logger.error("--queries-file is required. Generate experiment queries first.")
        logger.info(
            'Format: [{"query": "...", "target_tool_id": "...",'
            ' "candidates": [{"tool_id": "...", "description": "..."}]}]'
        )
        return

    queries = json.loads(Path(args.queries_file).read_text())

    if args.dry_run:
        logger.info(f"Would run {config.trials_per_query * len(queries)} trials")
        logger.info(
            f"Queries: {len(queries)}, Vendors: {config.vendors}, Reps: {config.repetitions}"
        )
        return

    trials = await run_experiment(queries, config, variant_store, settings)
    summary = compute_experiment_summary(trials)

    # Per-tool breakdown
    from scripts_helpers.selection_experiment import compute_per_tool_summary

    tool_summary = compute_per_tool_summary(trials)

    mcnemar_result = compute_mcnemar_summary(trials)
    if mcnemar_result is not None:
        logger.info(
            "McNemar's test: stat={stat:.2f}, p={p:.4f}, b={b}, c={c}",
            stat=mcnemar_result["statistic"],
            p=mcnemar_result["p_value"],
            b=mcnemar_result["b"],
            c=mcnemar_result["c"],
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "config": config.model_dump(),
        "n_queries": len(queries),
        "n_trials": len(trials),
        "summary": summary,
        "trials": [t.model_dump() for t in trials],
    }
    result["tool_summary"] = tool_summary
    result["mcnemar"] = mcnemar_result
    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    logger.info(f"Results saved to {OUTPUT_PATH}")

    for vendor, data in summary.items():
        ctrl = data.get("control", {}).get("selection_rate", 0)
        treat = data.get("treatment", {}).get("selection_rate", 0)
        imp = data.get("improvement", 0)
        logger.info(f"{vendor}: control={ctrl:.1%}, treatment={treat:.1%}, delta={imp:+.1%}")

    logger.info("Per-tool breakdown:")
    for tid, data in tool_summary.items():
        ctrl = data.get("control", {}).get("selection_rate", 0)
        treat = data.get("treatment", {}).get("selection_rate", 0)
        imp = data.get("improvement", 0)
        logger.info(f"  {tid}: control={ctrl:.1%}, treatment={treat:.1%}, delta={imp:+.1%}")


if __name__ == "__main__":
    asyncio.run(main())
