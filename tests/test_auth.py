"""Auth tests: Bearer/JWT gating on the JSON-RPC dispatcher.

The dispatcher takes the `verify_token` dependency; when AUTH_ENABLED=true,
requests without a valid Bearer token must be rejected with 401 before any
JSON-RPC processing happens.
"""
from __future__ import annotations

import pytest

from api.config import settings
from tests.conftest import send_payload


@pytest.fixture()
async def auth_client(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    monkeypatch.setattr(settings, "jwt_audience", "")
    return client


async def test_auth_disabled_allows_anonymous(client):
    """Default mode: no token needed."""
    resp = await client.post("/", json=send_payload("tasks/send"))
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "completed"


async def test_auth_enabled_rejects_missing_token(auth_client):
    resp = await auth_client.post("/", json=send_payload("tasks/send"))
    assert resp.status_code == 401


async def test_auth_enabled_rejects_bad_token(auth_client):
    resp = await auth_client.post(
        "/",
        json=send_payload("tasks/send"),
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


async def test_auth_enabled_accepts_valid_jwt(auth_client):
    import jwt

    token = jwt.encode({"sub": "test-client"}, "test-secret", algorithm="HS256")
    resp = await auth_client.post(
        "/",
        json=send_payload("tasks/send"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "completed"


async def test_agent_card_stays_public_when_auth_enabled(auth_client):
    """Agent Card discovery must not require auth per the A2A spec."""
    resp = await auth_client.get("/.well-known/agent.json")
    assert resp.status_code == 200
