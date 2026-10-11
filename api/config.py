"""Application settings loaded from environment / .env (pydantic-settings)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_audience: str = ""

    # Endpoint
    a2a_endpoint_url: str = "http://localhost:8000"
    max_task_timeout: int = 300
    sse_heartbeat_seconds: int = 15


settings = Settings()
