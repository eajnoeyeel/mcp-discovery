"""Ground Truth loading, filtering, and splitting utilities."""

import json
from pathlib import Path

from loguru import logger
from openai import AsyncOpenAI

from mcp_discovery.models import (
    TOOL_ID_SEPARATOR,
    Category,
    Difficulty,
    GroundTruthEntry,
    MCPServer,
    MCPTool,
)


def load_ground_truth(
    path: Path,
    difficulty: Difficulty | None = None,
    category: Category | None = None,
    only_verified: bool = False,
) -> list[GroundTruthEntry]:
    """Load and optionally filter a JSONL ground truth file.

    Args:
        path: Path to .jsonl file (one GroundTruthEntry per line).
        difficulty: If set, return only entries with this difficulty.
        category: If set, return only entries in this category.
        only_verified: If True, return only manually_verified=True entries.

    Returns:
        List of validated GroundTruthEntry objects.

    Raises:
        FileNotFoundError: if path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Ground truth file not found: {path}")

    entries: list[GroundTruthEntry] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        entry = GroundTruthEntry.model_validate_json(line)
        if difficulty is not None and entry.difficulty != difficulty:
            continue
        if category is not None and entry.category != category:
            continue
        if only_verified and not entry.manually_verified:
            continue
        entries.append(entry)

    logger.info(f"Loaded {len(entries)} ground truth entries from {path}")
    return entries


def merge_ground_truth(*paths: Path) -> list[GroundTruthEntry]:
    """Merge multiple JSONL files into one list.

    Raises:
        ValueError: if any query_id appears more than once across all files.
    """
    all_entries: list[GroundTruthEntry] = []
    seen_ids: set[str] = set()

    for path in paths:
        for entry in load_ground_truth(path):
            if entry.query_id in seen_ids:
                raise ValueError(f"duplicate query_id '{entry.query_id}' found in {path}")
            seen_ids.add(entry.query_id)
            all_entries.append(entry)

    logger.info(f"Merged {len(all_entries)} entries from {len(paths)} files")
    return all_entries


def split_by_difficulty(
    entries: list[GroundTruthEntry],
) -> dict[Difficulty, list[GroundTruthEntry]]:
    """Group entries by difficulty level.

    Always returns all three keys (EASY, MEDIUM, HARD), even if some are empty.

    Args:
        entries: Flat list of GroundTruthEntry objects.

    Returns:
        Dict mapping each Difficulty to its entries.
    """
    groups: dict[Difficulty, list[GroundTruthEntry]] = {
        Difficulty.EASY: [],
        Difficulty.MEDIUM: [],
        Difficulty.HARD: [],
    }
    for entry in entries:
        groups[entry.difficulty].append(entry)
    return groups


class QualityGateError(Exception):
    """Raised when synthetic GT fails a quality check."""


class QualityGate:
    """Validates synthetic ground truth against quality criteria.

    Checks:
    - Difficulty distribution matches seed set (within tolerance)
    - Medium/Hard queries do not contain tool names (keyword leakage)
    """

    DIFFICULTY_TOLERANCE = 0.15

    def check_difficulty_distribution(
        self,
        synthetic: list[GroundTruthEntry],
        seed: list[GroundTruthEntry],
    ) -> None:
        """Raise QualityGateError if synthetic distribution deviates > 15% from seed.

        Args:
            synthetic: LLM-generated entries to validate.
            seed: Reference seed set defining the target distribution.

        Raises:
            QualityGateError: if any difficulty's proportion deviates too much.
        """
        if not synthetic:
            raise QualityGateError("Synthetic set is empty")

        n_synthetic = len(synthetic)
        n_seed = len(seed)

        for diff in Difficulty:
            seed_count = sum(1 for e in seed if e.difficulty == diff)
            synth_count = sum(1 for e in synthetic if e.difficulty == diff)
            seed_ratio = seed_count / n_seed if n_seed > 0 else 0.0
            synth_ratio = synth_count / n_synthetic
            deviation = abs(synth_ratio - seed_ratio)
            if deviation > self.DIFFICULTY_TOLERANCE:
                raise QualityGateError(
                    f"difficulty distribution check failed for '{diff.value}': "
                    f"seed={seed_ratio:.0%}, synthetic={synth_ratio:.0%}, "
                    f"deviation={deviation:.0%} > tolerance={self.DIFFICULTY_TOLERANCE:.0%}"
                )

    def check_no_tool_name_leakage(
        self,
        entries: list[GroundTruthEntry],
        tool_names: list[str],
    ) -> None:
        """Raise QualityGateError if medium/hard queries contain any tool name.

        Easy queries are allowed to contain tool names (that's what makes them easy).
        Medium and Hard must NOT contain tool names — they should require semantic search.

        Args:
            entries: Entries to check.
            tool_names: List of tool names to look for (lowercase comparison).

        Raises:
            QualityGateError: listing all violating queries.
        """
        violations = []
        for entry in entries:
            if entry.difficulty == Difficulty.EASY:
                continue
            query_lower = entry.query.lower()
            for tool_name in tool_names:
                if tool_name.lower() in query_lower:
                    violations.append(
                        f"[{entry.query_id}] query '{entry.query}' contains tool name '{tool_name}'"
                    )
                    break
        if violations:
            raise QualityGateError(
                f"keyword leakage in {len(violations)} entries:\n" + "\n".join(violations)
            )


def parse_queries(
    raw: str,
    tool: MCPTool,
    *,
    server_id: str = "",
    server_category: Category = Category.GENERAL,
    author: str = "gpt-4o-mini",
    created_at: str = "",
    start_counter: int = 1,
) -> list[GroundTruthEntry]:
    """Parse raw LLM JSON output into GroundTruthEntry objects.

    Args:
        raw: Raw JSON string (possibly wrapped in markdown fences).
        tool: The MCPTool these queries target.
        server_id: Server ID (defaults to tool.server_id if empty).
        server_category: Category for generated entries.
        author: Author field for provenance.
        created_at: ISO 8601 date string.
        start_counter: Starting number for query_id generation.

    Returns:
        List of validated GroundTruthEntry objects (source='llm_synthetic',
        manually_verified=False). Malformed items are skipped with a warning.
    """
    if not server_id:
        server_id = tool.server_id
    if not created_at:
        from datetime import date

        created_at = date.today().isoformat()

    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()

    try:
        items = json.loads(text)
        if not isinstance(items, list):
            items = []
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Failed to parse LLM output as JSON for {tool.tool_id}")
        return []

    entries: list[GroundTruthEntry] = []
    counter = start_counter

    for item in items:
        if not isinstance(item, dict) or "query" not in item:
            logger.warning(f"Skipping malformed item for {tool.tool_id}: {item!r}")
            continue

        query_id = f"gt-synth-{counter:04d}"
        alt_tool_names = item.get("alternative_tool_names", [])
        alt_tool_ids = [f"{server_id}{TOOL_ID_SEPARATOR}{n}" for n in alt_tool_names] or None
        difficulty_val = item.get("difficulty", "medium")
        ambiguity_val = item.get("ambiguity", "low")

        # Ensure consistency: hard requires non-low ambiguity
        if difficulty_val == "hard" and ambiguity_val == "low":
            if not alt_tool_ids:
                logger.warning(
                    f"Skipping hard/low-ambiguity entry for {tool.tool_id}: "
                    "no alternative_tool_names provided by LLM"
                )
                continue
            ambiguity_val = "medium"

        # Ensure medium/high ambiguity has alternatives
        if ambiguity_val in ("medium", "high") and not alt_tool_ids:
            ambiguity_val = "low"

        try:
            entry = GroundTruthEntry(
                query_id=query_id,
                query=item["query"],
                correct_server_id=server_id,
                correct_tool_id=tool.tool_id,
                difficulty=difficulty_val,
                category=server_category,
                ambiguity=ambiguity_val,
                source="llm_synthetic",
                manually_verified=False,
                author=author,
                created_at=created_at,
                alternative_tools=alt_tool_ids,
                notes=item.get("notes"),
            )
            entries.append(entry)
            counter += 1
        except Exception as e:
            logger.warning(f"Skipping malformed entry for {tool.tool_id}: {e}")

    return entries


def save(entries: list[GroundTruthEntry], output_path: Path) -> int:
    """Write GroundTruthEntry objects to a JSONL file.

    Creates parent directories if they don't exist.

    Args:
        entries: List of entries to write.
        output_path: Path to output .jsonl file.

    Returns:
        Number of entries written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for entry in entries:
            f.write(entry.model_dump_json() + "\n")
    logger.info(f"Saved {len(entries)} entries to {output_path}")
    return len(entries)


_SYNTHETIC_PROMPT = """You are generating test queries for a tool recommendation system.

Tool: {tool_name}
Server ID: {server_id}
Description: {description}

Generate 10 natural language queries a user would write when they need this tool.
Distribute difficulty: 4 Easy, 4 Medium, 2 Hard.

Rules:
- Do NOT include the exact tool_name in Medium or Hard queries
- Vary sentence structures (question, command, statement of need)
- Hard queries must be genuinely ambiguous (another tool could also match)

Return a JSON array of 10 objects:
[
  {{
    "query": "...",
    "difficulty": "easy|medium|hard",
    "ambiguity": "low|medium|high",
    "alternative_tool_names": [],
    "notes": "why this difficulty/ambiguity"
  }},
  ...
]"""


async def generate_synthetic_gt(
    servers: list[MCPServer],
    client: AsyncOpenAI,
    model: str = "gpt-4o-mini",
    author: str = "gpt-4o-mini",
    created_at: str | None = None,
    category_map: dict[str, Category] | None = None,
) -> list[GroundTruthEntry]:
    """Generate synthetic ground truth entries using LLM for each tool.

    Generates 10 queries per tool. Filters out entries that fail basic validation.
    Does NOT run QualityGate — caller must do that.

    Args:
        servers: MCPServer list to generate queries for.
        client: AsyncOpenAI client (caller provides key).
        model: OpenAI model to use.
        author: Author field in generated entries.
        created_at: ISO 8601 date string.
        category_map: Optional server_id -> Category override.

    Returns:
        List of GroundTruthEntry objects (unverified, source='llm_synthetic').
    """
    if created_at is None:
        from datetime import date

        created_at = date.today().isoformat()

    entries: list[GroundTruthEntry] = []
    counter = 1

    for server in servers:
        server_category = (
            category_map.get(server.server_id, Category.GENERAL)
            if category_map
            else Category.GENERAL
        )
        for tool in server.tools:
            prompt = _SYNTHETIC_PROMPT.format(
                tool_name=tool.tool_name,
                server_id=server.server_id,
                description=tool.description or tool.tool_name,
            )
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                )
                raw = (response.choices[0].message.content or "[]").strip()
            except Exception as e:
                logger.warning(f"Skipping {tool.tool_id}: LLM call failed: {e}")
                continue

            parsed = parse_queries(
                raw,
                tool,
                server_id=server.server_id,
                server_category=server_category,
                author=author,
                created_at=created_at,
                start_counter=counter,
            )
            entries.extend(parsed)
            counter += len(parsed)

    logger.info(f"Generated {len(entries)} synthetic entries for {len(servers)} servers")
    return entries
