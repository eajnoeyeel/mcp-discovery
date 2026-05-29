"""Tests for gateway runtime settings."""

from service.gateway.settings import GatewaySettings


def test_gateway_settings_require_internal_secret_when_gateway_enabled() -> None:
    settings = GatewaySettings.model_validate(
        {
            "gateway_base_url": "https://gateway.example.com",
            "internal_auth_secret": "shared-secret",
            "session_pool_max_size": 32,
        }
    )

    assert settings.gateway_base_url == "https://gateway.example.com"
    assert settings.internal_auth_secret == "shared-secret"
    assert settings.session_pool_max_size == 32


def test_gateway_settings_default_secret_backend_is_supabase_until_secret_refs_land() -> None:
    settings = GatewaySettings.model_validate({"internal_auth_secret": "shared-secret"})

    assert settings.secret_backend == "supabase"
