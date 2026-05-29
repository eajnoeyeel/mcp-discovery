"""Provider OAuth start Lambda."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from service.adapters.aws_secrets_manager import AWSSecretsManagerOAuthStore
from service.adapters.supabase_auth import SupabaseAuthClient
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


def _extract_bearer_token(headers: dict | None) -> str | None:
    headers = headers or {}
    authorization = headers.get("authorization") or headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


def _build_broker_service() -> OAuthBrokerService:
    repo = SupabaseClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    secret_store = AWSSecretsManagerOAuthStore(
        region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        kms_key_id=os.environ.get("OAUTH_SECRET_KMS_KEY_ID"),
    )
    return OAuthBrokerService(repo=repo, client_secret_resolver=secret_store)


async def _async_handler(event: dict, _context: object) -> dict[str, Any]:
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Invalid JSON body"})

    token = _extract_bearer_token(event.get("headers"))
    if token is None:
        return _response(401, {"error": "Missing bearer token"})

    auth_client = SupabaseAuthClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    try:
        user = await auth_client.get_user(token)
    except httpx.HTTPStatusError:
        return _response(401, {"error": "Invalid bearer token"})

    provider = str(body.get("provider") or "").strip()
    tool_id = str(body.get("tool_id") or "").strip()
    required_scopes = body.get("required_scopes") or []
    pending_execution_id = str(body.get("pending_execution_id") or "").strip() or None
    if not provider or not tool_id:
        return _response(400, {"error": "provider and tool_id are required"})
    if not isinstance(required_scopes, list):
        return _response(400, {"error": "required_scopes must be a list"})

    try:
        result = await _build_broker_service().start_authorization(
            user_id=user["id"],
            provider=provider,
            tool_id=tool_id,
            required_scopes=[str(scope) for scope in required_scopes],
            pending_execution_id=pending_execution_id,
        )
    except OAuthBrokerError as exc:
        return _response(400, {"error": str(exc)})

    return _response(200, result)


def lambda_handler(event: dict, context: object) -> dict:
    loop = get_or_create_loop()
    return loop.run_until_complete(_async_handler(event, context))
