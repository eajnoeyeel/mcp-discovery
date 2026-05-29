"""Convert MCP-Atlas parquet → per-step GroundTruthEntry JSONL (ADR-0012).

MCP-Atlas contains 500 human-authored multi-step tasks (avg 4.8 tool calls/task).
This script decomposes each trajectory into per-step single-tool GT entries:

1. Load parquet files from data/external/mcp-atlas/
2. Parse TRAJECTORY column → extract tool calls
3. Filter boilerplate calls (filesystem_list_allowed_directories, etc.)
4. Generate per-step query via LLM (gpt-4o-mini)
5. Output GroundTruthEntry-compatible JSONL

Usage:
    uv run python scripts/convert_mcp_atlas.py
    uv run python scripts/convert_mcp_atlas.py --input data/external/mcp-atlas/ --max-tasks 80
    uv run python scripts/convert_mcp_atlas.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path so we can import src.models
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from mcp_discovery.models import TOOL_ID_SEPARATOR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_INPUT_DIR = "data/external/mcp-atlas"
DEFAULT_OUTPUT_PATH = "data/ground_truth/mcp_atlas.jsonl"

BOILERPLATE_BLOCKLIST: frozenset[str] = frozenset(
    {
        "filesystem_list_allowed_directories",
        "cli-mcp-server_show_security_rules",
        "desktop-commander_get_config",
        "memory_list_memories",
    }
)

# Tool IDs where MCP-Atlas name differs from actual server tool name.
# Format: "server_id::atlas_tool_name" → "server_id::actual_tool_name"
# Unmappable entries (no clear match in server) are mapped to None → dropped.
TOOL_ID_REMAP: dict[str, str | None] = {
    "context7::get-library-docs": "context7::query-docs",
    "fetch::fetch": "fetch::fetch_markdown",
    "filesystem::directory_tree": "filesystem::list_directory",
    "filesystem::read_text_file": "filesystem::read_file",
    "github::get_repository": None,
    "google-maps::maps_directions": "google-maps::GOOGLE_MAPS_GET_DIRECTION",
    "google-maps::maps_distance_matrix": "google-maps::GOOGLE_MAPS_DISTANCE_MATRIX_API",
    "google-maps::maps_elevation": None,
    "google-maps::maps_geocode": "google-maps::GOOGLE_MAPS_GEOCODING_API",
    "google-maps::maps_place_details": None,
    "google-maps::maps_search_places": "google-maps::GOOGLE_MAPS_TEXT_SEARCH",
    "notion::API-get-users": "notion::notion-get-users",
    "notion::API-post-database-query": "notion::notion-search",
    "notion::API-post-search": "notion::notion-search",
    "oxylabs::google_search_scraper": "oxylabs::oxylabs_scraper",
    "oxylabs::universal_scraper": "oxylabs::oxylabs_scraper",
    "pubmed::search_pubmed_advanced": "pubmed::search_articles",
    "pubmed::search_pubmed_key_words": "pubmed::search_articles",
    "slack::conversations_search_messages": None,
}

_HYPHENATED_SERVERS: frozenset[str] = frozenset(
    {
        "brave-search",
        "cli-mcp-server",
        "clinicaltrialsgov-mcp-server",
        "ddg-search",
        "desktop-commander",
        "e2b-server",
        "google-maps",
        "google-workspace",
        "lara-translate",
        "mcp-code-executor",
        "mcp-server-code-runner",
        "met-museum",
        "national-parks",
        "open-library",
        "osm-mcp-server",
        "weather-data",
    }
)

# Pre-sorted longest-first for greedy matching
_HYPHENATED_SERVERS_SORTED: tuple[str, ...] = tuple(
    sorted(_HYPHENATED_SERVERS, key=len, reverse=True)
)


# ---------------------------------------------------------------------------
# Pure functions (testable without external deps)
# ---------------------------------------------------------------------------


def split_tool_name(full_name: str) -> tuple[str, str]:
    """Split MCP-Atlas tool name into (server_id, tool_name).

    Hyphenated servers are matched via _HYPHENATED_SERVERS lookup.
    Simple servers split on first underscore.

    Examples:
        "github_search_repositories" → ("github", "search_repositories")
        "brave-search_brave_web_search" → ("brave-search", "brave_web_search")
        "sometool" → ("sometool", "")
    """
    # Try hyphenated server prefix (longest match first)
    for prefix in _HYPHENATED_SERVERS_SORTED:
        candidate = prefix + "_"
        if full_name.startswith(candidate):
            return prefix, full_name[len(candidate) :]

    # Simple split on first underscore
    if "_" in full_name:
        server_id, tool_name = full_name.split("_", 1)
        return server_id, tool_name

    # Single word without underscore
    return full_name, ""


def is_boilerplate(tool_call_name: str) -> bool:
    """Check whether a tool call name is in the boilerplate blocklist."""
    return tool_call_name in BOILERPLATE_BLOCKLIST


def parse_trajectory(trajectory: list[dict]) -> list[dict]:
    """Extract tool calls from MCP-Atlas TRAJECTORY JSON.

    MCP-Atlas trajectory format:
        [
            {"role": "assistant", "tool_calls": [{"function": {"name": ..., "arguments": ...}}]},
            {"role": "tool", "content": "...", "name": null},
            ...
        ]

    Returns:
        List of {"name": str, "arguments": str, "call_index": int}.
    """
    calls: list[dict] = []
    call_index = 0

    for message in trajectory:
        if message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls") or []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name")
            if name is None:
                continue
            calls.append(
                {
                    "name": name,
                    "arguments": func.get("arguments", ""),
                    "call_index": call_index,
                }
            )
            call_index += 1

    return calls


def extract_substantive_steps(tool_calls: list[dict]) -> list[dict]:
    """Filter out boilerplate tool calls, keeping only substantive ones."""
    return [tc for tc in tool_calls if not is_boilerplate(tc["name"])]


def build_ground_truth_entry(
    task_id: str,
    task_index: int,
    step_index: int,
    tool_call_name: str,
    query: str,
    prompt: str,
) -> dict | None:
    """Build a GroundTruthEntry-compatible dict for a single step.

    Args:
        task_id: Original MCP-Atlas task ID for lineage.
        task_index: 1-based task index (for query_id formatting).
        step_index: 0-based step position within the task.
        tool_call_name: Full MCP-Atlas tool name (e.g. "github_search_repositories").
        query: Per-step query (LLM-generated or from prompt).
        prompt: Original task prompt (for notes/context).

    Returns:
        Dict compatible with GroundTruthEntry.model_validate().
    """
    server_id, tool_name = split_tool_name(tool_call_name)
    tool_id = f"{server_id}{TOOL_ID_SEPARATOR}{tool_name}"

    # Apply remap if tool name differs between Atlas and actual server
    if tool_id in TOOL_ID_REMAP:
        remapped = TOOL_ID_REMAP[tool_id]
        if remapped is None:
            return None  # No match in server → drop this entry
        server_id = remapped.split(TOOL_ID_SEPARATOR)[0]
        tool_id = remapped

    return {
        "query_id": f"gt-atlas-{task_index:03d}-s{step_index:02d}",
        "query": query,
        "correct_server_id": server_id,
        "correct_tool_id": tool_id,
        "difficulty": "medium",
        "category": "general",
        "ambiguity": "low",
        "source": "external_mcp_atlas",
        "manually_verified": True,
        "author": "scale_ai",
        "created_at": "2026-03-28",
        "task_type": "single_step",
        "origin_task_id": task_id,
        "step_index": step_index,
        "notes": f"MCP-Atlas per-step decomposition. Original prompt: {prompt[:200]}",
    }


# ---------------------------------------------------------------------------
# Async / LLM functions
# ---------------------------------------------------------------------------


async def generate_step_query(
    prompt: str,
    tool_call_name: str,
    arguments: str,
    step_index: int,
    total_steps: int,
) -> str:
    """Generate a per-step query using LLM (gpt-4o-mini).

    Given the original task prompt and a specific tool call,
    generate a natural-language query that a user would ask
    to trigger this specific tool.

    Args:
        prompt: Original MCP-Atlas task prompt.
        tool_call_name: The tool being called at this step.
        arguments: JSON string of tool call arguments.
        step_index: 0-based step position.
        total_steps: Total substantive steps in the task.

    Returns:
        Generated per-step query string.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI()

    server_id, tool_name = split_tool_name(tool_call_name)

    system_prompt = (
        "You generate concise, natural-language queries that a user would type "
        "to trigger a specific MCP tool. The query should be self-contained and "
        "specific enough to uniquely identify the intended tool action. "
        "Output ONLY the query, no explanation."
    )

    user_prompt = (
        f"Original task: {prompt}\n\n"
        f"This is step {step_index + 1} of {total_steps} in the task.\n"
        f"Tool being called: {tool_call_name} (server: {server_id}, tool: {tool_name})\n"
        f"Arguments: {arguments}\n\n"
        f"Generate a natural-language query that would trigger this specific tool call."
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=150,
    )

    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# I/O functions
