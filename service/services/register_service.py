"""Register service — validates and persists MCP server registrations."""

from typing import Any

from loguru import logger
from pydantic import ValidationError as PydanticValidationError

from service.services.contracts import (
    ParameterMetadataEntry,
    RegisterClientAuthRequirement,
    UpstreamAuthConfig,
)
from service.services.delegated_oauth import normalize_scopes
from service.services.metadata_discovery_service import MetadataDiscoveryService
from service.services.secret_refs import OAuthSecretStore
from service.services.upstream_auth import build_upstream_headers
from service.shared.param_metadata_telemetry import emit_drop_warning
from service.validation.description_rules import validate_description

_TRANSPORT_TYPES = {"stateless_http", "streamable_http", "sse", "stdio"}


class ValidationError(Exception):
    """Raised when registration payload fails validation."""


class EventPublishError(Exception):
    """Raised when EventBridge publish fails during registration."""


def validate_execution_auth_config(auth: UpstreamAuthConfig) -> None:
    """Validate execution auth metadata at provider registration time."""
    if auth.auth_type == "oauth_session":
        if not auth.oauth_token_endpoint:
            raise ValueError("oauth_token_endpoint is required for oauth_session upstream auth")
        if not auth.oauth_client_id:
            raise ValueError("oauth_client_id is required for oauth_session upstream auth")
        if not auth.oauth_refresh_token:
            raise ValueError("oauth_refresh_token is required for oauth_session upstream auth")
        return

    build_upstream_headers(auth)


def validate_transport_metadata(transport_type: str, requires_gateway: bool) -> None:
    """Validate transport metadata supported by the MLP runtime."""
    if transport_type not in _TRANSPORT_TYPES:
        allowed = ", ".join(sorted(_TRANSPORT_TYPES))
        raise ValueError(f"transport_type must be one of: {allowed}")
    if transport_type in {"streamable_http", "sse", "stdio"} and not requires_gateway:
        raise ValueError(f"requires_gateway must be true for {transport_type} transport")


