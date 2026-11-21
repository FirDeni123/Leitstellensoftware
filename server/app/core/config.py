"""Central configuration.

All settings are read from environment variables (prefix ``ILS_``) or an ``.env`` file.
Secrets (JWT secret, encryption keys, database password) are never hard-coded; the
defaults below are only usable in ``development`` and are rejected in ``production``.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.4.0"

_DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me-0123456789"  # noqa: S105
# Fernet key used only for development/tests (base64, 32 bytes). Never valid in production.
_DEV_ENCRYPTION_KEY = "ZGV2LW9ubHktaW5zZWN1cmUta2V5LWNoYW5nZS1tZSE="


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ILS_", env_file=".env", extra="ignore")

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_json: bool = True

    # --- Database / Redis -------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://ils:ils_dev@localhost:5432/ils"
    database_pool_size: int = 10
    # Redis is optional: without it the event bus runs in-process (single server instance).
    redis_url: str | None = None

    # --- HTTP -----------------------------------------------------------------------------
    # app://ils is the origin of the packaged Windows client; localhost ports are the
    # renderer dev server (5173) and the web preview used by end-to-end tests (4173).
    cors_origins: list[str] = Field(
        default_factory=lambda: ["app://ils", "http://localhost:5173", "http://localhost:4173"]
    )
    # Number of reverse proxies in front of the app whose X-Forwarded-For can be trusted.
    trusted_proxy_count: int = 0

    # --- Authentication -------------------------------------------------------------------
    jwt_secret: str = _DEV_JWT_SECRET
    jwt_issuer: str = "ils-sim"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    password_min_length: int = 10

    # --- Encryption of stored secrets (API keys of interfaces) ----------------------------
    # Comma separated list of Fernet keys. The first key encrypts, all keys decrypt
    # (allows key rotation). Generate with: ils-admin generate-key
    encryption_keys: str = _DEV_ENCRYPTION_KEY

    # Local time zone of the control centres (e.g. year of incident numbers).
    timezone: str = "Europe/Berlin"

    # --- Realtime -------------------------------------------------------------------------
    ws_auth_timeout_seconds: float = 5.0
    ws_heartbeat_seconds: float = 20.0

    @model_validator(mode="after")
    def _reject_insecure_production_defaults(self) -> Settings:
        if self.environment == Environment.PRODUCTION:
            problems = []
            if self.jwt_secret == _DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                problems.append("ILS_JWT_SECRET muss gesetzt sein (mindestens 32 Zeichen)")
            if _DEV_ENCRYPTION_KEY in self.encryption_keys.split(","):
                problems.append("ILS_ENCRYPTION_KEYS darf nicht den Entwicklungsschlüssel enthalten")
            if "ils_dev" in self.database_url:
                problems.append("ILS_DATABASE_URL verwendet das Entwicklungspasswort")
            if problems:
                raise ValueError("Unsichere Produktionskonfiguration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
