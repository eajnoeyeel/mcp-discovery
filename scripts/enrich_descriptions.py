"""Description enrichment pipeline for MCP-Zero tools.

Enriches tool descriptions to improve sparse vector input quality.
All tools are enriched via LLM (GPT-4o-mini, MFTR + Tool-REX inspired pattern).
Supports incremental re-run: tools already in the output file are skipped.

Output: data/enriched/tool_profiles.jsonl
  Each line: {"tool_id": "...", "enriched_text": "...", "method": "llm|rule"}

Usage:
    PYTHONPATH=src uv run python scripts/enrich_descriptions.py
    PYTHONPATH=src uv run python scripts/enrich_descriptions.py --rule-only
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from openai import AsyncOpenAI

from mcp_discovery.config import Settings

load_dotenv()

RAW_PATH = Path("data/raw/mcp_zero_servers.jsonl")
OUTPUT_PATH = Path("data/enriched/tool_profiles.jsonl")

ENRICHMENT_PROMPT = """\
You are a technical writer improving MCP tool descriptions for search retrieval.

Given a tool's metadata, generate three fields:
1. function: embedding-friendly description of what this tool does (1-2 sentences)
2. when_to_use: the user intent or scenario that triggers this tool (1 sentence)
3. tags: exactly 5 comma-separated keywords (domain, action verbs, parameter-related)

RULES:
- Do NOT mention other tools or sibling tools by name
- Do NOT include code examples or API call syntax
- Do NOT use subjective claims ("best", "powerful", "advanced")
- Do NOT invent capabilities not evident from the description and parameters
- Write in English, third person, present tense

Tool name: {tool_name}
Server: {server_id}
Current description: {description}
Parameters: {parameters}

Respond in JSON with keys: function, when_to_use, tags (tags as a list of 5 strings)."""


def _load_all_tools() -> list[dict]:
    """Load all tools from mcp_zero_servers.jsonl."""
    tools: list[dict] = []
    for line in RAW_PATH.read_text().splitlines():
        if line.strip():
            server = json.loads(line)
            sid = server.get("server_id", "")
            for tool in server.get("tools", []):
                tname = tool.get("tool_name", "")
                tid = tool.get("tool_id", f"{sid}::{tname}")
                params = tool.get("parameter_names") or list(
                    (tool.get("input_schema") or {}).get("properties", {}).keys()
                )
                tools.append(
                    {
                        "tool_id": tid,
                        "server_id": sid,
                        "tool_name": tname,
                        "description": tool.get("description", ""),
                        "parameter_names": params,
                    }
                )
    return tools


def _load_already_enriched() -> set[str]:
    """Load tool_ids already present in output file for skip-on-rerun."""
    if not OUTPUT_PATH.exists():
        return set()
    enriched: set[str] = set()
    for line in OUTPUT_PATH.read_text().splitlines():
        if line.strip():
            entry = json.loads(line)
            enriched.add(entry["tool_id"])
    return enriched


def _rule_based_enrich(tool: dict) -> dict:
    """Apply rule-based enrichment: tool_name + description + parameter_names."""
    parts = [tool["tool_name"]]
    if tool["description"]:
        parts.append(tool["description"])
    if tool["parameter_names"]:
        parts.append("Parameters: " + ", ".join(tool["parameter_names"]))
    enriched_text = " ".join(parts)
    return {
        "tool_id": tool["tool_id"],
        "enriched_text": enriched_text,
        "method": "rule",
    }


async def _llm_enrich_one(
    client: AsyncOpenAI,
    tool: dict,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Enrich a single tool using GPT-4o-mini with concurrency limit."""
    params_str = ", ".join(tool["parameter_names"]) if tool["parameter_names"] else "(none)"
    prompt = ENRICHMENT_PROMPT.format(
        tool_name=tool["tool_name"],
        server_id=tool["server_id"],
        description=tool["description"] or "(empty)",
        parameters=params_str,
    )
    async with semaphore:
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            data = json.loads(raw)
            function_desc = data.get("function", "")
            when_to_use = data.get("when_to_use", "")
            tags = data.get("tags", [])
            if isinstance(tags, list):
                tags_str = " ".join(tags[:5])
            else:
                tags_str = str(tags)
            llm_text = f"{function_desc} {when_to_use} {tags_str}".strip()
            # Prepend tool_name + param names for SPLADE keyword preservation
            keyword_prefix = tool["tool_name"]
            if tool["parameter_names"]:
                keyword_prefix += " " + " ".join(tool["parameter_names"])
            enriched_text = f"{keyword_prefix} {llm_text}"
            return {
                "tool_id": tool["tool_id"],
                "enriched_text": enriched_text,
                "method": "llm",
            }
        except Exception as e:
            logger.warning(
                f"LLM enrichment failed for {tool['tool_id']}, falling back to rule-based: {e}"
            )
            return _rule_based_enrich(tool)


async def main(rule_only: bool = False) -> None:
    if not RAW_PATH.exists():
        logger.error(f"Raw data not found: {RAW_PATH}")
        sys.exit(1)

    all_tools = _load_all_tools()
    logger.info(f"Loaded {len(all_tools)} tools from {RAW_PATH}")

    already_enriched = _load_already_enriched()
    if already_enriched:
        logger.info(f"Skipping {len(already_enriched)} already-enriched tools")
        all_tools = [t for t in all_tools if t["tool_id"] not in already_enriched]
        logger.info(f"Remaining to process: {len(all_tools)}")

    if not all_tools:
        logger.info("All tools already enriched. Nothing to do.")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []

    if rule_only:
        for tool in all_tools:
            results.append(_rule_based_enrich(tool))
        logger.info(f"Rule-only mode: processed {len(results)} tools with rule-based enrichment")
    else:
        settings = Settings()
        if not settings.openai_api_key:
            logger.error("OPENAI_API_KEY not set — use --rule-only or set the env var")
            sys.exit(1)
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        semaphore = asyncio.Semaphore(5)
        logger.info(f"Starting LLM enrichment for {len(all_tools)} tools...")
        llm_results = await asyncio.gather(
            *[_llm_enrich_one(client, tool, semaphore) for tool in all_tools]
        )
        results.extend(llm_results)
        llm_success = sum(1 for r in llm_results if r["method"] == "llm")
        llm_fallback = sum(1 for r in llm_results if r["method"] == "rule")
        logger.info(f"LLM enrichment: {llm_success} success, {llm_fallback} rule fallback")

    # Append to output file (supports re-run skip)
    mode = "a" if already_enriched else "w"
    with OUTPUT_PATH.open(mode) as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total_written = len(already_enriched) + len(results)
    logger.info(f"Wrote {len(results)} entries (total in file: {total_written})")
    logger.info(f"Output: {OUTPUT_PATH}")

    # Summary stats
    rule_count = sum(1 for r in results if r["method"] == "rule")
    llm_count = sum(1 for r in results if r["method"] == "llm")
    logger.info(f"Method breakdown — rule: {rule_count}, llm: {llm_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enrich MCP tool descriptions for sparse vector retrieval"
    )
    parser.add_argument(
        "--rule-only",
        action="store_true",
        help="Use rule-based enrichment only (no OpenAI API calls)",
    )
    args = parser.parse_args()
    asyncio.run(main(rule_only=args.rule_only))
