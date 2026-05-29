"""Check npm package pin freshness for stdio transport specs (ADR-0018).

Reads ``transports.yaml``, extracts the pinned npm package versions from each
``stdio`` transport command, then queries ``npm view <pkg> version`` for the
latest published version. Diffs pinned vs. latest and emits a structured
advisory report.

**Advisory only**: this script always exits 0 in this PR.  A subsequent PR
(gated on ADR-0019) will add ``--fail-on-stale`` and wire it into the nightly
workflow.

Usage:
    uv run python scripts/check_transport_pin_freshness.py

    # Custom transports.yaml:
    uv run python scripts/check_transport_pin_freshness.py \\
      --transports src/mcp_discovery/data/transports.yaml

    # Output JSON report:
    uv run python scripts/check_transport_pin_freshness.py \\
      --json-out data/results/pin_freshness.json

Exit codes:
    0  -- always (advisory only in this PR)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger

from mcp_discovery.data.transport_spec import load_transports_yaml
from mcp_discovery.models.probe import TransportSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_TRANSPORTS_YAML = _REPO_ROOT / "src" / "mcp_discovery" / "data" / "transports.yaml"

# Regex to extract @scope/pkg@version or pkg@version from a command string.
# Matches tokens that look like pinned npm packages:
# Matches tokens like: "npx -y @modelcontextprotocol/server-fetch@0.6.2"
#   "npx -y @smithery/cli@0.1.0 run @smithery-ai/github" -> ("@smithery/cli", "0.1.0")
_PKG_VERSION_RE = re.compile(r"(@?[\w\-][\w\-./]*)@([\d][^\s]*)")

_NPM_VIEW_TIMEOUT_SECS = 15


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PinEntry:
    server_id: str
    package: str
    pinned_version: str
    latest_version: str | None
    is_fresh: bool | None  # None = check failed
    check_error: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_pkg_version(command: str) -> tuple[str, str] | None:
    """Extract (package_name, pinned_version) from an npx command string.

    Returns the first match that looks like a real package version (not a flag).
    Returns None if no pinned package is detected.
    """
    for match in _PKG_VERSION_RE.finditer(command):
        pkg, ver = match.group(1), match.group(2)
        # Only consider tokens that look like real npm packages
        if "/" in pkg or pkg.startswith("@") or len(pkg) > 2:
            return pkg, ver
    return None


async def _run_npm_view(package: str) -> str | None:
    """Run ``npm view <package> version`` via asyncio subprocess. Returns version or None."""
    # Uses asyncio.create_subprocess_exec (not shell=True) -- safe from injection.
    npm_args = ["npm", "view", package, "version"]
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                npm_args[0],
                *npm_args[1:],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=_NPM_VIEW_TIMEOUT_SECS,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_NPM_VIEW_TIMEOUT_SECS)
        if proc.returncode == 0:
            return stdout.decode().strip()
        logger.warning(f"npm view {package}: exit {proc.returncode} -- {stderr.decode().strip()}")
        return None
    except asyncio.TimeoutError:
        logger.warning(f"npm view {package}: timed out after {_NPM_VIEW_TIMEOUT_SECS}s")
        return None
    except Exception as exc:
        logger.warning(f"npm view {package}: {exc}")
        return None


async def _check_entry(server_id: str, command: str) -> PinEntry | None:
    """Check pin freshness for a single stdio command. Returns None if not applicable."""
    result = _extract_pkg_version(command)
    if result is None:
        logger.info(f"[{server_id}] No pinned package detected in command -- skipping")
        return None

    package, pinned_version = result
    logger.info(f"[{server_id}] Checking {package}@{pinned_version}...")

    latest = await _run_npm_view(package)
    if latest is None:
        return PinEntry(
            server_id=server_id,
            package=package,
            pinned_version=pinned_version,
            latest_version=None,
            is_fresh=None,
            check_error="npm view failed or timed out",
        )

    is_fresh = latest == pinned_version
    return PinEntry(
        server_id=server_id,
        package=package,
        pinned_version=pinned_version,
        latest_version=latest,
        is_fresh=is_fresh,
        check_error=None,
    )


def _format_report(entries: list[PinEntry]) -> str:
    """Format a human-readable pin freshness report."""
    fresh = [e for e in entries if e.is_fresh is True]
    stale = [e for e in entries if e.is_fresh is False]
    errors = [e for e in entries if e.is_fresh is None]

    lines = [
        "",
        "TRANSPORT PIN FRESHNESS REPORT (advisory)",
        "=" * 50,
        f"  Checked:   {len(entries)}",
        f"  Fresh:     {len(fresh)}",
        f"  Stale:     {len(stale)}",
        f"  Errors:    {len(errors)}",
        "",
    ]

    if stale:
        lines.append("Stale pins (update recommended):")
        for e in stale:
            lines.append(
                f"  [{e.server_id}] {e.package}  "
                f"pinned={e.pinned_version}  latest={e.latest_version}"
            )
        lines.append("")

    if errors:
        lines.append("Check errors:")
        for e in errors:
            lines.append(f"  [{e.server_id}] {e.package}: {e.check_error}")
        lines.append("")

    if not stale and not errors:
        lines.append("All pins are up-to-date.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check npm transport pin freshness (ADR-0018, advisory only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--transports",
        type=Path,
        default=_DEFAULT_TRANSPORTS_YAML,
        help="transports.yaml path (default: src/mcp_discovery/data/transports.yaml)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write structured JSON report to this path",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max parallel npm view calls (default: 4)",
    )

    args = parser.parse_args()

    specs = load_transports_yaml(args.transports)
    stdio_entries = {
        sid: spec
        for sid, spec in specs.items()
        if getattr(spec, "transport", None) == "stdio"
    }

    if not stdio_entries:
        logger.info("No stdio transport entries found -- nothing to check")
        return 0

    logger.info(f"Checking {len(stdio_entries)} stdio transport(s)...")

    sem = asyncio.Semaphore(args.concurrency)

    async def _guarded(server_id: str, spec: TransportSpec) -> PinEntry | None:
        async with sem:
            return await _check_entry(server_id, getattr(spec, "command", ""))

    tasks = [_guarded(sid, spec) for sid, spec in stdio_entries.items()]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    entries: list[PinEntry] = []
    for sid, result in zip(stdio_entries.keys(), raw_results):
        if isinstance(result, Exception):
            logger.error(f"[{sid}] Unhandled error: {result}")
            entries.append(
                PinEntry(
                    server_id=sid,
                    package="(unknown)",
                    pinned_version="(unknown)",
                    latest_version=None,
                    is_fresh=None,
                    check_error=str(result),
                )
            )
        elif result is not None:
            entries.append(result)

    report_text = _format_report(entries)
    logger.info(report_text)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        report_data = {
            "entries": [asdict(e) for e in entries],
            "summary": {
                "checked": len(entries),
                "fresh": sum(1 for e in entries if e.is_fresh is True),
                "stale": sum(1 for e in entries if e.is_fresh is False),
                "errors": sum(1 for e in entries if e.is_fresh is None),
            },
        }
        args.json_out.write_text(
            json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(f"JSON report written to {args.json_out}")

    # Advisory only -- always exit 0
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
