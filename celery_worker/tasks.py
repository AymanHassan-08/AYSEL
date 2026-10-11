"""Celery tasks for background agent execution.

The worker publishes SSE events through the SAME EventBus the web processes
subscribe to. With Redis configured, events cross the process boundary via
pub/sub — this is the fix for the original StreamManager design, which held
queues only in web-process memory and could never receive worker events.
"""
from __future__ import annotations

import asyncio
import logging

from celery_worker.celeryconfig import celery_app

logger = logging.getLogger(__name__)


def _run(task_id: str, session_id: str, user_text: str, rpc_id=None) -> str:
    # Import inside the task so Celery workers can boot without the full
    # web app import chain at broker-connect time.
    from services.a2a_handler import A2AHandler

    handler = A2AHandler(use_celery=False)
    try:
        asyncio.run(handler._execute(task_id, session_id, user_text, rpc_id=rpc_id, publish=True))
    except Exception as exc:
        logger.exception("Agent task %s failed", task_id)
        raise exc
    return task_id


@celery_app.task(name="celery_worker.tasks.run_agent_task", bind=True, max_retries=2)
def run_agent_task(self, task_id: str, session_id: str, user_text: str, rpc_id=None) -> str:
    return _run(task_id, session_id, user_text, rpc_id)
