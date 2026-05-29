"""Register Lambda — Provider registers an MCP server with its tools."""

import json
import os

import boto3
import httpx
from loguru import logger

from service.adapters.aws_secrets_manager import AWSSecretsManagerOAuthStore
from service.adapters.eventbridge_client import EventBridgeClient
from service.adapters.supabase_auth import SupabaseAuthClient
from service.adapters.supabase_client import SupabaseClient
from service.services.oauth_provider_bootstrap import (
    OAuthProviderBootstrapError,
    OAuthProviderBootstrapService,
)
from service.services.provider_service import ProviderService
from service.services.register_service import (
    EventPublishError,
    RegisterService,
    ValidationError,
)
from service.shared.event_loop import get_or_create_loop

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

_eventbridge_client = None
_eventbridge_client_override = None
eventbridge = None  # Set by tests or _get_eventbridge()


def _get_eventbridge():
    """Lazy-initialize EventBridge client (avoids errors when imported outside AWS)."""
    global _eventbridge_client, eventbridge  # noqa: PLW0603
    if _eventbridge_client is None:
        _eventbridge_client = boto3.client("events")
    eventbridge = _eventbridge_client
    return _eventbridge_client


def set_eventbridge_client_for_local_runtime(client) -> None:
    """Inject a shared EventBridge publisher for local runtime flows."""
    global _eventbridge_client_override  # noqa: PLW0603
    _eventbridge_client_override = client


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _request_path(event: dict) -> str:
    request_context = event.get("requestContext", {})
    http_context = request_context.get("http", {})
    raw = event.get("rawPath") or http_context.get("path") or event.get("path") or ""
    stage = request_context.get("stage", "")
    if stage and stage != "$default" and raw.startswith(f"/{stage}"):
        raw = raw[len(f"/{stage}") :]
    return raw


def _build_register_service() -> RegisterService:
    """Build a RegisterService with the current module-level Supabase/EventBridge config."""
    db = SupabaseClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    events = _build_eventbridge_client()
    oauth_secret_store = _build_oauth_secret_store()
    return RegisterService(db=db, events=events, oauth_secret_store=oauth_secret_store)


def _build_oauth_provider_bootstrap_service() -> OAuthProviderBootstrapService:
    repo = SupabaseClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    public_base_url = (
        os.environ.get("MLP_PUBLIC_API_BASE_URL")
        or os.environ.get("MLP_BACKEND_URL")
        or "http://127.0.0.1:8000"
    )
    return OAuthProviderBootstrapService(
        repo=repo,
        public_base_url=public_base_url,
        secret_store=_build_oauth_secret_store(),
    )


def _oauth_bootstrap_error_response(exc: OAuthProviderBootstrapError) -> dict:
    status_code = 424 if exc.retryable else 400
    if exc.code in {"secret_store_unavailable"}:
        status_code = 503
    elif exc.code in {
        "issuer_mismatch",
        "missing_client_secret",
        "unsupported_token_endpoint_auth_method",
    }:
        status_code = 422
    return _response(
        status_code,
        {
            "error": str(exc),
            "code": exc.code,
            "retryable": exc.retryable,
            "diagnostics": exc.diagnostics,
        },
    )


def _build_eventbridge_client():
    """Build the active EventBridge publisher, honoring local runtime overrides."""
    if _eventbridge_client_override is not None:
        return _eventbridge_client_override
    eb_raw = eventbridge or _get_eventbridge()
    return EventBridgeClient(eb_client=eb_raw)


def _build_oauth_secret_store():
    """Build the default OAuth secret store for registration-time persistence."""
    region_name = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    kms_key_id = os.environ.get("OAUTH_SECRET_KMS_KEY_ID")
    return AWSSecretsManagerOAuthStore(region_name=region_name, kms_key_id=kms_key_id)


def _extract_bearer_token(headers: dict | None) -> str | None:
    headers = headers or {}
    authorization = headers.get("authorization") or headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


def _is_platform_admin(user: dict) -> bool:
    """Return whether the authenticated user may mutate global OAuth providers."""
    app_metadata = user.get("app_metadata") if isinstance(user.get("app_metadata"), dict) else {}
    user_metadata = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
    role = app_metadata.get("role") or app_metadata.get("mlp_role") or user_metadata.get("mlp_role")
    roles = app_metadata.get("roles")
    return bool(
        app_metadata.get("mlp_admin") is True
        or app_metadata.get("platform_admin") is True
        or role in {"platform_admin", "mlp_admin"}
        or (isinstance(roles, list) and "platform_admin" in roles)
    )


