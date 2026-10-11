"""A2A protocol endpoint integration tests (JSON-RPC + SSE)."""
from __future__ import annotations

import json

from tests.conftest import send_payload


async def test_tasks_send_happy_path(client):
    resp = await client.post("/", json=send_payload("tasks/send", task_id="task-abc"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == "req-001"
    assert body["result"]["status"] == "completed"
    roles = [m["role"] for m in body["result"]["messages"]]
    assert roles == ["user", "agent"]
    assert body["result"]["artifacts"][0]["name"] == "market-gap-report"
    assert body["result"]["metadata"]["agent_used"] == "aysel_root_agent"


async def test_unknown_method_is_jsonrpc_error_with_http_200(client):
    """Fix check: JSON-RPC errors must be HTTP 200 with the error in the body."""
    resp = await client.post("/", json={
        "jsonrpc": "2.0", "id": "req-x", "method": "tasks/nonexistent", "params": {},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "req-x"
    assert body["error"]["code"] == -32601


async def test_invalid_json_returns_parse_level_error(client):
    resp = await client.post("/", content=b"{not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32600


async def test_invalid_params_returns_32602(client):
    resp = await client.post("/", json={
        "jsonrpc": "2.0", "id": "req-p", "method": "tasks/send",
        "params": {"message": {"role": "agent", "parts": [{"type": "bogus"}]}},
    })
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32602


async def test_tasks_get_roundtrip(client):
    created = await client.post("/", json=send_payload("tasks/send", task_id="task-get-1"))
    fetched = await client.post("/", json={
        "jsonrpc": "2.0", "id": "req-3", "method": "tasks/get",
        "params": {"id": "task-get-1"},
    })
    assert fetched.status_code == 200
    assert fetched.json()["result"]["id"] == "task-get-1"


async def test_tasks_get_unknown_task(client):
    resp = await client.post("/", json={
        "jsonrpc": "2.0", "id": "req-4", "method": "tasks/get",
        "params": {"id": "no-such-task"},
    })
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32001


async def test_send_subscribe_streams_status_events(client):
    """Fix check: subscribe-before-run means the FIRST event must not be lost —
    the stream must start with the 'working' status."""
    async with client.stream("POST", "/", json=send_payload("tasks/sendSubscribe")) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = []
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:"):].strip()))
    statuses = [e["result"]["status"] for e in events if "status" in e["result"]]
    assert statuses[0] == "working"
    assert statuses[-1] == "completed"
