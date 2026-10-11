"""Failure-path tests: an agent crash must leave the task in `failed`,
never dangling in `working`, and must surface a JSON-RPC error."""
from __future__ import annotations

import json

from tests.conftest import send_payload


async def test_send_agent_crash_returns_error_and_marks_failed(failing_client):
    resp = await failing_client.post("/", json=send_payload("tasks/send", task_id="t-fail"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"]["code"] == -32603

    fetched = await failing_client.post("/", json={
        "jsonrpc": "2.0", "id": "req-g", "method": "tasks/get",
        "params": {"id": "t-fail"},
    })
    assert fetched.json()["result"]["status"] == "failed"
    assert "Vertex AI" in fetched.json()["result"]["metadata"]["error"]


async def test_stream_agent_crash_terminates_with_failed_event(failing_client):
    async with failing_client.stream(
        "POST", "/", json=send_payload("tasks/sendSubscribe", task_id="t-sfail")
    ) as resp:
        events = []
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:"):].strip()))
    statuses = [e["result"]["status"] for e in events if "status" in e["result"]]
    assert statuses[-1] == "failed"
    assert "working" in statuses


async def test_failed_task_is_not_cancelable(failing_client):
    await failing_client.post("/", json=send_payload("tasks/send", task_id="t-nc"))
    resp = await failing_client.post("/", json={
        "jsonrpc": "2.0", "id": "req-c", "method": "tasks/cancel",
        "params": {"id": "t-nc"},
    })
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32002
