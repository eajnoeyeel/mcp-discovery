"""Server selection and filtering logic for crawling targets."""

from pathlib import Path

from loguru import logger

from mcp_discovery.models import MCPServerSummary


def filter_deployed(summaries: list[MCPServerSummary]) -> list[MCPServerSummary]:
    """Return only deployed servers."""
    return [s for s in summaries if s.is_deployed]


def sort_by_popularity(summaries: list[MCPServerSummary]) -> list[MCPServerSummary]:
    """Sort by use_count descending."""
    return sorted(summaries, key=lambda s: s.use_count, reverse=True)


def load_curated_list(path: Path) -> list[str]:
    """Load qualified names from a text file (one per line, # comments ignored)."""
    names: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            names.append(stripped)
    return names


def select_servers(
    summaries: list[MCPServerSummary],
    curated_list: Path | None = None,
    max_servers: int = 100,
    require_deployed: bool = True,
) -> list[MCPServerSummary]:
    """Select servers for crawling.

    If curated_list is provided, filter to those names only.
    Otherwise: deployed filter -> popularity sort -> truncate.
    """
    if curated_list is not None:
        curated_names = set(load_curated_list(curated_list))
        result = [s for s in summaries if s.qualified_name in curated_names]
        logger.info(f"Curated list: {len(result)}/{len(curated_names)} servers matched")
        return result[:max_servers]

    result = list(summaries)
    if require_deployed:
        result = filter_deployed(result)
    result = sort_by_popularity(result)
    result = result[:max_servers]
    logger.info(f"Selected {len(result)} servers (deployed={require_deployed}, max={max_servers})")
    return result
