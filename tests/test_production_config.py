"""Production configuration tests: fail-fast boot and env validation."""
from __future__ import annotations

import pytest

from api.config import Settings


def prod_settings(**kw) -> Settings:
    kw.setdefault("environment", "production")
    return Settings(**kw)


def test_dev_defaults_are_not_fatal():
    s = Settings(environment="development")
    fatal, _ = s.production_problems()
    assert fatal == []


def test_prod_missing_project_and_default_jwt_are_fatal():
    fatal, _ = prod_settings().production_problems()
    msgs = " ".join(fatal)
    assert "GOOGLE_CLOUD_PROJECT" in msgs
    assert "JWT_SECRET" in msgs


def test_prod_with_secrets_set_has_no_fatal_problems():
    s = prod_settings(google_cloud_project="proj-1", jwt_secret="a-real-secret")
    fatal, _ = s.production_problems()
    assert fatal == []


def test_prod_warnings_without_full_hardening():
    s = prod_settings(
        google_cloud_project="proj-1",
        jwt_secret="a-real-secret",
        auth_enabled=False,
        database_url="sqlite+aiosqlite:///./x.db",
        a2a_endpoint_url="http://aysel.example.com",
    )
    _, warnings = s.production_problems()
    joined = " ".join(warnings)
    assert "AUTH_ENABLED" in joined
    assert "SQLite" in joined
    assert "https" in joined


def test_prod_fully_hardened_is_clean():
    s = prod_settings(
        google_cloud_project="proj-1",
        jwt_secret="a-real-secret",
        auth_enabled=True,
        database_url="postgresql+asyncpg://u:p@host/db",
        a2a_endpoint_url="https://aysel.example.com",
    )
    fatal, warnings = s.production_problems()
    assert fatal == []
    assert warnings == []


@pytest.mark.asyncio
async def test_lifespan_blocks_boot_on_fatal_prod_problems(monkeypatch):
    """A half-configured production env must fail fast, not serve."""
    import api.server as server_mod
    from fastapi import FastAPI

    bad = prod_settings()  # no project, default JWT secret
    monkeypatch.setattr(server_mod, "settings", bad)
    app = FastAPI()
    with pytest.raises(RuntimeError, match="fatal config"):
        async with server_mod.lifespan(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_boots_when_prod_problems_fixed(monkeypatch):
    import api.server as server_mod
    from fastapi import FastAPI

    good = prod_settings(
        google_cloud_project="proj-1",
        jwt_secret="a-real-secret",
        auth_enabled=True,
        database_url="postgresql+asyncpg://u:p@host/db",
        a2a_endpoint_url="https://aysel.example.com",
    )
    monkeypatch.setattr(server_mod, "settings", good)
    app = FastAPI()
    async with server_mod.lifespan(app):
        pass  # boot succeeded