# ---------------------------------------------------------------------------


def load_parquet_tasks(input_dir: Path) -> list[dict]:
    """Load tasks from MCP-Atlas parquet files.

    Args:
        input_dir: Directory containing parquet files.

    Returns:
        List of task dictionaries.
    """
    try:
        import pyarrow.parquet as pq
    except ImportError:
        logger.error("pyarrow not installed. Run: uv add pyarrow")
        raise

    parquet_files = sorted(input_dir.glob("*.parquet"))

    if not parquet_files:
        logger.error(f"No parquet files found in {input_dir}")
        return []

    import pyarrow as pa

    table = pq.read_table(parquet_files[0])
    for pf in parquet_files[1:]:
        table = pa.concat_tables([table, pq.read_table(pf)])

    columns = table.to_pydict()
    n_rows = len(next(iter(columns.values())))
    tasks = [{col: columns[col][i] for col in columns} for i in range(n_rows)]
    logger.info(f"Loaded {len(tasks)} tasks from {len(parquet_files)} parquet files")

    return tasks


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


async def _process_tasks(
    tasks: list[dict],
    output_path: Path,
    max_tasks: int,
    dry_run: bool,
    allowed_servers: frozenset[str] | None = None,
    task_offset: int = 0,
    task_index_start: int = 1,
    append: bool = False,
) -> None:
    """Process MCP-Atlas tasks into per-step GT entries.

    Args:
        allowed_servers: If provided, only tool calls whose server_id is in this set
            are included (ADR-0012 pool filter). None = no filter (include all).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_entries = 0
    skipped_tasks = 0
    skipped_boilerplate = 0
    skipped_not_in_pool = 0
    task_index = task_index_start - 1

    entries: list[dict] = []

    for task in tasks[task_offset:task_offset + max_tasks]:
        # MCP-Atlas stores trajectory as JSON string or list
        trajectory_raw = task.get("TRAJECTORY") or task.get("trajectory")
        if trajectory_raw is None:
            skipped_tasks += 1
            continue

        # Parse trajectory JSON if it's a string
        if isinstance(trajectory_raw, str):
            try:
                trajectory = json.loads(trajectory_raw)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse trajectory JSON for task index {task_index}")
                skipped_tasks += 1
                continue
        else:
            trajectory = trajectory_raw

        if not isinstance(trajectory, list):
            skipped_tasks += 1
            continue

        # Extract and filter tool calls
        all_calls = parse_trajectory(trajectory)
        substantive = extract_substantive_steps(all_calls)
        skipped_boilerplate += len(all_calls) - len(substantive)

        # ADR-0012 pool filter: only include steps whose server is in the pool
        if allowed_servers is not None:
            filtered = [
                tc for tc in substantive if split_tool_name(tc["name"])[0] in allowed_servers
            ]
            skipped_not_in_pool += len(substantive) - len(filtered)
            substantive = filtered

        if not substantive:
            skipped_tasks += 1
            continue

        task_index += 1
        task_id = task.get("task_id") or task.get("id") or f"atlas-task-{task_index}"
        prompt = task.get("PROMPT") or task.get("prompt") or task.get("instruction") or ""

        for step_idx, tc in enumerate(substantive):
            if dry_run:
                query = f"[DRY-RUN] Step {step_idx} of task {task_id}: {tc['name']}"
            else:
                try:
                    query = await generate_step_query(
                        prompt=prompt,
                        tool_call_name=tc["name"],
                        arguments=tc["arguments"],
                        step_index=step_idx,
                        total_steps=len(substantive),
                    )
                except Exception as e:
                    logger.warning(
                        f"LLM query generation failed for {task_id} step {step_idx}: {e}"
                    )
                    query = f"Use {tc['name']} tool"

            entry = build_ground_truth_entry(
                task_id=task_id,
                task_index=task_index,
                step_index=step_idx,
                tool_call_name=tc["name"],
                query=query,
                prompt=prompt,
            )
            if entry is None:
                logger.debug(f"Dropped unmappable tool: {tc['name']} (task {task_id})")
                continue
            entries.append(entry)
            total_entries += 1

    # Write all entries
    mode = "a" if append else "w"
    with output_path.open(mode) as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    pool_filter_msg = (
        f", {skipped_not_in_pool} steps not in pool" if allowed_servers is not None else ""
    )
    logger.info(
        f"Completed: {total_entries} GT entries from {task_index} tasks "
        f"(skipped {skipped_tasks} tasks, {skipped_boilerplate} boilerplate calls"
        f"{pool_filter_msg})"
    )
    logger.info(f"Output: {output_path}")


def main() -> None:
    """CLI entrypoint for MCP-Atlas → per-step GT conversion."""
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Convert MCP-Atlas parquet → per-step GT JSONL (ADR-0012)"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(DEFAULT_INPUT_DIR),
        help=f"MCP-Atlas parquet directory (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(DEFAULT_OUTPUT_PATH),
        help=f"Output JSONL path (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=80,
        help="Maximum number of tasks to process (default: 80)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip LLM query generation, use placeholder queries",
    )
    parser.add_argument(
        "--task-offset",
        type=int,
        default=0,
        help="Skip first N tasks from parquet (default: 0)",
    )
    parser.add_argument(
        "--task-start-index",
        type=int,
        default=1,
        help="Starting task_index for query_id numbering (default: 1)",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to output file instead of overwriting",
    )
    parser.add_argument(
        "--pool-file",
        type=Path,
        default=None,
        help=(
            "MCP-Zero pool JSONL. Only servers in this pool are included. "
            "Implements ADR-0012 selection criterion. Default: no filter."
        ),
    )
    args = parser.parse_args()

    if not args.input.exists():
        logger.error(f"Input directory not found: {args.input}")
        logger.info("Download MCP-Atlas first. See data/external/README.md")
        return

    tasks = load_parquet_tasks(args.input)
    if not tasks:
        logger.error("No tasks loaded. Check parquet file format.")
        return

    allowed_servers: frozenset[str] | None = None
    if args.pool_file:
        if not args.pool_file.exists():
            logger.error(f"Pool file not found: {args.pool_file}")
            return
        pool_ids: set[str] = set()
        for line in args.pool_file.read_text().splitlines():
            line = line.strip()
            if line:
                pool_ids.add(json.loads(line)["server_id"])
        allowed_servers = frozenset(pool_ids)
        logger.info(
            f"Pool filter: {len(allowed_servers)} allowed servers from {args.pool_file}"
        )

    asyncio.run(
        _process_tasks(
            tasks=tasks,
            output_path=args.output,
            max_tasks=args.max_tasks,
            dry_run=args.dry_run,
            allowed_servers=allowed_servers,
            task_offset=args.task_offset,
            task_index_start=args.task_start_index,
            append=args.append,
        )
    )


if __name__ == "__main__":
    main()
