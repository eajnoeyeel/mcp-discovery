"""Pool prober orchestrator with ProberRegistry, split semaphore, and secret-scan (ADR-0018).

Key design:
  - ProberRegistry: simple dict mapping transport name -> Prober instance.
  - Split semaphore: stdio=2, http=8 (ScriptProber uses stdio_sem).
  - Secret-scan: keyword + high-entropy-adjacent regex applied to raw probe output
    before cache write. Fail-write on match; logs offending key NAME only.
  - Content-hash cache: data/probes/.cache/<sha256(spec.model_dump_json())>.json,
    24h TTL, gitignored. --force bypasses.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from mcp_discovery.data.probers.base import Prober
from mcp_discovery.data.probers.http_prober import HttpProber
from mcp_discovery.data.probers.script_prober import ScriptProber
from mcp_discovery.data.probers.stdio_prober import StdioProber
from mcp_discovery.models.probe import ProbeErrorKind, ProbeResult, TransportSpec

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Secret-scan regex (Architect FC4):
# keyword + high-entropy adjacency pattern.
# Avoids false-positives on "API key metadata" in descriptions.
# ---------------------------------------------------------------------------

_SECRET_SCAN_RE = re.compile(r"(?i)\b(token|key|auth|secret|bearer)\b.*?[A-Za-z0-9_\-]{32,}")

# Cache directory relative to repo root
_CACHE_DIR_RELATIVE = Path("data/probes/.cache")
_CACHE_TTL_HOURS = 24

# Split semaphore capacities
_STDIO_CONCURRENCY = 2
_HTTP_CONCURRENCY = 8


class ProberRegistry:
    """Simple dict-based registry mapping transport type to Prober instance.

    Not a dynamic plugin registry (probers are a small closed set per ADR-0018).
    """

    def __init__(self) -> None:
        self._probers: dict[str, Prober] = {}

    def register(self, transport: str, prober: Prober) -> None:
        """Register a prober for the given transport type."""
        self._probers[transport] = prober

    def get(self, transport: str) -> Prober | None:
        """Return the prober for the given transport, or None if not registered."""
        return self._probers.get(transport)

    def get_for_spec(self, spec: TransportSpec) -> Prober | None:
        """Return the first registered prober that supports spec, or None."""
        prober = self._probers.get(spec.transport)
        if prober and prober.supports(spec):
            return prober
        # Fallback: linear scan (supports() is the authoritative gate)
        for p in self._probers.values():
            if p.supports(spec):
                return p
        return None

    @property
    def transports(self) -> list[str]:
        return list(self._probers.keys())


def _default_registry() -> ProberRegistry:
    registry = ProberRegistry()
    registry.register("stdio", StdioProber())
    registry.register("http", HttpProber())
    registry.register("script", ScriptProber())
    return registry


def _scan_for_secrets(data: str) -> list[str]:
    """Return list of offending KEY NAMES found (values are never logged).

    Returns empty list when no secrets detected.
    """
    offenders: list[str] = []
    for match in _SECRET_SCAN_RE.finditer(data):
        key_name = match.group(1)
        if key_name not in offenders:
            offenders.append(key_name)
    return offenders


def _cache_path(spec_hash: str, cache_dir: Path) -> Path:
    return cache_dir / f"{spec_hash}.json"


def _is_cache_valid(cache_file: Path) -> bool:
    if not cache_file.exists():
        return False
    mtime = datetime.datetime.fromtimestamp(cache_file.stat().st_mtime, tz=datetime.timezone.utc)
    age = datetime.datetime.now(tz=datetime.timezone.utc) - mtime
    return age.total_seconds() < _CACHE_TTL_HOURS * 3600


def _read_cache(cache_file: Path) -> ProbeResult | None:
    try:
        return ProbeResult.model_validate_json(cache_file.read_text())
    except Exception as exc:
        logger.warning(f"Cache read failed for {cache_file}: {exc} -- ignoring")
        return None


def _write_cache(result: ProbeResult, cache_file: Path) -> None:
    """Write result to cache after secret-scan. Fail-write on secret detection."""
    serialised = result.model_dump_json()
    offenders = _scan_for_secrets(serialised)
    if offenders:
        logger.error(
            f"Secret-scan triggered before cache write for server '{result.server_id}'"
            f" -- offending key names: {offenders}. Cache write ABORTED."
        )
        return
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(serialised)
    except Exception as exc:
        logger.warning(f"Cache write failed for {cache_file}: {exc}")


async def probe_server(
    server_id: str,
    spec: TransportSpec,
    *,
    registry: ProberRegistry | None = None,
    stdio_sem: asyncio.Semaphore | None = None,
    http_sem: asyncio.Semaphore | None = None,
    cache_dir: Path | None = None,
    force: bool = False,
) -> ProbeResult:
    """Probe a single server, respecting the split semaphore and content-hash cache.

    Args:
        server_id: Canonical server identifier.
        spec: Transport spec describing how to connect.
        registry: ProberRegistry to use; defaults to _default_registry().
        stdio_sem: Semaphore for stdio/script probes (capacity 2).
        http_sem: Semaphore for HTTP probes (capacity 8).
        cache_dir: Path to cache directory; defaults to data/probes/.cache/.
        force: If True, bypass cache and re-probe.
    """
    if registry is None:
        registry = _default_registry()

    spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()

    # Resolve cache directory relative to repo root
    if cache_dir is None:
        cache_dir = Path(__file__).resolve().parents[4] / _CACHE_DIR_RELATIVE

    cache_file = _cache_path(spec_hash, cache_dir)
    if not force and _is_cache_valid(cache_file):
        cached = _read_cache(cache_file)
        if cached is not None:
            logger.info(f"probe_server: cache hit for '{server_id}' (spec_hash={spec_hash[:8]})")
            return cached

    prober = registry.get_for_spec(spec)
    if prober is None:
        logger.warning(f"probe_server: no prober registered for transport '{spec.transport}'")
        return ProbeResult(
            server_id=server_id,
            success=False,
            spec_hash=spec_hash,
            error_kind=ProbeErrorKind.TRANSPORT_UNSUPPORTED,
            error_message=f"No prober registered for transport: {spec.transport}",
        )

    # Select semaphore by transport type (script uses stdio semaphore)
    is_http = spec.transport == "http"
    if is_http:
        sem = http_sem or asyncio.Semaphore(_HTTP_CONCURRENCY)
    else:
        sem = stdio_sem or asyncio.Semaphore(_STDIO_CONCURRENCY)

    async with sem:
        result = await prober.probe(server_id, spec)

    _write_cache(result, cache_file)
    return result


async def probe_servers(
    specs: dict[str, TransportSpec],
    *,
    registry: ProberRegistry | None = None,
    cache_dir: Path | None = None,
    force: bool = False,
) -> dict[str, ProbeResult]:
    """Probe multiple servers in parallel, respecting split semaphores.

    Args:
        specs: Mapping server_id -> TransportSpec.
        registry: ProberRegistry to use; defaults to _default_registry().
        cache_dir: Path to cache directory.
        force: If True, bypass cache for all probes.

    Returns:
        Mapping server_id -> ProbeResult.
    """
    if registry is None:
        registry = _default_registry()

    stdio_sem = asyncio.Semaphore(_STDIO_CONCURRENCY)
    http_sem = asyncio.Semaphore(_HTTP_CONCURRENCY)

    tasks = {
        server_id: probe_server(
            server_id,
            spec,
            registry=registry,
            stdio_sem=stdio_sem,
            http_sem=http_sem,
            cache_dir=cache_dir,
            force=force,
        )
        for server_id, spec in specs.items()
    }

    results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results: dict[str, ProbeResult] = {}
    for server_id, result in zip(tasks.keys(), results_list):
        if isinstance(result, Exception):
            logger.error(f"probe_servers: unhandled exception for '{server_id}': {result}")
            spec_hash = hashlib.sha256(specs[server_id].model_dump_json().encode()).hexdigest()
            results[server_id] = ProbeResult(
                server_id=server_id,
                success=False,
                spec_hash=spec_hash,
                error_kind=ProbeErrorKind.HANDSHAKE_FAILED,
                error_message=str(result),
            )
        else:
            results[server_id] = result  # type: ignore[assignment]

    return results
