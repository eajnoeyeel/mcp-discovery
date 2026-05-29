"""OAuth provider bootstrap services for delegated client-auth providers.

Discovery/DCR/manual input creates a draft; only explicit promotion updates the
active ``oauth_provider_registry`` execution metadata. This keeps untrusted
machine-readable metadata out of runtime paths until it is validated.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import secrets
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urljoin, urlparse

import httpx

TokenEndpointAuthMethod = Literal["none", "client_secret_post", "client_secret_basic"]
BootstrapMode = Literal["manual", "discovery", "dcr"]
BootstrapStatus = Literal["draft", "validated", "enabled", "failed", "disabled", "promoted"]

SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS: set[str] = {
    "none",
    "client_secret_post",
    "client_secret_basic",
}
SENSITIVE_KEYS = {
    "access_token",
    "authorization",
    "client_secret",
    "code",
    "code_verifier",
    "refresh_token",
}
NON_SENSITIVE_KEYS = {
    "supports_refresh_token",
}


class OAuthProviderBootstrapError(ValueError):
    """Raised when provider OAuth bootstrap input cannot be accepted safely."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "oauth_provider_bootstrap_error",
        retryable: bool = False,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.diagnostics = redact_sensitive(diagnostics or {})


class OAuthProviderBootstrapRepo(Protocol):
    async def fetch_bootstrap_draft_by_idempotency_key(
        self, *, owner_user_id: str, idempotency_key: str
    ) -> dict | None: ...

    async def fetch_oauth_provider_bootstrap_draft(
        self, *, draft_id: str, owner_user_id: str
    ) -> dict | None: ...

    async def create_oauth_provider_bootstrap_draft(self, payload: dict) -> dict | list: ...

    async def promote_oauth_provider_bootstrap_draft(
        self, *, draft_id: str, owner_user_id: str
    ) -> dict | list: ...


class ProviderClientSecretStore(Protocol):
    async def provision_provider_client_secret_ref(
        self,
        *,
        provider_key: str,
        client_secret: str,
    ) -> str: ...


@dataclass(frozen=True)
class BootstrapDraftResult:
    """Normalized draft response returned by bootstrap services."""

    draft_id: str | None
    provider_key: str
    status: BootstrapStatus
    mode: BootstrapMode
    metadata: dict[str, Any]
    diagnostics: dict[str, Any]
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "provider_key": self.provider_key,
            "status": self.status,
            "mode": self.mode,
            "metadata": redact_sensitive(self.metadata),
            "diagnostics": redact_sensitive(self.diagnostics),
            "idempotency_key": self.idempotency_key,
        }


def _is_sensitive_key(key: object) -> bool:
    key_text = str(key).lower()
    if key_text in NON_SENSITIVE_KEYS:
        return False
    if key_text.endswith("_ref") or key_text.endswith("_refs"):
        return False
    return key_text in SENSITIVE_KEYS or key_text.endswith("_token")


