"""Event bus for SSE fan-out.

Fix vs. the original design doc: StreamManager kept in-process asyncio queues
in the web process, while task execution ran in the Celery worker process —
so `publish()` from the worker could never reach the web process's queues.
This bus has two backends:

- Redis pub/sub when REDIS_URL is reachable (multi-process safe: a Celery
  worker publishes, every web process holding an SSE subscriber receives).
- In-process asyncio queues as a dev/test fallback (single process only).

`register()` separates subscription setup from iteration, so the caller can
subscribe BEFORE triggering execution — fixing the subscribe/run race from
the original design.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, AsyncIterator, Optional

from api.config import settings
from schemas.a2a import TERMINAL_STATES, TaskState

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "a2a:events"


class Subscription:
    """A registered subscriber for one task's events."""

    def __init__(self, bus: "EventBus", task_id: str, queue: asyncio.Queue,
                 pump: Optional[asyncio.Task] = None,
                 pubsub: Any = None, timeout: float = 300.0) -> None:
        self.bus = bus
        self.task_id = task_id
        self.queue = queue
        self.pump = pump
        self.pubsub = pubsub
        self.timeout = timeout

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield events until a terminal status arrives or timeout hits.

        Heartbeats are yielded periodically so proxies keep the connection
        open. Event shape: {"event_type": "status"|"artifact"|"heartbeat",
                            "payload": <JSON-RPC dict>}.
        """
        while True:
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=self.timeout)
            except asyncio.TimeoutError:
                yield {"event_type": "heartbeat", "payload": None}
                continue
            yield event
            if self._is_terminal(event):
                return

    @staticmethod
    def _is_terminal(event: dict[str, Any]) -> bool:
        if event.get("event_type") != "status":
            return False
        payload = event.get("payload") or {}
        status = (payload.get("result") or {}).get("status")
        try:
            return TaskState(status) in TERMINAL_STATES
        except ValueError:
            return False

    async def close(self) -> None:
        if self.pump is not None:
            self.pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.pump
        if self.pubsub is not None:
            with contextlib.suppress(Exception):
                await self.pubsub.unsubscribe(self.bus._channel(self.task_id))
                await self.pubsub.aclose()
        else:
            subscribers = self.bus._local_queues.get(self.task_id, [])
            if self.queue in subscribers:
                subscribers.remove(self.queue)


class EventBus:
    def __init__(self) -> None:
        self._redis: Optional[Any] = None
        self._local_queues: dict[str, list[asyncio.Queue]] = {}

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        """Try Redis; silently fall back to in-process queues if unreachable."""
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(settings.redis_url)
            await self._redis.ping()
            logger.info("EventBus: Redis connected (%s)", settings.redis_url)
        except Exception as exc:
            logger.warning(
                "EventBus: Redis unavailable (%s); using in-process queues", exc
            )
            self._redis = None

    async def disconnect(self) -> None:
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.aclose()
            self._redis = None

    # -- publish -----------------------------------------------------------

    def _channel(self, task_id: str) -> str:
        return f"{CHANNEL_PREFIX}:{task_id}"

    async def publish(self, task_id: str, event_type: str, payload: Any) -> None:
        event = {"event_type": event_type, "payload": payload}
        if self._redis is not None:
            await self._redis.publish(self._channel(task_id), json.dumps(event, default=str))
            return
        for queue in self._local_queues.get(task_id, []):
            await queue.put(event)

    # -- subscribe ---------------------------------------------------------

    async def register(self, task_id: str, timeout: Optional[float] = None) -> Subscription:
        """Register a subscriber NOW (before execution starts). Returns a
        Subscription whose `events()` iterator streams until terminal state."""
        timeout = timeout or float(settings.max_task_timeout)
        queue: asyncio.Queue = asyncio.Queue()

        if self._redis is not None:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(self._channel(task_id))
            pump = asyncio.create_task(self._pump_redis(pubsub, queue))
            return Subscription(self, task_id, queue, pump=pump, pubsub=pubsub, timeout=timeout)

        self._local_queues.setdefault(task_id, []).append(queue)
        return Subscription(self, task_id, queue, timeout=timeout)

    async def _pump_redis(self, pubsub: Any, queue: asyncio.Queue) -> None:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                event = json.loads(message["data"])
            except Exception:
                continue
            await queue.put(event)


# Singleton shared by the web app and (optionally) the Celery worker.
event_bus = EventBus()
