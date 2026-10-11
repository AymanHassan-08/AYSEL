"""A2A JSON-RPC dispatcher.

Key fixes vs. the original design doc:
- JSON-RPC-level errors (method not found, invalid params, internal error)
  are returned with HTTP 200 and the error in the envelope, per JSON-RPC 2.0
  conventions and A2A client expectations.
- Requests are validated with Pydantic models (one per method) instead of
  raw dict access.
- `tasks/sendSubscribe` registers the SSE subscription BEFORE task execution
  starts, so no events are lost to a subscribe/run race.
- `tasks/cancel` accepts tasks in submitted, working, AND input-required
  states, per the A2A spec.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.dependencies import AuthClaims
from schemas.a2a import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    TASK_NOT_CANCELABLE,
    TASK_NOT_FOUND,
    CancelTaskRequest,
    GetTaskRequest,
    SendTaskRequest,
    SendTaskSubscribeRequest,
    TaskResponse,
    TaskState,
)

logger = logging.getLogger(__name__)

# A2A spec: input-required tasks are still cancelable.
CANCELABLE_STATES = {
    TaskState.SUBMITTED,
    TaskState.WORKING,
    TaskState.INPUT_REQUIRED,
}

router = APIRouter()

_METHODS = {
    "tasks/send": SendTaskRequest,
    "tasks/sendSubscribe": SendTaskSubscribeRequest,
    "tasks/get": GetTaskRequest,
    "tasks/cancel": CancelTaskRequest,
}


def rpc_error(rpc_id: Any, code: int, message: str, data: Any = None) -> JSONResponse:
    """JSON-RPC errors travel in the body — HTTP status stays 200."""
    body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        body["error"]["data"] = data
    return JSONResponse(status_code=200, content=body)


@router.get("/.well-known/agent.json")
async def get_agent_card() -> dict:
    """Agent Card discovery."""
    from services.a2a_handler import build_agent_card

    return build_agent_card().model_dump(exclude_none=True)


@router.post("/")
async def a2a_rpc_dispatcher(request: Request, claims: AuthClaims) -> Any:
    try:
        body = await request.json()
    except Exception:
        return rpc_error(None, INVALID_REQUEST, "Invalid JSON payload")

    if not isinstance(body, dict):
        return rpc_error(None, INVALID_REQUEST, "Request must be a JSON object")

    method = body.get("method")
    rpc_id = body.get("id")

    model_cls = _METHODS.get(method)
    if model_cls is None:
        return rpc_error(rpc_id, METHOD_NOT_FOUND, f"Method not found: {method!r}")

    try:
        rpc_request = model_cls.model_validate(body)
    except Exception as exc:
        return rpc_error(rpc_id, INVALID_PARAMS, f"Invalid params: {exc}")

    handler = request.app.state.a2a_handler

    try:
        match rpc_request:
            case SendTaskRequest():
                result = await handler.handle_send(rpc_request.params)
                return JSONResponse(
                    content=TaskResponse(id=rpc_id, result=result).model_dump(mode="json", exclude_none=True)
                )
            case SendTaskSubscribeRequest() as sub_req:

                async def event_stream():
                    async for event in handler.handle_send_subscribe(sub_req):
                        if event["event_type"] == "heartbeat":
                            yield ": keepalive\n\n"
                            continue
                        yield (
                            f"event: {event['event_type']}\n"
                            f"data: {json.dumps(event['payload'])}\n\n"
                        )

                return StreamingResponse(event_stream(), media_type="text/event-stream")
            case GetTaskRequest():
                result = await handler.handle_get(rpc_request.params.id)
                if result is None:
                    return rpc_error(rpc_id, TASK_NOT_FOUND, f"Task not found: {rpc_request.params.id}")
                return JSONResponse(
                    content=TaskResponse(id=rpc_id, result=result).model_dump(mode="json", exclude_none=True)
                )
            case CancelTaskRequest():
                result = await handler.handle_cancel(rpc_request.params.id)
                if result is None:
                    return rpc_error(rpc_id, TASK_NOT_FOUND, f"Task not found: {rpc_request.params.id}")
                if result.status != TaskState.CANCELED:
                    return rpc_error(
                        rpc_id,
                        TASK_NOT_CANCELABLE,
                        f"Task in state {result.status.value!r} cannot be canceled",
                    )
                return JSONResponse(
                    content=TaskResponse(id=rpc_id, result=result).model_dump(mode="json", exclude_none=True)
                )
    except Exception as exc:
        logger.exception("A2A handler error")
        return rpc_error(rpc_id, INTERNAL_ERROR, f"Internal error: {exc}")

    return rpc_error(rpc_id, INTERNAL_ERROR, "Unreachable dispatch branch")


__all__ = ["router", "rpc_error", "CANCELABLE_STATES"]