def redact_sensitive(value: Any) -> Any:
    """Recursively redact values whose keys indicate OAuth secret material."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_provider_key(provider_key: str) -> str:
    normalized = provider_key.strip().lower()
    if not normalized:
        raise OAuthProviderBootstrapError("provider_key is required", code="missing_provider_key")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    if any(char not in allowed for char in normalized):
        raise OAuthProviderBootstrapError(
            "provider_key may contain only lowercase letters, numbers, '-' and '_'",
            code="invalid_provider_key",
        )
    return normalized


def _validate_https_url(
    value: str,
    *,
    field: str,
    allow_local: bool = False,
    enforce_public_network: bool = False,
) -> str:
    candidate = value.strip()
    if not candidate:
        raise OAuthProviderBootstrapError(f"{field} is required", code=f"missing_{field}")
    parsed = urlparse(candidate)
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "https":
        if enforce_public_network:
            _validate_public_network_location(candidate, field=field)
        return candidate
    if allow_local and parsed.scheme == "http" and (parsed.hostname or "") in local_hosts:
        return candidate
    raise OAuthProviderBootstrapError(
        f"{field} must be an HTTPS URL",
        code="insecure_oauth_metadata_url",
        diagnostics={"field": field, "url": candidate},
    )


def _validate_public_network_location(url: str, *, field: str) -> None:
    """Reject URLs that resolve to private/link-local/loopback network space."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise OAuthProviderBootstrapError(
            f"{field} must include a hostname",
            code="invalid_oauth_metadata_url",
            diagnostics={"field": field, "url": url},
        )
    try:
        addr_infos = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise OAuthProviderBootstrapError(
            f"{field} hostname could not be resolved",
            code="oauth_metadata_host_unresolvable",
            retryable=True,
            diagnostics={"field": field, "host": hostname},
        ) from exc
    for addr_info in addr_infos:
        ip = ipaddress.ip_address(addr_info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise OAuthProviderBootstrapError(
                f"{field} resolves to a blocked network address",
                code="oauth_metadata_host_blocked",
                diagnostics={"field": field, "host": hostname, "address": str(ip)},
            )


def normalize_scopes(value: Any) -> list[str]:
    """Normalize OAuth scopes from list or space/comma-delimited string."""
    raw: list[Any]
    if value is None:
        raw = []
    elif isinstance(value, str):
        raw = value.replace(",", " ").split()
    elif isinstance(value, list):
        raw = value
    else:
        raise OAuthProviderBootstrapError("scopes must be a list or string", code="invalid_scopes")

    scopes: list[str] = []
    for scope in raw:
        text = str(scope).strip()
        if text and text not in scopes:
            scopes.append(text)
    return scopes


def build_redirect_uri(*, public_base_url: str, provider_key: str) -> str:
    base = public_base_url.rstrip("/")
    provider = _require_provider_key(provider_key)
    return f"{base}/api/oauth/providers/{provider}/callback"


def normalize_authorization_metadata(
    metadata: dict[str, Any],
    *,
    source_url: str,
    expected_issuer: str | None = None,
    allow_local_http: bool = False,
    enforce_public_network: bool = False,
) -> dict[str, Any]:
    """Normalize RFC8414/OIDC metadata into registry-compatible fields."""
    if not isinstance(metadata, dict):
        raise OAuthProviderBootstrapError("metadata must be an object", code="invalid_metadata")

    issuer = str(metadata.get("issuer") or expected_issuer or "").strip()
    if expected_issuer and issuer and issuer.rstrip("/") != expected_issuer.rstrip("/"):
        raise OAuthProviderBootstrapError(
            "authorization server issuer mismatch",
            code="issuer_mismatch",
            diagnostics={"expected_issuer": expected_issuer, "issuer": issuer},
        )

    authorize_url = _validate_https_url(
        str(metadata.get("authorization_endpoint") or ""),
        field="authorize_url",
        allow_local=allow_local_http,
        enforce_public_network=enforce_public_network,
    )
    token_url = _validate_https_url(
        str(metadata.get("token_endpoint") or ""),
        field="token_url",
        allow_local=allow_local_http,
        enforce_public_network=enforce_public_network,
    )
    registration_endpoint = metadata.get("registration_endpoint")
    if registration_endpoint:
        registration_endpoint = _validate_https_url(
            str(registration_endpoint),
            field="registration_endpoint",
            allow_local=allow_local_http,
            enforce_public_network=enforce_public_network,
        )

    token_methods = metadata.get("token_endpoint_auth_methods_supported") or ["none"]
    token_methods = [str(method) for method in token_methods if str(method)]
    safe_methods = [
        method for method in token_methods if method in SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS
    ]

    code_challenge_methods = [
        str(method)
        for method in (metadata.get("code_challenge_methods_supported") or [])
        if str(method)
    ]

    return {
        "issuer": issuer or None,
        "metadata_url": source_url,
        "authorize_url": authorize_url,
        "token_url": token_url,
        "registration_endpoint": registration_endpoint,
        "scopes_supported": normalize_scopes(metadata.get("scopes_supported") or []),
        "grant_types_supported": [
            str(item) for item in (metadata.get("grant_types_supported") or []) if str(item)
        ],
        "response_types_supported": [
            str(item) for item in (metadata.get("response_types_supported") or []) if str(item)
        ],
        "token_endpoint_auth_methods_supported": token_methods,
        "supported_token_endpoint_auth_methods": safe_methods,
        "code_challenge_methods_supported": code_challenge_methods,
        "pkce_required": "S256" in code_challenge_methods or "none" in safe_methods,
        "supports_dcr": bool(registration_endpoint),
        "source": {"type": "authorization_server_metadata", "url": source_url},
    }


def normalize_protected_resource_metadata(
    metadata: dict[str, Any],
    *,
    source_url: str,
    selected_authorization_server: str | None = None,
    allow_local_http: bool = False,
    enforce_public_network: bool = False,
) -> dict[str, Any]:
    """Normalize RFC9728 Protected Resource Metadata."""
    authorization_servers = metadata.get("authorization_servers") or []
    if not isinstance(authorization_servers, list):
        raise OAuthProviderBootstrapError(
            "authorization_servers must be a list", code="invalid_protected_resource_metadata"
        )
    authorization_servers = [str(url).strip() for url in authorization_servers if str(url).strip()]
    if len(authorization_servers) > 1 and not selected_authorization_server:
        raise OAuthProviderBootstrapError(
            "multiple authorization servers require explicit selection",
            code="authorization_server_selection_required",
            diagnostics={"authorization_servers": authorization_servers},
        )
    selected = selected_authorization_server or (
        authorization_servers[0] if authorization_servers else ""
    )
    if selected:
        selected = _validate_https_url(
            selected,
            field="authorization_server",
            allow_local=allow_local_http,
            enforce_public_network=enforce_public_network,
        )
    return {
        "protected_resource_metadata_url": source_url,
        "authorization_server": selected or None,
        "authorization_servers": authorization_servers,
        "scopes_supported": normalize_scopes(metadata.get("scopes_supported") or []),
        "source": {"type": "protected_resource_metadata", "url": source_url},
    }


def build_authorization_metadata_urls(issuer: str) -> list[str]:
    issuer = issuer.rstrip("/")
    parsed = urlparse(issuer)
    if not parsed.scheme or not parsed.netloc:
        raise OAuthProviderBootstrapError("issuer must be a URL", code="invalid_issuer")
    suffix = parsed.path.rstrip("/") if parsed.path not in ("", "/") else ""
    return [
        urljoin(f"{parsed.scheme}://{parsed.netloc}", "/.well-known/oauth-authorization-server")
        + suffix,
        f"{issuer}/.well-known/openid-configuration",
    ]


def build_dcr_registration_payload(
    *,
    client_name: str,
    redirect_uri: str,
    scopes: list[str],
    token_endpoint_auth_method: TokenEndpointAuthMethod,
    supports_refresh_token: bool,
) -> dict[str, Any]:
    grant_types = ["authorization_code"]
    if supports_refresh_token:
        grant_types.append("refresh_token")
    return {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "response_types": ["code"],
        "grant_types": grant_types,
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "scope": " ".join(normalize_scopes(scopes)),
    }


class OAuthProviderBootstrapService:
    """Create provider bootstrap drafts through discovery, DCR, or manual input."""

    def __init__(
        self,
        *,
        repo: OAuthProviderBootstrapRepo,
        public_base_url: str,
        secret_store: ProviderClientSecretStore | None = None,
        http_client: httpx.AsyncClient | None = None,
        allow_local_http: bool = False,
    ) -> None:
        self._repo = repo
        self._public_base_url = public_base_url.rstrip("/")
        self._secret_store = secret_store
        self._http_client = http_client
        self._allow_local_http = allow_local_http

    async def discover(
        self,
        *,
        owner_user_id: str,
        provider_key: str,
        display_name: str | None = None,
        issuer: str | None = None,
        authorization_server_metadata_url: str | None = None,
        openid_configuration_url: str | None = None,
        protected_resource_metadata_url: str | None = None,
        selected_authorization_server: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_endpoint_auth_method: TokenEndpointAuthMethod = "none",
        default_scopes: list[str] | None = None,
        supports_refresh_token: bool | None = None,
        pkce_required: bool | None = None,
        idempotency_key: str | None = None,
    ) -> BootstrapDraftResult:
        provider = _require_provider_key(provider_key)
        existing = await self._get_idempotent(owner_user_id, idempotency_key)
        if existing is not None:
            return self._draft_result_from_row(existing)

        diagnostics: dict[str, Any] = {"fetched_at": _now_iso()}
        enforce_public_network = self._http_client is None
        metadata: dict[str, Any] = {
            "provider_key": provider,
            "display_name": display_name or provider,
            "redirect_uri": build_redirect_uri(
                public_base_url=self._public_base_url, provider_key=provider
            ),
            "bootstrap_mode": "discovery",
            "bootstrap_status": "draft",
            "provenance": {},
        }

        if protected_resource_metadata_url:
            prm_url = _validate_https_url(
                protected_resource_metadata_url,
                field="protected_resource_metadata_url",
                allow_local=self._allow_local_http,
                enforce_public_network=enforce_public_network,
            )
            prm = normalize_protected_resource_metadata(
                await self._fetch_json(prm_url),
                source_url=prm_url,
                selected_authorization_server=selected_authorization_server,
                allow_local_http=self._allow_local_http,
                enforce_public_network=enforce_public_network,
            )
            metadata.update({k: v for k, v in prm.items() if k != "source"})
            diagnostics["protected_resource_metadata"] = prm["source"]
            issuer = issuer or prm.get("authorization_server")

        candidate_urls: list[str] = []
        if authorization_server_metadata_url:
            candidate_urls.append(
                _validate_https_url(
                    authorization_server_metadata_url,
                    field="authorization_server_metadata_url",
                    allow_local=self._allow_local_http,
                    enforce_public_network=enforce_public_network,
                )
            )
        if openid_configuration_url:
            candidate_urls.append(
                _validate_https_url(
                    openid_configuration_url,
                    field="openid_configuration_url",
                    allow_local=self._allow_local_http,
                    enforce_public_network=enforce_public_network,
                )
            )
        if issuer:
            candidate_urls.extend(build_authorization_metadata_urls(issuer))

        if not candidate_urls:
            raise OAuthProviderBootstrapError(
                "issuer or metadata URL is required for discovery",
                code="missing_discovery_hint",
            )

        last_error: Exception | None = None
        for metadata_url in candidate_urls:
            try:
                auth_metadata = normalize_authorization_metadata(
                    await self._fetch_json(metadata_url),
                    source_url=metadata_url,
                    expected_issuer=issuer,
                    allow_local_http=self._allow_local_http,
                    enforce_public_network=enforce_public_network,
                )
                metadata.update(auth_metadata)
                diagnostics["authorization_server_metadata"] = auth_metadata["source"]
                break
            except Exception as exc:
                last_error = exc
                diagnostics.setdefault("failed_metadata_urls", []).append(
                    {"url": metadata_url, "error": str(exc)}
                )
        else:
            if isinstance(last_error, OAuthProviderBootstrapError):
                raise last_error
            raise OAuthProviderBootstrapError(
                "failed to discover authorization server metadata",
                code="discovery_failed",
                retryable=True,
                diagnostics=diagnostics,
            ) from last_error

        status: BootstrapStatus = "draft"
        if client_id:
            if token_endpoint_auth_method not in SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS:
                raise OAuthProviderBootstrapError(
                    "unsupported token_endpoint_auth_method",
                    code="unsupported_token_endpoint_auth_method",
                )
            client_id = client_id.strip()
            if not client_id:
                raise OAuthProviderBootstrapError("client_id is required", code="missing_client_id")
            client_secret_ref: str | None = None
            if token_endpoint_auth_method != "none":
                if not client_secret:
                    raise OAuthProviderBootstrapError(
                        "client_secret is required for this token endpoint auth method",
                        code="missing_client_secret",
                    )
                if self._secret_store is None:
                    raise OAuthProviderBootstrapError(
                        "secret store is unavailable",
                        code="secret_store_unavailable",
                        retryable=True,
                    )
                client_secret_ref = await self._secret_store.provision_provider_client_secret_ref(
                    provider_key=provider,
                    client_secret=client_secret,
                )
            metadata.update(
                {
                    "client_id": client_id,
                    "client_secret_ref": client_secret_ref,
                    "default_scopes": normalize_scopes(default_scopes or []),
                    "scope_aliases": {},
                    "supports_refresh_token": bool(
                        supports_refresh_token
                        if supports_refresh_token is not None
                        else "refresh_token" in metadata.get("grant_types_supported", [])
                    ),
                    "pkce_required": bool(
                        pkce_required
                        if pkce_required is not None
                        else metadata.get("pkce_required", token_endpoint_auth_method == "none")
                    ),
                    "enabled": False,
                    "token_endpoint_auth_method": token_endpoint_auth_method,
                    "bootstrap_status": "validated",
                    "metadata": {"bootstrap_source": "discovery"},
                    "provenance": {
                        "client_id": "discovery_input",
                        "client_secret_ref": "secret_store" if client_secret_ref else None,
                    },
                }
            )
            status = "validated"
            diagnostics["validated_at"] = _now_iso()
        else:
            metadata["bootstrap_status"] = "draft"
            diagnostics["next_step"] = "run_dcr_or_create_manual_draft_with_client_credentials"

        row = await self._persist_draft(
            owner_user_id=owner_user_id,
            provider_key=provider,
            mode="discovery",
            status=status,
            metadata=metadata,
            diagnostics=diagnostics,
            idempotency_key=idempotency_key,
        )
        return self._draft_result_from_row(row)

    async def create_manual_draft(
        self,
        *,
        owner_user_id: str,
        provider_key: str,
        display_name: str,
        authorize_url: str,
        token_url: str,
        client_id: str,
        token_endpoint_auth_method: TokenEndpointAuthMethod = "none",
        client_secret: str | None = None,
        default_scopes: list[str] | None = None,
        issuer: str | None = None,
        supports_refresh_token: bool = False,
        pkce_required: bool = True,
        idempotency_key: str | None = None,
    ) -> BootstrapDraftResult:
        provider = _require_provider_key(provider_key)
        existing = await self._get_idempotent(owner_user_id, idempotency_key)
        if existing is not None:
            return self._draft_result_from_row(existing)
        if token_endpoint_auth_method not in SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS:
            raise OAuthProviderBootstrapError(
                "unsupported token_endpoint_auth_method",
                code="unsupported_token_endpoint_auth_method",
            )
        client_id = client_id.strip()
        if not client_id:
            raise OAuthProviderBootstrapError("client_id is required", code="missing_client_id")
        client_secret_ref: str | None = None
        if token_endpoint_auth_method != "none":
            if not client_secret:
                raise OAuthProviderBootstrapError(
                    "client_secret is required for this token endpoint auth method",
                    code="missing_client_secret",
                )
            if self._secret_store is None:
                raise OAuthProviderBootstrapError(
                    "secret store is unavailable",
                    code="secret_store_unavailable",
                    retryable=True,
                )
            client_secret_ref = await self._secret_store.provision_provider_client_secret_ref(
                provider_key=provider,
                client_secret=client_secret,
            )

        metadata = {
            "provider_key": provider,
            "display_name": display_name.strip() or provider,
            "issuer": issuer.strip() if issuer else None,
            "authorize_url": _validate_https_url(
                authorize_url,
                field="authorize_url",
                allow_local=self._allow_local_http,
                enforce_public_network=self._http_client is None,
            ),
            "token_url": _validate_https_url(
                token_url,
                field="token_url",
                allow_local=self._allow_local_http,
                enforce_public_network=self._http_client is None,
            ),
            "client_id": client_id,
            "client_secret_ref": client_secret_ref,
            "redirect_uri": build_redirect_uri(
                public_base_url=self._public_base_url, provider_key=provider
            ),
            "default_scopes": normalize_scopes(default_scopes or []),
            "scope_aliases": {},
            "supports_refresh_token": bool(supports_refresh_token),
            "pkce_required": bool(pkce_required),
            "enabled": False,
            "token_endpoint_auth_method": token_endpoint_auth_method,
            "bootstrap_mode": "manual",
            "bootstrap_status": "validated",
            "metadata": {"bootstrap_source": "manual"},
            "provenance": {
                "client_id": "manual",
                "client_secret_ref": "secret_store" if client_secret_ref else None,
            },
        }
        row = await self._persist_draft(
            owner_user_id=owner_user_id,
            provider_key=provider,
            mode="manual",
            status="validated",
            metadata=metadata,
            diagnostics={"validated_at": _now_iso()},
            idempotency_key=idempotency_key,
        )
        return self._draft_result_from_row(row)

    async def run_dcr(
        self,
        *,
        owner_user_id: str,
        provider_key: str,
        display_name: str,
        registration_endpoint: str,
        authorize_url: str,
        token_url: str,
        client_name: str,
        token_endpoint_auth_method: TokenEndpointAuthMethod,
        scopes: list[str],
        supports_refresh_token: bool = True,
        issuer: str | None = None,
        idempotency_key: str | None = None,
    ) -> BootstrapDraftResult:
        provider = _require_provider_key(provider_key)
        existing = await self._get_idempotent(owner_user_id, idempotency_key)
        if existing is not None:
            return self._draft_result_from_row(existing)
        registration_url = _validate_https_url(
            registration_endpoint,
            field="registration_endpoint",
            allow_local=self._allow_local_http,
            enforce_public_network=self._http_client is None,
        )
        redirect_uri = build_redirect_uri(
            public_base_url=self._public_base_url, provider_key=provider
        )
        payload = build_dcr_registration_payload(
            client_name=client_name,
            redirect_uri=redirect_uri,
            scopes=scopes,
            token_endpoint_auth_method=token_endpoint_auth_method,
            supports_refresh_token=supports_refresh_token,
        )

        async def _post(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                registration_url,
                json=payload,
                headers={"Accept": "application/json"},
            )

        try:
            if self._http_client is None:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await _post(client)
            else:
                response = await _post(self._http_client)
            response.raise_for_status()
            dcr_response = response.json()
        except httpx.HTTPError as exc:
            raise OAuthProviderBootstrapError(
                "dynamic client registration failed",
                code="dcr_failed",
                retryable=True,
                diagnostics={"registration_endpoint": registration_url, "error": str(exc)},
            ) from exc

        client_id = str(dcr_response.get("client_id") or "").strip()
        if not client_id:
            raise OAuthProviderBootstrapError(
                "DCR response did not include client_id",
                code="dcr_missing_client_id",
                diagnostics={"dcr_response": redact_sensitive(dcr_response)},
            )
        client_secret_ref = None
        client_secret = str(dcr_response.get("client_secret") or "").strip()
        if client_secret:
            if self._secret_store is None:
                raise OAuthProviderBootstrapError(
                    "secret store is unavailable",
                    code="secret_store_unavailable",
                    retryable=True,
                )
            client_secret_ref = await self._secret_store.provision_provider_client_secret_ref(
                provider_key=provider,
                client_secret=client_secret,
            )
        metadata = {
            "provider_key": provider,
            "display_name": display_name or provider,
            "issuer": issuer,
            "authorize_url": _validate_https_url(
                authorize_url,
                field="authorize_url",
                allow_local=self._allow_local_http,
                enforce_public_network=self._http_client is None,
            ),
            "token_url": _validate_https_url(
                token_url,
                field="token_url",
                allow_local=self._allow_local_http,
                enforce_public_network=self._http_client is None,
            ),
            "registration_endpoint": registration_url,
            "client_id": client_id,
            "client_secret_ref": client_secret_ref,
            "redirect_uri": redirect_uri,
            "default_scopes": normalize_scopes(scopes),
            "scope_aliases": {},
            "supports_refresh_token": supports_refresh_token,
            "pkce_required": True,
            "enabled": False,
            "token_endpoint_auth_method": token_endpoint_auth_method,
            "bootstrap_mode": "dcr",
            "bootstrap_status": "validated",
            "metadata": {"bootstrap_source": "dcr", "dcr_response": redact_sensitive(dcr_response)},
        }
        row = await self._persist_draft(
            owner_user_id=owner_user_id,
            provider_key=provider,
            mode="dcr",
            status="validated",
            metadata=metadata,
            diagnostics={"dcr_registered_at": _now_iso()},
            idempotency_key=idempotency_key,
        )
        return self._draft_result_from_row(row)

    async def enable(
        self, *, owner_user_id: str, draft_id: str, provider_key: str | None = None
    ) -> dict[str, Any]:
        normalized_provider = _require_provider_key(provider_key) if provider_key else None
        clean_draft_id = draft_id.strip()
        if not clean_draft_id:
            raise OAuthProviderBootstrapError("draft_id is required", code="missing_draft_id")
        if normalized_provider is not None:
            fetch_draft = getattr(self._repo, "fetch_oauth_provider_bootstrap_draft", None)
            if not callable(fetch_draft):
                raise OAuthProviderBootstrapError(
                    "OAuth provider draft verification is unavailable",
                    code="oauth_provider_draft_verification_unavailable",
                    retryable=True,
                )
            draft = await fetch_draft(draft_id=clean_draft_id, owner_user_id=owner_user_id)
            if draft is None:
                raise OAuthProviderBootstrapError(
                    "OAuth provider bootstrap draft not found", code="draft_not_found"
                )
            draft_metadata = draft.get("metadata") or {}
            draft_provider = _require_provider_key(
                str(draft.get("provider_key") or draft_metadata.get("provider_key") or "")
            )
            if draft_provider != normalized_provider:
                raise OAuthProviderBootstrapError(
                    "OAuth provider bootstrap draft/provider mismatch",
                    code="provider_key_mismatch",
                    diagnostics={
                        "path_provider_key": normalized_provider,
                        "draft_provider_key": draft_provider,
                    },
                )
        promoted = await self._repo.promote_oauth_provider_bootstrap_draft(
            draft_id=clean_draft_id,
            owner_user_id=owner_user_id,
        )
        if isinstance(promoted, list):
            return promoted[0] if promoted else {}
        return promoted

    async def _fetch_json(self, url: str) -> dict[str, Any]:
        if self._http_client is None:
            _validate_https_url(
                url,
                field="metadata_url",
                allow_local=self._allow_local_http,
                enforce_public_network=True,
            )

        async def _get(client: httpx.AsyncClient) -> httpx.Response:
            return await client.get(url, headers={"Accept": "application/json"})

        try:
            if self._http_client is None:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await _get(client)
            else:
                response = await _get(self._http_client)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise OAuthProviderBootstrapError(
                "failed to fetch OAuth metadata",
                code="metadata_fetch_failed",
                retryable=True,
                diagnostics={"url": url, "error": str(exc)},
            ) from exc
        if not isinstance(data, dict):
            raise OAuthProviderBootstrapError(
                "metadata response must be an object", code="invalid_metadata"
            )
        return data

    async def _get_idempotent(self, owner_user_id: str, idempotency_key: str | None) -> dict | None:
        if not idempotency_key:
            return None
        return await self._repo.fetch_bootstrap_draft_by_idempotency_key(
            owner_user_id=owner_user_id,
            idempotency_key=idempotency_key,
        )

    async def _persist_draft(
        self,
        *,
        owner_user_id: str,
        provider_key: str,
        mode: BootstrapMode,
        status: BootstrapStatus,
        metadata: dict[str, Any],
        diagnostics: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict:
        payload = {
            "owner_user_id": owner_user_id,
            "provider_key": provider_key,
            "bootstrap_mode": mode,
            "status": status,
            "metadata": redact_sensitive(metadata),
            "diagnostics": redact_sensitive(diagnostics),
            "idempotency_key": idempotency_key,
            "updated_at": _now_iso(),
        }
        row = await self._repo.create_oauth_provider_bootstrap_draft(payload)
        if isinstance(row, list):
            return row[0] if row else payload
        return row

    @staticmethod
    def _draft_result_from_row(row: dict) -> BootstrapDraftResult:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        diagnostics = row.get("diagnostics") if isinstance(row.get("diagnostics"), dict) else {}
        return BootstrapDraftResult(
            draft_id=str(row.get("id") or row.get("draft_id") or "") or None,
            provider_key=str(row.get("provider_key") or metadata.get("provider_key") or ""),
            status=str(row.get("status") or metadata.get("bootstrap_status") or "draft"),  # type: ignore[arg-type]
            mode=str(row.get("bootstrap_mode") or metadata.get("bootstrap_mode") or "manual"),  # type: ignore[arg-type]
            metadata=metadata,
            diagnostics=diagnostics,
            idempotency_key=row.get("idempotency_key"),
        )


def build_state_nonce() -> tuple[str, str]:
    """Return opaque state nonce plus its SHA-256 hash for storage."""
    nonce = secrets.token_urlsafe(32)
    return nonce, hash_state_nonce(nonce)


def hash_state_nonce(nonce: str) -> str:
    digest = hashlib.sha256(nonce.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def encode_oauth_state(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_oauth_state(state: str) -> dict[str, Any]:
    padded = state + "=" * (-len(state) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, json.JSONDecodeError) as exc:
        raise OAuthProviderBootstrapError(
            "Invalid OAuth state", code="invalid_oauth_state"
        ) from exc
    if int(payload.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
        raise OAuthProviderBootstrapError("OAuth state expired", code="oauth_state_expired")
    return payload
