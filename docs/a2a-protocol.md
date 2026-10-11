# A2A Protocol Compliance Notes

This service implements the Google Agent-to-Agent (A2A) protocol over
JSON-RPC 2.0, with the deviations from the original design doc noted below.

## Endpoints

| Method | Route | Description |
|---|---|---|
| GET | `/.well-known/agent.json` | Agent Card discovery |
| POST | `/` | JSON-RPC 2.0 dispatcher (`tasks/send`, `tasks/sendSubscribe`, `tasks/get`, `tasks/cancel`) |

## Deviations / fixes vs. the original design doc

1. **JSON-RPC errors use HTTP 200.** Protocol-level failures (method not
   found `-32601`, invalid params `-32602`, internal error `-32603`, task not
   found `-32001`, not cancelable `-32002`) are returned as HTTP 200 with the
   error object in the body, per JSON-RPC 2.0 and common A2A client behavior.
2. **`tasks/cancel` accepts `input-required` tasks.** The A2A spec allows
   canceling from `submitted`, `working`, and `input-required`. Terminal-state
   cancels are idempotent (return the existing task).
3. **SSE events cross process boundaries.** Task execution (Celery worker or
   in-process) publishes events through an EventBus backed by Redis pub/sub,
   not in-memory web-process queues. Local asyncio queues are the fallback
   when Redis is unavailable.
4. **Subscribe happens before execution.** For `tasks/sendSubscribe`, the SSE
   subscription is registered before the agent starts, so early status events
   are never dropped.
5. **Timezone-aware timestamps.** `datetime.now(timezone.utc)` everywhere;
   `datetime.utcnow` is deprecated on Python 3.12+.
6. **Root agent name** is `aysel_root_agent` (no trailing underscore) so clean
   names appear in logs, metadata, and responses.

## Streaming event format (`tasks/sendSubscribe`)

```
event: status
data: {"jsonrpc":"2.0","id":"req-002","result":{"id":"...","sessionId":"...","status":"working","timestamp":"...","message":{...}}}

event: artifact
data: {"jsonrpc":"2.0","id":"req-002","result":{"id":"...","sessionId":"...","artifact":{...},"timestamp":"..."}}

event: status
data: {"jsonrpc":"2.0","id":"req-002","result":{...,"status":"completed",...}}
```

SSE comments (`: keepalive`) are emitted as heartbeats while a task runs.

## Task state machine

```
submitted -> working -> completed
submitted -> canceled
working   -> input-required -> working     (follow-up via same task id)
working   -> canceled
working   -> failed      (agent/infra error; terminal)
input-required -> canceled
```

`failed` is terminal per the A2A spec; tasks are never left dangling in
`working` when execution raises.

## Verification TODOs before production

- Confirm `google.adk.*` import paths (agents/search_agent.py,
  agents/url_context_agent.py, services/agent_runner.py) against the pinned
  `google-adk` version — tool module names have shifted across 1.x releases.
- Set up Alembic: `alembic init models/migrations` (the ORM models are ready;
  use `db.connection.engine` and `models.base.Base.metadata` in env.py).
- Enable `AUTH_ENABLED=true` and configure real JWT credentials.