class RegisterService:
    """Orchestrates registration: validate, persist, publish event."""

    def __init__(
        self,
        db,
        events,
        oauth_secret_store: OAuthSecretStore | None = None,
        metadata_discovery_service: MetadataDiscoveryService | None = None,
    ) -> None:
        self._db = db
        self._events = events
        self._oauth_secret_store = oauth_secret_store
        self._metadata_discovery_service = metadata_discovery_service or MetadataDiscoveryService()

    async def mark_tools_event_failed_for_server(self, server_id: str) -> None:
        """Mark all pending tools for `server_id` as `event_failed`.

        Called from the HTTP boundary after `register()` raises
        `EventPublishError`, so the index_replay Lambda can later retry
        persistence. Tolerates adapter failure (logs, does not re-raise) —
        the caller still needs to return 202 to the provider.
        """
        try:
            await self._db.mark_tools_event_failed(server_id)
        except Exception as exc:
            logger.error(
                f"mark_tools_event_failed_for_server failed (server_id={server_id}): {exc}"
            )

    async def discover_server_metadata(self, payload: dict):
        """Validate a discovery request and fetch normalized upstream tool metadata."""
        url = payload.get("url")
        if not url:
            raise ValidationError("Missing required field: url")

        try:
            execution_auth = UpstreamAuthConfig.model_validate(payload.get("execution_auth") or {})
            validate_execution_auth_config(execution_auth)
        except ValueError as exc:
            raise ValidationError(f"Execution auth: {exc}") from exc

        return await self._metadata_discovery_service.discover(url=url, auth=execution_auth)

    async def register(self, payload: dict, *, provider_id: str | None = None) -> dict:
        """Validate payload, upsert server + tools, publish EventBridge event."""
        server_id = payload.get("server_id")
        name = payload.get("name")
        description = payload.get("description", "")
        url = payload.get("url")
        tags = payload.get("tags", [])
        tools = payload.get("tools", [])
        try:
            execution_auth = UpstreamAuthConfig.model_validate(payload.get("execution_auth") or {})
            validate_execution_auth_config(execution_auth)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        transport_type = payload.get("transport_type", "stateless_http")
        requires_gateway = bool(payload.get("requires_gateway", False))
        try:
            validate_transport_metadata(transport_type, requires_gateway)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        if not server_id or not name or not url:
            raise ValidationError("Missing required fields: server_id, name, url")
        if not tools:
            raise ValidationError("At least one tool is required")

        if description:
            if err := validate_description(description):
                raise ValidationError(f"Server description: {err}")

        for tool in tools:
            if tool_desc := tool.get("description", ""):
                if err := validate_description(tool_desc):
                    raise ValidationError(f"Tool '{tool.get('tool_name', '?')}': {err}")

        client_auth_rows = await self._build_client_auth_rows(
            server_id=str(server_id),
            payload=payload,
            tools=tools,
        )

        server_row = {
            "server_id": server_id,
            "name": name,
            "description": description,
            "url": url,
            "tags": tags,
            "transport_type": transport_type,
            "requires_gateway": requires_gateway,
        }
        if provider_id is not None:
            server_row["provider_id"] = provider_id
        if owner_user_id := payload.get("owner_user_id"):
            server_row["owner_user_id"] = owner_user_id
            if provider_id is None:
                provider = await self._get_or_create_provider(owner_user_id)
                if provider is not None:
                    server_row["provider_id"] = provider["id"]
        await self._db.upsert_server(server_row)

        if execution_auth.auth_type == "oauth_session":
            auth_for_storage = execution_auth
            oauth_refs = None
            if self._oauth_secret_store is not None and execution_auth.oauth_refresh_token:
                try:
                    oauth_refs = await self._oauth_secret_store.provision_oauth_secret_refs(
                        server_id=server_id,
                        client_secret=execution_auth.oauth_client_secret,
                        refresh_token=execution_auth.oauth_refresh_token,
                    )
                    auth_for_storage = execution_auth.model_copy(
                        update={
                            "oauth_client_secret": oauth_refs.client_secret_ref,
                            "oauth_refresh_token": oauth_refs.refresh_token_ref,
                        }
                    )
                except Exception as exc:
                    logger.warning(
                        f"OAuth secret provisioning failed for server_id={server_id}: {exc} — "
                        "falling back to plaintext-only storage"
                    )
                    oauth_refs = None
            await self._db.upsert_oauth_session(server_id, auth_for_storage, secret_refs=oauth_refs)
        elif execution_auth.auth_type != "none":
            auth_refs = None
            if self._oauth_secret_store is not None and (
                execution_auth.bearer_token or execution_auth.api_key
            ):
                try:
                    auth_refs = await self._oauth_secret_store.provision_server_auth_secret_refs(
                        server_id=server_id,
                        bearer_token=execution_auth.bearer_token,
                        api_key=execution_auth.api_key,
                    )
                except Exception as exc:
                    logger.warning(
                        f"Server auth secret provisioning failed for server_id={server_id}: {exc}"
                        " — auth refs unavailable, secrets will not be persisted"
                    )
                    auth_refs = None
            await self._db.upsert_server_auth(server_id, execution_auth, secret_refs=auth_refs)

        await self._db.insert_tools(server_id, tools)
        await self._db.replace_auth_requirements(server_id, client_auth_rows)

        try:
            await self._events.publish_server_registered(server_id)
        except Exception as exc:
            logger.error(f"EventBridge publish failed: {exc}")
            raise EventPublishError(str(exc)) from exc

        return {
            "server_id": server_id,
            "tools_count": len(tools),
            "message": "Server registered. Indexing in progress.",
        }

    async def _build_client_auth_rows(
        self,
        *,
        server_id: str,
        payload: dict[str, Any],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        explicit_requirement_present = False

        server_requirement = self._normalize_client_auth_requirement(
            payload.get("client_auth"),
            context=f"server '{server_id}'",
        )
        if server_requirement is not None:
            rows.append(
                {
                    "server_id": server_id,
                    "tool_id": None,
                    **server_requirement,
                }
            )
            explicit_requirement_present = True

        for tool in tools:
            tool_name = str(tool.get("tool_name") or "").strip()
            tool_requirement = self._normalize_client_auth_requirement(
                tool.get("client_auth"),
                context=f"tool '{tool_name or '?'}'",
            )
            if tool_requirement is None:
                continue
            if not tool_name:
                raise ValidationError(
                    "Tool-level client auth requires a non-empty tool_name"
                )
            rows.append(
                {
                    "server_id": server_id,
                    "tool_id": f"{server_id}::{tool_name}",
                    **tool_requirement,
                }
            )
            explicit_requirement_present = True

        if not explicit_requirement_present:
            inferred_requirement = self._infer_legacy_client_auth_requirement(server_id)
            if inferred_requirement is not None:
                rows.append(
                    {
                        "server_id": server_id,
                        "tool_id": None,
                        **inferred_requirement,
                    }
                )

        await self._validate_client_auth_requirements(rows)
        return rows

    async def _validate_client_auth_requirements(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        if not rows:
            return

        fetch_provider_registry = getattr(self._db, "fetch_provider_registry", None)
        if not callable(fetch_provider_registry):
            raise ValidationError(
                "Delegated client auth validation unavailable: "
                "provider registry lookup is not supported"
            )

        validated_provider_keys: set[str] = set()
        for row in rows:
            provider_key = str(row.get("provider_key") or "").strip()
            if not provider_key or provider_key in validated_provider_keys:
                continue
            provider_row = await fetch_provider_registry(provider_key)
            if provider_row is None:
                raise ValidationError(
                    "Delegated client auth provider "
                    f"'{provider_key}' is not configured in oauth_provider_registry. "
                    "Bootstrap the provider registry before registering this server."
                )
            if provider_row.get("enabled") is False:
                raise ValidationError(
                    f"Delegated client auth provider '{provider_key}' is disabled"
                )
            validated_provider_keys.add(provider_key)

    @staticmethod
    def _infer_legacy_client_auth_requirement(server_id: str) -> dict[str, Any] | None:
        provider_key = server_id.removesuffix("-oauth").strip()
        if not provider_key or provider_key == server_id:
            return None
        return {
            "provider_key": provider_key,
            "auth_kind": "oauth",
            "required_scopes": [],
            "scope_mode": "default",
        }

    async def _get_or_create_provider(self, owner_user_id: str) -> dict[str, Any] | None:
        fetch_provider = getattr(self._db, "fetch_provider_by_user_id", None)
        create_provider = getattr(self._db, "create_provider", None)
        if not callable(fetch_provider) or not callable(create_provider):
            return None

        provider = await fetch_provider(owner_user_id)
        if provider is not None:
            return provider
        return await create_provider(owner_user_id)

    @staticmethod
    def _normalize_client_auth_requirement(
        value: Any,
        *,
        context: str,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        if not isinstance(value, dict):
            raise ValidationError(
                f"Client auth metadata for {context} must be an object"
            )
        if not value:
            return None

        try:
            requirement = RegisterClientAuthRequirement.model_validate(value)
        except PydanticValidationError as exc:
            raise ValidationError(
                f"Client auth metadata for {context} is invalid"
            ) from exc

        provider_key = str(requirement.provider_key or "").strip()
        if not provider_key:
            raise ValidationError(
                f"Client auth metadata for {context} requires a provider_key"
            )

        return {
            "provider_key": provider_key,
            "auth_kind": requirement.auth_kind,
            "required_scopes": normalize_scopes(
                [str(scope) for scope in requirement.required_scopes]
            ),
            "scope_mode": requirement.scope_mode,
        }

    @staticmethod
    def _normalize_parameter_metadata(
        value: Any,
        *,
        context: str | None = None,
        server_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        reason_counts: dict[str, int] = {}
        total = len(value)
        for entry in value:
            if hasattr(entry, "model_dump"):
                entry = entry.model_dump()
            if not isinstance(entry, dict):
                reason_counts["not_a_dict"] = reason_counts.get("not_a_dict", 0) + 1
                continue
            candidate = dict(entry)
            candidate["path"] = str(candidate.get("path") or "").strip()
            candidate["name"] = str(candidate.get("name") or "").strip()
            if not candidate["path"] or not candidate["name"]:
                reason_counts["missing_required_fields"] = (
                    reason_counts.get("missing_required_fields", 0) + 1
                )
                continue
            try:
                normalized.append(ParameterMetadataEntry.model_validate(candidate).model_dump())
            except PydanticValidationError:
                reason_counts["validation_error"] = reason_counts.get("validation_error", 0) + 1
                continue
        emit_drop_warning(
            "RegisterService._normalize_parameter_metadata",
            total - len(normalized),
            total,
            reason_counts,
            context=context,
            server_id=server_id,
        )
        return normalized

    @staticmethod
    def _normalize_published_parameter_metadata(
        value: Any,
        *,
        context: str | None = None,
        server_id: str | None = None,
    ) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, str]] = []
        reason_counts: dict[str, int] = {}
        total = len(value)
        for entry in value:
            if hasattr(entry, "model_dump"):
                entry = entry.model_dump()
            if not isinstance(entry, dict):
                reason_counts["not_a_dict"] = reason_counts.get("not_a_dict", 0) + 1
                continue
            path = str(entry.get("path") or "").strip()
            description = str(entry.get("description") or "").strip()
            if not path or not description:
                reason_counts["missing_required_fields"] = (
                    reason_counts.get("missing_required_fields", 0) + 1
                )
                continue
            normalized.append({"path": path, "description": description})
        emit_drop_warning(
            "RegisterService._normalize_published_parameter_metadata",
            total - len(normalized),
            total,
            reason_counts,
            context=context,
            server_id=server_id,
        )
        return normalized
