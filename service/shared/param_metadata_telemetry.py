"""Telemetry helper for silent drops inside parameter-metadata normalizers.

Background
----------
`RegisterService._normalize_parameter_metadata`, `_normalize_published_parameter_metadata`,
`DashboardService._normalize_upstream_parameter_metadata`, and
`DashboardService._normalize_published_parameter_metadata` all process lists of
parameter-metadata dicts coming from an upstream HTTP MCP server's `tools/list`
JSON-RPC response. Invalid entries (wrong shape, missing required fields,
Pydantic validation errors) are silently dropped via `continue`, which hides
upstream schema issues from providers trying to debug their own tool
registrations.

This helper emits a **single aggregated** warning per normalizer invocation
(not per dropped entry) when drops occur, with a per-reason count.

Kill switch
-----------
Warnings are gated behind the `MLP_WARN_PARAM_DROPS` env var (default off).
Enable per-incident via `MLP_WARN_PARAM_DROPS=1` when investigating a
provider-reported schema issue. Off-by-default prevents CloudWatch log
volume spikes at provider scale (tools × params × dashboard refresh cycle).
"""

from __future__ import annotations

import os

from loguru import logger

_ENV_FLAG = "MLP_WARN_PARAM_DROPS"


def emit_drop_warning(
    normalizer_name: str,
    dropped: int,
    total: int,
    reason_counts: dict[str, int],
    *,
    context: str | None = None,
    server_id: str | None = None,
) -> None:
    """Emit a single aggregated warning when parameter-metadata entries are dropped.

    Parameters
    ----------
    normalizer_name:
        Name of the normalizer for log correlation (e.g. the method's dotted path).
    dropped:
        Count of entries discarded this call.
    total:
        Total number of entries received (before dropping).
    reason_counts:
        Mapping of reason tag -> count (e.g. {"not_a_dict": 1, "missing_required_fields": 2}).
    context:
        Free-form caller tag ("register", "dashboard_refresh", "dashboard_update", …).
        Omit for pure-library callers; log falls back to "unknown".
    server_id:
        Provider's server_id when available. Helps correlate with upstream
        server identity. Omit if not in scope.

    Notes
    -----
    Honors the ``MLP_WARN_PARAM_DROPS`` env var kill switch (default off).
    Returns early if the env var is unset / not "1" or if no drops occurred.
    """
    if os.environ.get(_ENV_FLAG) != "1":
        return
    if dropped <= 0:
        return
    logger.warning(
        f"{normalizer_name} dropped {dropped}/{total} entries "
        f"(context={context or 'unknown'}, server_id={server_id or 'unknown'}, "
        f"reasons={reason_counts})"
    )
