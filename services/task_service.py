"""Task lifecycle: state machine + persistence.

State machine (per design doc, plus the A2A-spec fix that input-required
tasks may also be canceled):

    submitted -> working -> completed
    submitted -> canceled
    working   -> input-required -> working   (follow-up via same sessionId)
    working   -> canceled
    input-required -> canceled
working -> failed (agent/infra error)
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db.queries import (
    add_artifact,
    add_message,
    create_task,
    get_task,
    task_to_model,
    update_status,
)
from schemas.a2a import Artifact, Message, Task, TaskState

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.SUBMITTED: {TaskState.WORKING, TaskState.CANCELED},
    TaskState.WORKING: {
        TaskState.COMPLETED,
        TaskState.INPUT_REQUIRED,
        TaskState.CANCELED,
        TaskState.FAILED,
    },
    TaskState.INPUT_REQUIRED: {TaskState.WORKING, TaskState.CANCELED},
    TaskState.COMPLETED: set(),
    TaskState.CANCELED: set(),
    TaskState.FAILED: set(),
}


class InvalidTransition(Exception):
    pass


class TaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        task_id: Optional[str],
        session_id: str,
        user_message: Message,
        metadata: Optional[dict] = None,
    ) -> Task:
        task_orm = await create_task(
            self.db,
            task_id=task_id,
            session_id=session_id,
            user_message=user_message,
            metadata=metadata,
        )
        return task_to_model(task_orm)

    async def get(self, task_id: str) -> Optional[Task]:
        task_orm = await get_task(self.db, task_id)
        if task_orm is None:
            return None
        return task_to_model(task_orm)

    async def transition(
        self,
        task_id: str,
        new_state: TaskState,
        *,
        agent_message: Optional[Message] = None,
        metadata: Optional[dict] = None,
    ) -> Task:
        current = await self.get(task_id)
        if current is None:
            raise KeyError(task_id)
        current_state = TaskState(current.status)
        if new_state not in ALLOWED_TRANSITIONS[current_state]:
            raise InvalidTransition(
                f"Illegal transition {current_state.value} -> {new_state.value}"
            )
        await update_status(self.db, task_id, new_state, metadata)
        if agent_message is not None:
            await add_message(self.db, task_id, agent_message)
        refreshed = await self.get(task_id)
        assert refreshed is not None
        return refreshed

    async def cancel(self, task_id: str) -> Task:
        current = await self.get(task_id)
        if current is None:
            raise KeyError(task_id)
        current_state = TaskState(current.status)
        if current_state in (
            TaskState.COMPLETED, TaskState.CANCELED, TaskState.FAILED,
        ):
            # Already terminal — idempotent cancel per A2A guidance; the
            # caller decides whether a terminal-but-not-canceled task is
            # an error (routes maps it to -32002).
            return current
        return await self.transition(
            task_id,
            TaskState.CANCELED,
            metadata={"canceled_by": "client"},
        )

    async def record_artifact(self, task_id: str, artifact: Artifact) -> None:
        await add_artifact(self.db, task_id, artifact)

    async def record_message(self, task_id: str, message: Message) -> None:
        await add_message(self.db, task_id, message)
