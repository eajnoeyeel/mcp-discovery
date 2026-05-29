"""Bootstrap curated OAuth provider registry rows into Supabase."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

REQUIRED_FIELDS = {
    "provider_key",
    "display_name",
    "authorize_url",
    "token_url",
    "client_id",
    "redirect_uri",
    "default_scopes",
    "scope_aliases",
    "supports_refresh_token",
    "pkce_required",
    "enabled",
    "metadata",
}

ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def interpolate_env_placeholders(value: Any) -> Any:
    """Recursively replace ${VAR} placeholders with environment values."""
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            env_name = match.group(1)
            env_value = os.environ.get(env_name)
            if env_value is None:
                raise ValueError(f"Missing required environment variable: {env_name}")
            return env_value

        return ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [interpolate_env_placeholders(item) for item in value]
    if isinstance(value, dict):
        return {key: interpolate_env_placeholders(item) for key, item in value.items()}
    return value


def load_registry_entries(raw_json: str) -> list[dict[str, Any]]:
    """Load and validate provider registry entries from JSON."""
    payload = json.loads(raw_json)
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON array of provider registry entries")

    entries: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each provider registry entry must be an object")
        entry = interpolate_env_placeholders(item)
        missing = sorted(REQUIRED_FIELDS - set(entry))
        if missing:
            raise ValueError(
                f"Provider registry entry '{entry.get('provider_key', '<unknown>')}' "
                f"is missing required fields: {', '.join(missing)}"
            )
        entries.append(entry)
    return entries


async def upsert_registry_entries(
    *,
    client: httpx.AsyncClient,
    supabase_url: str,
    service_key: str,
    entries: list[dict[str, Any]],
) -> None:
    """Upsert provider registry rows into Supabase."""
    response = await client.post(
        f"{supabase_url.rstrip('/')}/rest/v1/oauth_provider_registry",
        params={"on_conflict": "provider_key"},
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        json=entries,
    )
    response.raise_for_status()


async def _async_main(args: argparse.Namespace) -> None:
    raw_json = Path(args.registry_file).read_text(encoding="utf-8")
    entries = load_registry_entries(raw_json)
    async with httpx.AsyncClient(timeout=20.0) as client:
        await upsert_registry_entries(
            client=client,
            supabase_url=args.supabase_url,
            service_key=args.service_key,
            entries=entries,
        )
    print(json.dumps({"upserted": [entry["provider_key"] for entry in entries]}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap OAuth provider registry rows.")
    parser.add_argument(
        "--registry-file",
        default="service/config/oauth_provider_registry.example.json",
        help="Path to a JSON file containing provider registry entries.",
    )
    parser.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL", ""))
    parser.add_argument("--service-key", default=os.environ.get("SUPABASE_SERVICE_KEY", ""))
    args = parser.parse_args()

    if not args.supabase_url or not args.service_key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")

    import asyncio

    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
