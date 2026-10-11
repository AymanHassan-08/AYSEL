"""Pydantic models for the A2A protocol (JSON-RPC 2.0 envelope, task objects,
agent card, request/response types).

Fixes applied vs. the original design doc:
- Classes are ordered so nothing is referenced before it is defined.
- `Part` is a proper discriminated union on the `type` field.
- All timestamps are timezone-aware (`datetime.utcnow` is deprecated on 3.12).
- Forward references are resolved with explicit `model_rebuild()` calls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    """Timezone-aware UTC now (replaces deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Parts — discriminated union on the "type" field
# --------------------------------------------------------------------------

class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class FilePart(BaseModel):
    type: Literal["file"] = "file"
    file: dict[str, Any]  # { name?: str, mimeType?: str, bytes?: str, uri?: str }


class DataPart(BaseModel):
    type: Literal["data"] = "data"
    data: dict[str, Any]


Part = Annotated[Union[TextPart, FilePart, DataPart], Field(discriminator="type")]


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"


TERMINAL_STATES = {TaskState.COMPLETED, TaskState.CANCELED, TaskState.FAILED}


# --------------------------------------------------------------------------
# Core protocol objects
# --------------------------------------------------------------------------

class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[Part]
    metadata: Optional[dict[str, Any]] = None


class Artifact(BaseModel):
    name: Optional[str] = None
    parts: list[Part]
    index: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None
    append: Optional[bool] = None


class Task(BaseModel):
    id: str
    session_id: str
    status: TaskState
    messages: list[Message] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    history: list[Message] = Field(default_factory=list)
    metadata: Optional[dict[str, Any]] = None


# --------------------------------------------------------------------------
# Agent Card
# --------------------------------------------------------------------------

class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    inputModes: list[str] = Field(default_factory=lambda: ["text"])
    outputModes: list[str] = Field(default_factory=lambda: ["text"])


class AgentProvider(BaseModel):
    organization: str
    url: Optional[str] = None


class AgentCapabilities(BaseModel):
    streaming: bool = True
    pushNotifications: bool = False
    stateTransitionHistory: bool = True


class AgentAuthentication(BaseModel):
    schemes: list[str] = Field(default_factory=lambda: ["Bearer"])
    credentials: Optional[str] = None


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    provider: Optional[AgentProvider] = None
    version: str = "1.0.0"
    documentationUrl: Optional[str] = None
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    authentication: AgentAuthentication = Field(default_factory=AgentAuthentication)
    defaultInputModes: list[str] = Field(default_factory=lambda: ["text"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["text"])
    skills: list[AgentSkill]


# --------------------------------------------------------------------------
# Request params — defined BEFORE the requests that reference them
# --------------------------------------------------------------------------

class TaskSendParams(BaseModel):
    id: Optional[str] = None  # auto-generated (UUIDv4) if absent
    sessionId: Optional[str] = None
    acceptedOutputModes: Optional[list[str]] = None
    message: Message
    metadata: Optional[dict[str, Any]] = None


class TaskIdParams(BaseModel):
    id: str


# --------------------------------------------------------------------------
# JSON-RPC requests
# --------------------------------------------------------------------------

class SendTaskRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int
    method: Literal["tasks/send"] = "tasks/send"
    params: TaskSendParams


class SendTaskSubscribeRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int
    method: Literal["tasks/sendSubscribe"] = "tasks/sendSubscribe"
    params: TaskSendParams


class GetTaskRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int
    method: Literal["tasks/get"] = "tasks/get"
    params: TaskIdParams


class CancelTaskRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int
    method: Literal["tasks/cancel"] = "tasks/cancel"
    params: TaskIdParams


A2ARequest = Union[
    SendTaskSubscribeRequest,
    SendTaskRequest,
    GetTaskRequest,
    CancelTaskRequest,
]


# --------------------------------------------------------------------------
# JSON-RPC responses
# --------------------------------------------------------------------------

class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class TaskResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    result: Optional[Task] = None
    error: Optional[JSONRPCError] = None


class TaskStatusUpdate(BaseModel):
    id: str
    sessionId: str
    status: TaskState
    timestamp: datetime = Field(default_factory=utcnow)
    message: Optional[Message] = None


class TaskStatusUpdateEvent(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    result: TaskStatusUpdate


class TaskArtifactUpdate(BaseModel):
    id: str
    sessionId: str
    artifact: Artifact
    timestamp: datetime = Field(default_factory=utcnow)


class TaskArtifactUpdateEvent(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    result: TaskArtifactUpdate


# Resolve any remaining forward references (defensive; ordering above already
# avoids most, but keep explicit in case of future edits).
for _model in (TaskResponse, TaskStatusUpdateEvent, TaskArtifactUpdateEvent):
    _model.model_rebuild()


# --------------------------------------------------------------------------
# JSON-RPC error codes
# --------------------------------------------------------------------------

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002
