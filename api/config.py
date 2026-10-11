"""Application settings loaded from environment / .env (pydantic-settings).

Production mode: set ENVIRONMENT=production. Boot then fails fast on
misconfiguration (see `validate_production`) instead of serving a
half-configured endpoint.
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEV_JWT_SECRET = "dev-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Runtime environment: "development" | "production"
    environment: Literal["development", "production"] = "development"
    log_level: str = "INFO"

    # GCP / Vertex AI
    google_cloud_project: str = ""
    google_application_credentials: str = ""
    agent_model: str = "gemini-3.5-flash"

    # Database
    database_url: str = "sqlite+aiosqlite:///./aysel.db"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    use_celery: bool = False

    # Auth
    auth_enabled: bool = False
    jwt_secret: str = _DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_audience: str = ""

    # Endpoint
    a2a_endpoint_url: str = "http://localhost:8000"
    max_task_timeout: int = 300
    sse_heartbeat_seconds: int = 15

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("max_task_timeout", "sse_heartbeat_seconds")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be positive")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def production_problems(self) -> tuple[list[str], list[str]]:
        """Return (fatal, warnings) for the current configuration.

        Fatal problems should block boot in production; warnings are logged.
        In development nothing is fatal.
        """
        fatal: list[str] = []
        warnings: list[str] = []

        if not self.google_cloud_project:
            (fatal if self.is_production else warnings).append(
                "GOOGLE_CLOUD_PROJECT is not set — the ADK agent cannot call "
                "Vertex AI without it."
            )
        if self.jwt_secret == _DEV_JWT_SECRET:
            (fatal if self.is_production else warnings).append(
                "JWT_SECRET is the built-in development default — anyone can "
                "forge tokens."
            )
        if self.is_production and not self.auth_enabled:
            warnings.append(
                "AUTH_ENABLED=false in production: the endpoint accepts "
                "unauthenticated JSON-RPC calls."
            )
        if self.is_production and not self.a2a_endpoint_url.startswith("https://"):
            warnings.append(
                "A2A_ENDPOINT_URL does not start with https:// — the Agent "
                "Card will advertise an insecure URL."
            )
        if self.is_production and "sqlite" in self.database_url:
            warnings.append(
                "DATABASE_URL uses SQLite — task history is lost on every "
                "container restart. Use Cloud SQL Postgres for durable state."
            )
        return fatal, warnings


settings = Settings()

# Early signal at import time; the app lifespan (api/server.py) decides
# whether fatal problems actually block boot.
_problems, _warnings = settings.production_problems()
for _p in _problems:
    logger.error("Config (fatal in production): %s", _p)
for _w in _warnings:
    logger.warning("Config warning: %s", _w)
