#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
IMAGE_IDENTIFIER="${IMAGE_IDENTIFIER:-123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/mlp-gateway:local}"
GATEWAY_BASE_URL="${GATEWAY_BASE_URL:-https://gateway.example.com}"

export UV_CACHE_DIR

predeploy_args=(
  --image-identifier "$IMAGE_IDENTIFIER"
  --gateway-base-url "$GATEWAY_BASE_URL"
)
if [[ -n "${SUPABASE_URL:-}" && -n "${SUPABASE_SERVICE_KEY:-}" ]]; then
  predeploy_args+=(--verify-runtime-schema)
elif [[ "${MLP_REQUIRE_LIVE_SCHEMA_VERIFY:-0}" == "1" ]]; then
  echo "MLP_REQUIRE_LIVE_SCHEMA_VERIFY=1 but SUPABASE_URL/SUPABASE_SERVICE_KEY are not set" >&2
  exit 1
else
  echo "Skipping live Supabase schema verification; set SUPABASE_URL and SUPABASE_SERVICE_KEY to enable it." >&2
fi

uv run python -m service.build.predeploy \
  "${predeploy_args[@]}"

uv run python scripts/ci/check_migration_prefixes.py
