"""Type-safe CRUD queries for tasks, messages, and artifacts."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.task import ArtifactORM, MessageORM, TaskORM
from schemas.a2a import Artifact, Message, Task, TaskState


def new_task_id() -> str:
    return str(uuid.uuid4())


async def create_task(
    db: AsyncSession,
    *,
    task_id: Optional[str] = None,
    session_id: str,
    user_message: Message,
    metadata: Optional[dict[str, Any]] = None,
) -> TaskORM:
    task = TaskORM(
        id=task_id or new_task_id(),
        session_id=session_id,
        status=TaskState.SUBMITTED,
        metadata=metadata or {},
    )
    db.add(task)
    await db.flush()
    db.add(MessageORM(
        task_id=task.id,
        role="user",
        parts=[p.model_dump() for p in user_message.parts],
        metadata_=user_message.metadata or {},
    ))
    await db.flush()
    loaded = await get_task(db, task.id)
    assert loaded is not None
    return loaded


async def get_task(db: AsyncSession, task_id: str) -> Optional[TaskORM]:
    result = await db.execute(
        select(TaskORM)
        .options(selectinload(TaskORM.messages), selectinload(TaskORM.artifacts))
        .where(TaskORM.id == task_id)
    )
    return result.scalar_one_or_none()


async def update_status(
    db: AsyncSession, task_id: str, status: TaskState,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[TaskORM]:
    task = await get_task(db, task_id)
    if task is None:
        return None
    task.status = status
    if metadata:
        merged = dict(task.metadata_ or {})
        merged.update(metadata)
        task.metadata_ = merged
    await db.flush()
    return task


async def add_message(db: AsyncSession, task_id: str, message: Message) -> None:
    db.add(MessageORM(
        task_id=task_id,
        role=message.role,
        parts=[p.model_dump() for p in message.parts],
        metadata_=message.metadata or {},
    ))
    await db.flush()


async def add_artifact(db: AsyncSession, task_id: str, artifact: Artifact) -> None:
    db.add(ArtifactORM(
        task_id=task_id,
        name=artifact.name,
        parts=[p.model_dump() for p in artifact.parts],
        index=artifact.index,
        metadata_=artifact.metadata or {},
    ))
    await db.flush()


async def list_session_messages(
    db: AsyncSession, session_id: str
) -> list[Message]:
    """All messages across tasks in a session, in order — used as conversation
    history for follow-ups (input-required → working)."""
    rows = await db.execute(
        select(MessageORM)
        .join(TaskORM, TaskORM.id == MessageORM.task_id)
        .where(TaskORM.session_id == session_id)
        .order_by(MessageORM.id)
    )
    return [
        Message(role=row.role, parts=row.parts, metadata=row.metadata_ or {})
        for row in rows.scalars()
    ]


def task_to_model(task: TaskORM) -> Task:
    """Convert a TaskORM (with loaded relationships) to the wire Task model."""
    return Task(
        id=task.id,
        session_id=task.session_id,
        status=TaskState(task.status),
        messages=[
            Message(role=m.role, parts=m.parts, metadata=m.metadata_ or {})
            for m in task.messages
        ],
        artifacts=[
            Artifact(name=a.name, parts=a.parts, index=a.index, metadata=a.metadata_ or {})
            for a in task.artifacts
        ],
        history=[],
        metadata=task.metadata_ or {},
    )
