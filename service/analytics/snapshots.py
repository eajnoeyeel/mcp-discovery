"""Dashboard snapshot builder — aggregates GEO scores per server.

Pure functions. No external API calls, no async required.
Input: tool dicts with geo_score fields (as stored in Supabase).
Output: provider-level snapshot dicts ready for dashboard consumption.
"""

from __future__ import annotations

from collections import defaultdict

# GEO score dimension names (matching src/analytics/geo_score.py GEOScore model)
_GEO_DIMENSIONS: tuple[str, ...] = (
    "clarity",
    "disambiguation",
    "parameter_coverage",
    "boundary",
    "stats",
    "precision",
)

# Tools with total GEO score below this threshold are counted as "low score"
_LOW_SCORE_THRESHOLD: float = 0.5


def _extract_total(tool: dict) -> float:
    """Extract the total GEO score from a tool dict, defaulting to 0.0."""
    geo = tool.get("geo_score")
    if geo is None:
        return 0.0
    if isinstance(geo, dict):
        return float(geo.get("total", 0.0))
    return 0.0


def _extract_dimension(tool: dict, dimension: str) -> float | None:
    """Extract a specific GEO dimension score, returning None if absent."""
    geo = tool.get("geo_score")
    if geo is None or not isinstance(geo, dict):
        return None
    val = geo.get(dimension)
    if val is None:
        return None
    return float(val)


def _safe_avg(values: list[float]) -> float:
    """Compute average, returning 0.0 for empty lists."""
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def build_provider_snapshot(server_id: str, tools: list[dict]) -> dict:
    """Build a dashboard snapshot for a single provider (server).

    Args:
        server_id: The server identifier.
        tools: List of tool dicts, each optionally containing a "geo_score" dict
               with "total" and per-dimension floats.

    Returns:
        A dict with aggregated snapshot data:
        - server_id, tool_count, avg_geo_score, min_geo_score, max_geo_score
        - low_score_count (tools with total < 0.5)
        - dimension_averages (per-dimension averages, only for dimensions present)
    """
    if not tools:
        return {
            "server_id": server_id,
            "tool_count": 0,
            "avg_geo_score": 0.0,
            "min_geo_score": 0.0,
            "max_geo_score": 0.0,
            "low_score_count": 0,
            "dimension_averages": {},
        }

    totals = [_extract_total(t) for t in tools]

    # Per-dimension averages (only include dimensions that have data)
    dimension_averages: dict[str, float] = {}
    for dim in _GEO_DIMENSIONS:
        dim_values = [v for t in tools if (v := _extract_dimension(t, dim)) is not None]
        if dim_values:
            dimension_averages[dim] = _safe_avg(dim_values)

    return {
        "server_id": server_id,
        "tool_count": len(tools),
        "avg_geo_score": _safe_avg(totals),
        "min_geo_score": round(min(totals), 4),
        "max_geo_score": round(max(totals), 4),
        "low_score_count": sum(1 for t in totals if t < _LOW_SCORE_THRESHOLD),
        "dimension_averages": dimension_averages,
    }


def _extract_server_id(tool: dict) -> str:
    """Extract server_id from tool dict, falling back to tool_id prefix."""
    server_id = tool.get("server_id")
    if server_id:
        return str(server_id)
    # Fallback: extract prefix before "::" from tool_id
    tool_id = tool.get("tool_id", "")
    if "::" in tool_id:
        return tool_id.split("::")[0]
    return "unknown"


def build_all_snapshots(tools: list[dict]) -> list[dict]:
    """Build snapshots for all servers from a flat list of tool dicts.

    Groups tools by server_id (or tool_id prefix if server_id is absent),
    then builds a snapshot for each group.

    Args:
        tools: Flat list of tool dicts with server_id and/or tool_id fields.

    Returns:
        List of snapshot dicts, one per server, sorted by server_id.
    """
    if not tools:
        return []

    grouped: dict[str, list[dict]] = defaultdict(list)
    for tool in tools:
        sid = _extract_server_id(tool)
        grouped[sid].append(tool)

    return [
        build_provider_snapshot(server_id=sid, tools=group)
        for sid, group in sorted(grouped.items())
    ]
