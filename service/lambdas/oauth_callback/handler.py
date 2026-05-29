"""Provider OAuth callback Lambda."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from service.adapters.aws_secrets_manager import AWSSecretsManagerOAuthStore
from service.adapters.supabase_client import SupabaseClient
from service.services.oauth_broker import OAuthBrokerError, OAuthBrokerService
from service.shared.event_loop import get_or_create_loop

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _build_broker_service() -> OAuthBrokerService:
    repo = SupabaseClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    secret_store = AWSSecretsManagerOAuthStore(
        region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        kms_key_id=os.environ.get("OAUTH_SECRET_KMS_KEY_ID"),
    )
    return OAuthBrokerService(repo=repo, client_secret_resolver=secret_store)


async def _async_handler(event: dict, _context: object) -> dict[str, Any]:
    query = event.get("queryStringParameters") or {}
    path = event.get("pathParameters") or {}
    provider = str(path.get("provider") or query.get("provider") or "").strip()
    code = str(query.get("code") or "").strip()
    state = str(query.get("state") or "").strip()
    if not provider or not code or not state:
        return _response(400, {"error": "provider, code, and state are required"})

    try:
        result = await _build_broker_service().complete_authorization(
            provider=provider,
            code=code,
            state=state,
        )
    except OAuthBrokerError as exc:
        return _response(400, {"error": str(exc)})
    except httpx.HTTPStatusError as exc:
        return _response(502, {"error": f"Provider token exchange failed: {exc}"})

    return _response(200, result)


def lambda_handler(event: dict, context: object) -> dict:
    loop = get_or_create_loop()
    return loop.run_until_complete(_async_handler(event, context))
