"""A2A protocol method handling: send, sendSubscribe, get, cancel.

Execution model:
- In-process (default): the agent runs in an asyncio task inside the web
  process. Simple, and streaming works with or without Redis.
- Celery (USE_CELERY=true): the agent runs in the Celery worker; SSE events
  flow back through the Redis pub/sub event bus. tasks/send enqueues and
  polls the DB for a terminal state until MAX_TASK_TIMEOUT.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncIterator, Optional

from api.config import settings
from db.connection import session_factory
from schemas.a2a import (
    TERMINAL_STATES,
    AgentCapabilities,
    AgentCard,
    AgentProvider,
    AgentSkill,
    Artifact,
    Message,
    Task,
    TaskArtifactUpdateEvent,
    TaskArtifactUpdate,
    TaskSendParams,
    TaskState,
    TaskStatusUpdate,
    TaskStatusUpdateEvent,
    TextPart,
)
from services.agent_runner import AgentRunner, AdkAgentRunner
from services.stream_manager import EventBus, event_bus
from services.task_service import TaskService

logger = logging.getLogger(__name__)


def build_agent_card() -> AgentCard:
    return AgentCard(
        name="Aysel",
        description=(
            "Strategic business development research agent specializing in "
            "market gap identification and global financing system analysis, "
            "with real-time web search and deep URL content retrieval."
        ),
        url=settings.a2a_endpoint_url,
        provider=AgentProvider(
            organization="Aysel Research Group",
            url=f"{settings.a2a_endpoint_url}/about",
        ),
        version="0.1.0",
        documentationUrl=f"{settings.a2a_endpoint_url}/docs",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=True,
        ),
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        skills=[
            AgentSkill(
                id="market-gap-analysis",
                name="Market Gap Analysis",
                description=(
                    "Identify untapped market opportunities and competitive "
                    "advantages through specialized research."
                ),
                tags=["market-research", "business-strategy", "competitive-analysis"],
                examples=[
                    "Analyze market gaps in the renewable energy sector",
                    "Identify untapped opportunities in Southeast Asian fintech",
                ],
            ),
            AgentSkill(
                id="global-financing-systems",
                name="Global Financing Systems",
                description=(
                    "Comprehensive analysis of global financing mechanisms, "
                    "funding systems, and capital allocation strategies."
                ),
                tags=["finance", "investment", "capital-markets", "global-economy"],
                examples=[
                    "Explain venture capital ecosystems in emerging markets",
                    "Analyze cross-border investment regulations and opportunities",
                ],
            ),
            AgentSkill(
                id="web-search",
                name="Intelligent Web Search",
                description=(
                    "Real-time information retrieval from the web using Google "
                    "Search to supplement agent knowledge."
                ),
                tags=["search", "research", "real-time-data"],
                examples=[
                    "Search for latest trends in AI startup funding",
                    "Find recent policy changes affecting foreign direct investment",
                ],
            ),
            AgentSkill(
                id="url-content-analysis",
                name="URL Content Analysis",
                description=(
                    "Deep content extraction and analysis from provided URLs "
                    "for comprehensive research synthesis."
                ),
                tags=["content-analysis", "url-processing", "deep-research"],
                examples=[
                    "Extract and summarize key findings from this World Bank report URL",
                    "Analyze the investment thesis presented in this article",
                ],
            ),
        ],
    )


def _text_of(message: Message) -> str:
    return " ".join(
        p.text for p in message.parts if getattr(p, "type", None) == "text" and p.text
    )


class A2AHandler:
    def __init__(
        self,
        runner: Optional[AgentRunner] = None,
        bus: Optional[EventBus] = None,
        use_celery: Optional[bool] = None,
    ) -> None:
        self.runner = runner or AdkAgentRunner()
        self.bus = bus or event_bus
        self.use_celery = settings.use_celery if use_celery is None else use_celery

    # ------------------------------------------------------------------
    # tasks/send
    # ------------------------------------------------------------------

    async def handle_send(self, params: TaskSendParams) -> Task:
        task = await self._upsert_task(params)
        user_text = _text_of(params.message)

        if self.use_celery:
            from celery_worker.tasks import run_agent_task

            run_agent_task.delay(task.id, task.session_id, user_text, params.id)
            return await self._await_terminal(task.id)
        return await self._execute(task.id, task.session_id, user_text, rpc_id=params.id)

    # ------------------------------------------------------------------
    # tasks/sendSubscribe
    # ------------------------------------------------------------------

    async def handle_send_subscribe(self, request) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE-ready event dicts.

        Fix: the subscription is registered BEFORE execution starts, so no
        early status/artifact events are dropped.
        """
        params: TaskSendParams = request.params
        task = await self._upsert_task(params)
        user_text = _text_of(params.message)

        subscription = await self.bus.register(task.id)

        async def run_execution() -> None:
            try:
                if self.use_celery:
                    from celery_worker.tasks import run_agent_task

                    run_agent_task.delay(task.id, task.session_id, user_text, params.id)
                else:
                    await self._execute(
                        task.id, task.session_id, user_text, rpc_id=params.id,
                        publish=True,
                    )
            except Exception:
                logger.exception("Streamed execution failed for task %s", task.id)
                # Guarantee the stream terminates even if _execute could not
                # record the failure (e.g. DB down).
                task_now = None
                try:
                    task_now = await self.handle_get(task.id)
                except Exception:
                    pass
                if task_now is None or task_now.status not in TERMINAL_STATES:
                    await self.bus.publish(
                        task.id, "status",
                        self._status_payload(
                            task.id, task.session_id, TaskState.FAILED,
                            params.id,
                            message=Message(
                                role="agent",
                                parts=[TextPart(text="Internal error during execution.")],
                            ),
                        ),
                    )

        execution = asyncio.create_task(run_execution())
        try:
            async for event in subscription.events():
                yield event
        finally:
            await subscription.close()
            try:
                await execution
            except Exception:
                logger.exception("Execution task errored after stream closed")

    # ------------------------------------------------------------------
    # tasks/get, tasks/cancel
    # ------------------------------------------------------------------

    async def handle_get(self, task_id: str) -> Optional[Task]:
        async with session_factory() as db:
            return await TaskService(db).get(task_id)

    async def handle_cancel(self, task_id: str) -> Optional[Task]:
        async with session_factory() as db:
            svc = TaskService(db)
            try:
                return await svc.cancel(task_id)
            except KeyError:
                return None

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _upsert_task(self, params: TaskSendParams) -> Task:
        """Create a task, or resume an input-required task via follow-up."""
        async with session_factory() as db:
            svc = TaskService(db)
            try:
                if params.id:
                    existing = await svc.get(params.id)
                    if existing is not None:
                        if existing.status == TaskState.INPUT_REQUIRED:
                            # Follow-up: input-required -> working
                            await svc.transition(params.id, TaskState.WORKING)
                            await svc.record_message(params.id, params.message)
                            refreshed = await svc.get(params.id)
                            assert refreshed is not None
                            return refreshed
                        return existing
                return await svc.create(
                    task_id=params.id,
                    session_id=params.sessionId or str(uuid.uuid4()),
                    user_message=params.message,
                    metadata=params.metadata,
                )
            finally:
                await db.commit()

    async def _execute(
        self,
        task_id: str,
        session_id: str,
        user_text: str,
        *,
        rpc_id: Any = None,
        publish: bool = False,
    ) -> Task:
        """Run the agent and persist results. Publishes events when asked."""
        async with session_factory() as db:
            svc = TaskService(db)
            await svc.transition(task_id, TaskState.WORKING)
            await db.commit()

        if publish:
            await self.bus.publish(
                task_id, "status",
                self._status_payload(
                    task_id, session_id, TaskState.WORKING, rpc_id,
                    message=Message(
                        role="agent",
                        parts=[TextPart(text="Initiating research...")],
                    ),
                ),
            )

        try:
            result = await self.runner.run(user_text)
        except Exception as exc:
            logger.exception("Agent execution failed for task %s", task_id)
            async with session_factory() as db:
                svc = TaskService(db)
                try:
                    await svc.transition(
                        task_id, TaskState.FAILED, metadata={"error": str(exc)}
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.exception("Could not mark task %s as failed", task_id)
            if publish:
                await self.bus.publish(
                    task_id, "status",
                    self._status_payload(
                        task_id, session_id, TaskState.FAILED, rpc_id,
                        message=Message(
                            role="agent",
                            parts=[TextPart(text="Execution failed; see server logs.")],
                        ),
                    ),
                )
            raise

        async with session_factory() as db:
            svc = TaskService(db)
            if result.final_message:
                await svc.record_message(
                    task_id,
                    Message(role="agent", parts=[TextPart(text=result.final_message)]),
                )
            for artifact_dict in result.artifacts:
                artifact = Artifact.model_validate(artifact_dict)
                await svc.record_artifact(task_id, artifact)
                if publish:
                    await self.bus.publish(
                        task_id, "artifact",
                        TaskArtifactUpdateEvent(
                            id=rpc_id,
                            result=TaskArtifactUpdate(
                                id=task_id, sessionId=session_id, artifact=artifact,
                            ),
                        ).model_dump(mode="json", exclude_none=True),
                    )
            final_task = await svc.transition(
                task_id, TaskState.COMPLETED, metadata=result.metadata or None,
            )
            await db.commit()

        if publish:
            await self.bus.publish(
                task_id, "status",
                self._status_payload(
                    task_id, session_id, TaskState.COMPLETED, rpc_id,
                    message=Message(
                        role="agent",
                        parts=[TextPart(text=result.final_message or "Task completed.")],
                    ),
                ),
            )
        return final_task

    async def _await_terminal(self, task_id: str) -> Task:
        """Poll the DB until the (Celery-executed) task reaches a terminal state."""
        deadline = asyncio.get_event_loop().time() + settings.max_task_timeout
        while asyncio.get_event_loop().time() < deadline:
            task = await self.handle_get(task_id)
            if task is None:
                raise KeyError(task_id)
            if task.status in (TaskState.COMPLETED, TaskState.CANCELED, TaskState.INPUT_REQUIRED, TaskState.FAILED):
                return task
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Task {task_id} did not finish within {settings.max_task_timeout}s")

    def _status_payload(
        self,
        task_id: str,
        session_id: str,
        status: TaskState,
        rpc_id: Any,
        message: Optional[Message] = None,
    ) -> dict[str, Any]:
        return TaskStatusUpdateEvent(
            id=rpc_id,
            result=TaskStatusUpdate(
                id=task_id, sessionId=session_id, status=status, message=message,
            ),
        ).model_dump(mode="json", exclude_none=True)
