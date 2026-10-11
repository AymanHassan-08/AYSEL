"""FastAPI app factory with lifespan-managed DB, event bus, and handler."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from api.config import settings
from api.routes import router
from db.connection import dispose_db, init_db
from services.a2a_handler import A2AHandler
from services.stream_manager import event_bus


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    fatal, warnings = settings.production_problems()
    if settings.is_production and fatal:
        raise RuntimeError(
            "Refusing to start in production with fatal config problems: "
            + "; ".join(fatal)
        )
    for w in warnings:
        logging.getLogger(__name__).warning("Production config warning: %s", w)
    await init_db()
    await event_bus.connect()
    existing = getattr(app.state, "a2a_handler", None)
    if existing is None:
        app.state.a2a_handler = A2AHandler()
    try:
        yield
    finally:
        await event_bus.disconnect()
        await dispose_db()


def create_app(handler: A2AHandler | None = None) -> FastAPI:
    """Build the app. Pass `handler` to inject a test runner."""
    app = FastAPI(
        title="Aysel A2A Endpoint",
        version="0.1.0",
        description=(
            "Multi-agent research system (market gap analysis, global financing) "
            "exposed via the Google Agent-to-Agent protocol."
        ),
        lifespan=lifespan,
    )
    if handler is not None:
        app.state.a2a_handler = handler  # set early; lifespan re-set is harmless
    app.include_router(router)
    return app
