"""Runtime settings for the long-running MLP gateway."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Environment-backed settings for the App Runner gateway runtime."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    gateway_base_url: str | None = Field(default=None, validation_alias="GATEWAY_BASE_URL")
    internal_auth_secret: str = Field(validation_alias="GATEWAY_INTERNAL_AUTH_SECRET")
    internal_auth_max_age_seconds: int = Field(
        default=300,
        ge=1,
        validation_alias="GATEWAY_INTERNAL_AUTH_MAX_AGE_SECONDS",
    )
    session_pool_max_size: int = Field(
        default=32,
        ge=1,
        validation_alias="GATEWAY_SESSION_POOL_MAX_SIZE",
    )
    secret_backend: str = Field(default="supabase", validation_alias="GATEWAY_SECRET_BACKEND")
    gateway_log_level: str = Field(default="INFO", validation_alias="GATEWAY_LOG_LEVEL")


@lru_cache(maxsize=1)
def get_gateway_settings() -> GatewaySettings:
    """Return cached gateway settings for process startup wiring."""

    return GatewaySettings()
