"""Task lifecycle and state-transition tests."""
from __future__ import annotations

import pytest

from db.connection import session_factory
from schemas.a2a import Message, TaskState, TextPart
from services.task_service import InvalidTransition, TaskService


def user_message(text: str = "hello") -> Message:
    return Message(role="user", parts=[TextPart(text=text)])


async def test_full_lifecycle():
    async with session_factory() as db:
        svc = TaskService(db)
        task = await svc.create(task_id="t1", session_id="s1", user_message=user_message())
        assert task.status == TaskState.SUBMITTED

        task = await svc.transition("t1", TaskState.WORKING)
        assert task.status == TaskState.WORKING

        task = await svc.transition("t1", TaskState.COMPLETED)
        assert task.status == TaskState.COMPLETED

        await db.commit()


async def test_illegal_transition_rejected():
    async with session_factory() as db:
        svc = TaskService(db)
        await svc.create(task_id="t2", session_id="s2", user_message=user_message())
        with pytest.raises(InvalidTransition):
            await svc.transition("t2", TaskState.COMPLETED)  # submitted -> completed
        await db.rollback()


async def test_cancel_from_input_required_allowed():
    """Fix check: per the A2A spec, input-required tasks are cancelable."""
    async with session_factory() as db:
        svc = TaskService(db)
        await svc.create(task_id="t3", session_id="s3", user_message=user_message())
        await svc.transition("t3", TaskState.WORKING)
        await svc.transition("t3", TaskState.INPUT_REQUIRED)
        task = await svc.cancel("t3")
        assert task.status == TaskState.CANCELED
        await db.commit()


async def test_cancel_is_idempotent_when_terminal():
    async with session_factory() as db:
        svc = TaskService(db)
        await svc.create(task_id="t4", session_id="s4", user_message=user_message())
        first = await svc.cancel("t4")
        second = await svc.cancel("t4")
        assert first.status == TaskState.CANCELED
        assert second.status == TaskState.CANCELED
        await db.commit()
