"""Shared fixtures: isolated DB, scripted agent runner, ASGI test client.

The scripted runner lets us test the full A2A protocol stack (routing,
state machine, SSE) without Google ADK or Vertex AI credentials.
"""
from __future__ import annotations

import asyncio
import os
import pathlib

# Configure the environment BEFORE any app import.
_TEST_DB = pathlib.Path("/tmp/aysel_test.db")
if _TEST_DB.exists():
    _TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"
os.environ["REDIS_URL"] = "redis://localhost:9/0"  # unreachable -> local bus
os.environ["AUTH_ENABLED"] = "false"

import pytest
from httpx import ASGITransport, AsyncClient

from api.server import create_app
from db.connection import dispose_db, init_db
from schemas.agent import AgentRunResult
from services.a2a_handler import A2AHandler
from services.stream_manager import EventBus


class ScriptedRunner:
    """Deterministic agent: returns one final message plus one artifact."""

    async def run(self, user_message: str) -> AgentRunResult:
        return AgentRunResult(
            final_message=f"Analysis complete for: {user_message}",
            artifacts=[{
                "name": "market-gap-report",
                "parts": [{"type": "text", "text": "# Report\n\nFindings..."}],
            }],
            metadata={"agent_used": "aysel_root_agent"},
        )


@pytest.fixture()
async def client():
    bus = EventBus()
    await bus.connect()  # Redis unreachable in tests -> in-process queues
    app = create_app(handler=A2AHandler(runner=ScriptedRunner(), bus=bus, use_celery=False))
    await init_db()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await dispose_db()
        if _TEST_DB.exists():
            _TEST_DB.unlink()


def send_payload(method: str, message_text: str = "Analyze African fintech gaps",
                 task_id: str | None = None, session_id: str | None = None) -> dict:
    params: dict = {
        "message": {"role": "user", "parts": [{"type": "text", "text": message_text}]},
    }
    if task_id:
        params["id"] = task_id
    if session_id:
        params["sessionId"] = session_id
    return {"jsonrpc": "2.0", "id": "req-001", "method": method, "params": params}


@pytest.fixture(autouse=True)
async def _tables():
    """Ensure tables exist for every test (lifecycle tests don't use `client`)."""
    await init_db()
    yield


class FailingRunner:
    """Simulates an agent crash (e.g. Vertex AI unavailable)."""

    async def run(self, user_message: str) -> AgentRunResult:
        raise RuntimeError("Vertex AI model request failed")


@pytest.fixture()
async def failing_client():
    bus = EventBus()
    await bus.connect()
    app = create_app(handler=A2AHandler(runner=FailingRunner(), bus=bus, use_celery=False))
    await init_db()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await dispose_db()
        if _TEST_DB.exists():
            _TEST_DB.unlink()