async def _async_handler(event: dict, _context: object) -> dict:
    # Request parsing
    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Invalid JSON body"})

    # Auth (handler boundary)
    token = _extract_bearer_token(event.get("headers"))
    if token is None:
        return _response(401, {"error": "Missing bearer token"})

    auth_client = SupabaseAuthClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    try:
        user = await auth_client.get_user(token)
    except httpx.HTTPStatusError:
        return _response(401, {"error": "Invalid bearer token"})

    # Auth hardening: if owner_user_id is claimed in payload, it must match the token owner
    claimed_owner_user_id = body.get("owner_user_id")
    if claimed_owner_user_id is not None and claimed_owner_user_id != user["id"]:
        return _response(403, {"error": "owner_user_id does not match authenticated user"})

    # OAuth provider bootstrap branch: discovery/DCR/manual authoring is provider-owner scoped.
    path = _request_path(event)
    if path.startswith("/api/oauth/providers/bootstrap") or (
        path.startswith("/api/oauth/providers/") and path.endswith("/enable")
    ):
        if not _is_platform_admin(user):
            return _response(403, {"error": "OAuth provider bootstrap requires platform admin"})
        service = _build_oauth_provider_bootstrap_service()
        idempotency_key = (event.get("headers") or {}).get("Idempotency-Key") or (
            event.get("headers") or {}
        ).get("idempotency-key")
        try:
            if path == "/api/oauth/providers/bootstrap/discover":
                result = await service.discover(
                    owner_user_id=user["id"],
                    provider_key=str(body.get("provider_key") or ""),
                    display_name=body.get("display_name"),
                    issuer=body.get("issuer"),
                    authorization_server_metadata_url=body.get("authorization_server_metadata_url"),
                    openid_configuration_url=body.get("openid_configuration_url"),
                    protected_resource_metadata_url=body.get("protected_resource_metadata_url"),
                    selected_authorization_server=body.get("selected_authorization_server"),
                    client_id=body.get("client_id"),
                    client_secret=body.get("client_secret"),
                    token_endpoint_auth_method=body.get("token_endpoint_auth_method") or "none",
                    default_scopes=body.get("default_scopes") or [],
                    supports_refresh_token=body.get("supports_refresh_token"),
                    pkce_required=body.get("pkce_required"),
                    idempotency_key=idempotency_key or body.get("idempotency_key"),
                )
                return _response(200, result.to_dict())
            if path == "/api/oauth/providers/bootstrap/manual":
                result = await service.create_manual_draft(
                    owner_user_id=user["id"],
                    provider_key=str(body.get("provider_key") or ""),
                    display_name=str(body.get("display_name") or ""),
                    authorize_url=str(body.get("authorize_url") or ""),
                    token_url=str(body.get("token_url") or ""),
                    client_id=str(body.get("client_id") or ""),
                    token_endpoint_auth_method=body.get("token_endpoint_auth_method") or "none",
                    client_secret=body.get("client_secret"),
                    default_scopes=body.get("default_scopes") or [],
                    issuer=body.get("issuer"),
                    supports_refresh_token=bool(body.get("supports_refresh_token", False)),
                    pkce_required=bool(body.get("pkce_required", True)),
                    idempotency_key=idempotency_key or body.get("idempotency_key"),
                )
                return _response(201, result.to_dict())
            if path == "/api/oauth/providers/bootstrap/dcr":
                result = await service.run_dcr(
                    owner_user_id=user["id"],
                    provider_key=str(body.get("provider_key") or ""),
                    display_name=str(body.get("display_name") or ""),
                    registration_endpoint=str(body.get("registration_endpoint") or ""),
                    authorize_url=str(body.get("authorize_url") or ""),
                    token_url=str(body.get("token_url") or ""),
                    client_name=str(body.get("client_name") or body.get("display_name") or ""),
                    token_endpoint_auth_method=body.get("token_endpoint_auth_method") or "none",
                    scopes=body.get("scopes") or body.get("default_scopes") or [],
                    supports_refresh_token=bool(body.get("supports_refresh_token", True)),
                    issuer=body.get("issuer"),
                    idempotency_key=idempotency_key or body.get("idempotency_key"),
                )
                return _response(201, result.to_dict())
            if path.startswith("/api/oauth/providers/") and path.endswith("/enable"):
                provider_key = path.removeprefix("/api/oauth/providers/").removesuffix("/enable")
                result = await service.enable(
                    owner_user_id=user["id"],
                    draft_id=str(body.get("draft_id") or ""),
                    provider_key=provider_key,
                )
                return _response(200, result)
        except OAuthProviderBootstrapError as exc:
            return _oauth_bootstrap_error_response(exc)
        except httpx.HTTPError as exc:
            logger.warning(f"OAuth provider bootstrap dependency failed: {exc}")
            return _response(
                424, {"error": "OAuth provider bootstrap dependency failed", "retryable": True}
            )

    # Discovery branch
    if path == "/api/providers/servers/discovery":
        try:
            service = _build_register_service()
            result = await service.discover_server_metadata(body)
            return _response(200, result.model_dump())
        except ValidationError as e:
            return _response(400, {"error": str(e)})
        except RuntimeError as e:
            return _response(400, {"error": str(e)})
        except httpx.HTTPError as e:
            logger.warning(f"Provider metadata discovery failed: {e}")
            return _response(502, {"error": "Failed to discover provider metadata"})

    # Registration branch — pre-resolve provider, then delegate
    provider_repo = SupabaseClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    provider_service = ProviderService(repo=provider_repo)
    provider = await provider_service.get_or_create_provider(user["id"])

    # Ensure owner_user_id is populated from authenticated user if not in payload
    if "owner_user_id" not in body:
        body["owner_user_id"] = user["id"]

    service = _build_register_service()
    try:
        result = await service.register(body, provider_id=provider["id"])
    except ValidationError as e:
        return _response(400, {"error": str(e)})
    except EventPublishError as e:
        logger.error(f"EventBridge publish failed for server_id={body.get('server_id')}: {e}")
        await service.mark_tools_event_failed_for_server(body.get("server_id"))
        return _response(
            202,
            {
                "server_id": body.get("server_id"),
                "tools_count": len(body.get("tools", [])),
                "message": "Server registered. Event publish failed — tools queued for retry.",
                "index_status": "event_failed",
            },
        )

    return _response(201, result)


def lambda_handler(event: dict, context: object) -> dict:
    """AWS Lambda entry point."""
    loop = get_or_create_loop()
    return loop.run_until_complete(_async_handler(event, context))
