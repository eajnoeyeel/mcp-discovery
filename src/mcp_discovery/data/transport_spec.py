"""Transport spec Pydantic models and YAML loader for MCP probe infrastructure (ADR-0018).

Three concrete transport types form a discriminated union keyed on `transport`:
  - StdioTransportSpec  (transport="stdio")  — npx / npm-based stdio MCP servers
  - HttpTransportSpec   (transport="http")   — HTTP/SSE MCP endpoints
  - ScriptTransportSpec (transport="script") — arbitrary shell scripts (fallback)

The YAML loader returns `dict[str, AnyTransportSpec]` keyed by server_id.
Version pinning is ENFORCED for stdio packages: `@latest` and bare unversioned
`@org/pkg` entries are rejected at load time.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal, Union

import yaml
from loguru import logger
from pydantic import Field, field_validator

from mcp_discovery.models.probe import TransportSpec

# ---------------------------------------------------------------------------
# Version-pin enforcement helpers
# ---------------------------------------------------------------------------

# Accepts: @1.2.3, @1.2.3-alpha.1, @2024.11.5, @0.1.0-rc.2 etc.
# Rejects: @latest, @next, @beta, @alpha, @rc, @canary (floating tags)
_LATEST_RE = re.compile(r"@(?:latest|next|beta|alpha|rc|canary)\b", re.IGNORECASE)

# Detects a bare unversioned npm package reference as the primary/first npm arg.
# Matches tokens like "@foo/bar" (no @version suffix) that are NOT followed by a version pin.
# The invariant: the *first* npm package reference in the command must be pinned.
# Sub-commands like "run @smithery-ai/github" are allowed unpinned (they're runner targets,
# not the version-pinned CLI itself).
_BARE_NPM_FIRST_PKG_RE = re.compile(r"npx\s+(?:-y\s+)?(@[a-zA-Z0-9_\-./]+)(?:\s|$)")
_HAS_VERSION_RE = re.compile(r"@\d[\w.\-]*$")


def _assert_pinned_package(command: str) -> str:
    """Validate that the primary npm package in a command string has an explicit version pin.

    Only the first npm package reference (the tool being invoked via npx) must be pinned.
    Sub-command targets like 'npx -y @smithery/cli@0.1.0 run @smithery-ai/github' are allowed
    because the CLI runner itself (@smithery/cli@0.1.0) is pinned.

    Raises ValueError on @latest/@next or a completely bare primary package.
    """
    # Reject any floating tag anywhere in the command
    if _LATEST_RE.search(command):
        raise ValueError(
            f"Unpinned npm package rejected: '{command}'. "
            "Use an explicit version (e.g. '@pkg@1.2.3'), never '@latest' or '@next'."
        )
    # Ensure the first npm package has a version pin
    m = _BARE_NPM_FIRST_PKG_RE.search(command)
    if m:
        first_pkg = m.group(1)
        if not _HAS_VERSION_RE.search(first_pkg):
            raise ValueError(
                f"No explicit version pin found in primary npm package '{first_pkg}' "
                f"(from command: '{command}'). "
                "Pin an explicit version to ensure reproducible probes "
                "(e.g. '@smithery/cli@0.1.0')."
            )
    return command


# ---------------------------------------------------------------------------
# Concrete transport specs
# ---------------------------------------------------------------------------


class StdioTransportSpec(TransportSpec):
    """npm/npx-based stdio MCP server.

    The `command` field is the full invocation string
    (e.g. "npx -y @smithery/cli@0.1.0 run @smithery-ai/github").
    Version pinning is mandatory — @latest is rejected at construction time.
    """

    transport: Literal["stdio"] = "stdio"
    command: str = Field(
        ...,
        description=(
            "Full npx/npm command. Must pin an explicit package version "
            "(e.g. '@pkg@1.2.3'). '@latest' is rejected."
        ),
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Map of env-var names to env-var names. Values are resolved from "
            "the runtime environment at probe time; never hardcode secrets here."
        ),
    )
    notes: str | None = Field(default=None, description="Human-readable rationale / auth notes")

    @field_validator("command")
    @classmethod
    def validate_version_pin(cls, v: str) -> str:
        _assert_pinned_package(v)
        return v


class HttpTransportSpec(TransportSpec):
    """HTTP/SSE MCP endpoint."""

    transport: Literal["http"] = "http"
    url: str = Field(..., description="Base URL of the HTTP MCP endpoint (no trailing slash)")
    headers: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Static headers to include. Use env-var reference names for secrets "
            "(resolved at probe time)."
        ),
    )
    timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Request timeout in seconds",
    )
    notes: str | None = Field(default=None, description="Human-readable rationale / auth notes")


class ScriptTransportSpec(TransportSpec):
    """Arbitrary shell-script / binary MCP server (fallback transport).

    ScriptProber routes these to TRANSPORT_UNSUPPORTED unless a custom
    runner is registered.  Exists to capture servers that don't fit
    stdio/http without dropping them from the spec file.
    """

    transport: Literal["script"] = "script"
    script_path: str = Field(
        ...,
        description="Relative or absolute path to the MCP server script/binary",
    )
    args: list[str] = Field(default_factory=list, description="CLI arguments")
    notes: str | None = Field(default=None, description="Human-readable rationale / auth notes")


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------

AnyTransportSpec = Annotated[
    Union[StdioTransportSpec, HttpTransportSpec, ScriptTransportSpec],
    Field(discriminator="transport"),
]

# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def load_transports_yaml(path: str | Path) -> dict[str, AnyTransportSpec]:
    """Load and validate transport specs from a YAML file.

    Returns a mapping of server_id → concrete transport spec.
    Raises ValueError immediately if any entry fails validation (fail-closed).

    YAML format expected:
    ```yaml
    servers:
      github:
        transport: stdio
        command: "npx -y @smithery/cli@0.1.0 run @smithery-ai/github"
        env:
          GITHUB_PERSONAL_ACCESS_TOKEN: GITHUB_PERSONAL_ACCESS_TOKEN
    ```
    """
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"transports.yaml not found at: {resolved}")

    raw = yaml.safe_load(resolved.read_text())
    if not raw or "servers" not in raw:
        logger.warning(f"transports.yaml at {resolved} has no 'servers' key — returning empty map")
        return {}

    servers_raw: dict[str, dict] = raw["servers"]
    specs: dict[str, AnyTransportSpec] = {}
    errors: list[str] = []

    for server_id, entry in servers_raw.items():
        if not isinstance(entry, dict):
            errors.append(f"[{server_id}] expected a mapping, got {type(entry).__name__}")
            continue
        # Inject server_id so models can reference it (TransportSpec base has server_id).
        entry_with_id = {"server_id": server_id, **entry}
        try:
            transport_kind = entry_with_id.get("transport", "")
            if transport_kind == "stdio":
                specs[server_id] = StdioTransportSpec.model_validate(entry_with_id)
            elif transport_kind == "http":
                specs[server_id] = HttpTransportSpec.model_validate(entry_with_id)
            elif transport_kind == "script":
                specs[server_id] = ScriptTransportSpec.model_validate(entry_with_id)
            else:
                errors.append(
                    f"[{server_id}] unknown transport kind '{transport_kind}'; "
                    "expected 'stdio', 'http', or 'script'"
                )
        except Exception as exc:
            errors.append(f"[{server_id}] validation failed: {exc}")

    if errors:
        detail = "\n  ".join(errors)
        raise ValueError(
            f"transport_spec.py: {len(errors)} entry(ies) failed validation "
            f"in {resolved}:\n  {detail}"
        )

    logger.info(f"Loaded {len(specs)} transport specs from {resolved}")
    return specs


# ---------------------------------------------------------------------------
# Migration helper
# ---------------------------------------------------------------------------


def migrate_from_pool_jsonl(pool_path: str | Path) -> dict[str, AnyTransportSpec]:
    """Best-effort extraction of transport specs from a pool JSONL file.

    Many pool rows have null url/transport fields.  This helper extracts
    what it can and returns a *partial* mapping for human review.  The
    caller should merge results into transports.yaml after inspection.

    Rows with no extractable transport info are skipped with a warning.
    """
    import json

    resolved = Path(pool_path)
    if not resolved.exists():
        raise FileNotFoundError(f"Pool JSONL not found at: {resolved}")

    specs: dict[str, AnyTransportSpec] = {}
    skipped: list[str] = []

    for line_no, line in enumerate(resolved.read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning(f"Pool JSONL line {line_no}: JSON parse error — {exc}")
            continue

        server_id: str = row.get("server_id") or row.get("id") or ""
        if not server_id:
            skipped.append(f"line {line_no}: no server_id")
            continue

        url: str | None = row.get("url") or row.get("endpoint_url")
        transport_hint: str = (row.get("transport") or "").lower()

        if url and (transport_hint == "http" or url.startswith("http")):
            specs[server_id] = HttpTransportSpec(
                server_id=server_id,
                transport="http",
                url=url,
            )
        else:
            # No reliable transport info — skip
            skipped.append(f"line {line_no} [{server_id}]: no url/transport info")

    if skipped:
        logger.warning(
            f"migrate_from_pool_jsonl: {len(skipped)} rows skipped "
            f"(no extractable transport). Add manually to transports.yaml.\n"
            + "\n".join(f"  {s}" for s in skipped[:20])
            + ("..." if len(skipped) > 20 else "")
        )

    logger.info(f"migrate_from_pool_jsonl: extracted {len(specs)} specs from {resolved}")
    return specs
