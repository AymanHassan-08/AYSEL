"""Agent execution abstraction.

The real ADK runner imports google-adk lazily so the rest of the service
(including tests) works without the heavy dependency installed. Swap the
runner via app.state / handler injection.

Structure follows the design doc (GlobalGemini client bound to the Vertex AI
"global" location, search + url-context sub-agents as AgentTools of the root).
NOTE: verify `google.adk.*` import paths against the ADK version you pin;
several tool module names shifted across 1.x releases.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Protocol

from schemas.agent import AgentRunResult

logger = logging.getLogger(__name__)

ROOT_INSTRUCTION = (
    "Discuss a critical area of strategic business development. "
    "Understanding market gaps presents significant opportunities for innovation and growth. "
    "A thorough analysis of these untapped areas is paramount for identifying competitive advantages. "
    "Furthermore, a comprehensive understanding of the world's financing systems is essential "
    "for sustainable investment and expansion. Navigate the complexities of global finance with "
    "detailed insight into various funding mechanisms. This knowledge allows for informed "
    "decision-making regarding capital acquisition and allocation. By effectively leveraging both "
    "market gap identification and financial system comprehension, businesses can achieve "
    "remarkable success."
)


class AgentEvent:
    """A streaming event emitted by the runner."""

    def __init__(self, kind: str, **payload: Any) -> None:
        self.kind = kind  # "status" | "artifact" | "result"
        self.payload = payload


class AgentRunner(Protocol):
    async def run(self, user_message: str) -> AgentRunResult: ...

    def run_stream(self, user_message: str) -> AsyncIterator[AgentEvent]: ...


class AdkAgentRunner:
    """Real runner backed by Google ADK. Imports are lazy."""

    def __init__(self, model: str | None = None) -> None:
        from api.config import settings

        self._model_name = model or settings.agent_model
        self._built = False
        self._root: Any = None
        self._runner: Any = None

    def _build(self) -> None:
        if self._built:
            return
        # Late imports: keep module importable without google-adk installed,
        # and give a clear error instead of an import-time crash.
        from google.adk.agents import LlmAgent
        from google.adk.models import Gemini
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import Client

        class GlobalGemini(Gemini):
            @property
            def api_client(self) -> Client:
                return Client(vertexai=True, location="global")

        search_agent = LlmAgent(
            name="aysel_google_search_agent",
            model=GlobalGemini(model=self._model_name),
            description="Finds real-time information on the web via Google Search.",
            instruction=(
                "Use Google Search to find current, relevant information on the web. "
                "Cite sources and report what you found concisely."
            ),
        )
        url_agent = LlmAgent(
            name="aysel_url_context_agent",
            model=GlobalGemini(model=self._model_name),
            description="Retrieves and analyzes content from provided URLs.",
            instruction=(
                "Use URL context retrieval to fetch content from provided URLs and "
                "extract the key findings relevant to the research question."
            ),
        )
        self._root = LlmAgent(
            name="aysel_root_agent",
            model=GlobalGemini(model=self._model_name),
            instruction=ROOT_INSTRUCTION,
            description=(
                "Strategic business development research: market gap identification "
                "and global financing system analysis."
            ),
            sub_agents=[search_agent, url_agent],
        )
        self._service = InMemorySessionService()
        self._built = True

    async def run(self, user_message: str) -> AgentRunResult:
        self._build()
        runner = Runner(
            agent=self._root,
            app_name="aysel",
            session_service=self._service,
        )
        from google.adk.sessions import InMemorySessionService  # noqa: F401

        session = await self._service.create_session(app_name="aysel")
        content = {"role": "user", "parts": [{"text": user_message}]}

        final_text = ""
        async for event in runner.run_async(
            session_id=session.id, user_id="a2a-client", new_message=content
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = "".join(
                    getattr(p, "text", "") or "" for p in event.content.parts
                )
        return AgentRunResult(final_message=final_text or "No response generated.")

    async def run_stream_events(self, user_message: str) -> AsyncIterator[AgentEvent]:
        self._build()
        runner = Runner(
            agent=self._root,
            app_name="aysel",
            session_service=self._service,
        )
        session = await self._service.create_session(app_name="aysel")
        content = {"role": "user", "parts": [{"text": user_message}]}

        final_text = ""
        async for event in runner.run_async(
            session_id=session.id, user_id="a2a-client", new_message=content
        ):
            if event.content and event.content.parts:
                text = "".join(getattr(p, "text", "") or "" for p in event.content.parts)
                if text:
                    yield AgentEvent("status", message=text)
            if event.is_final_response():
                if final_text or text:
                    yield AgentEvent(
                        "result",
                        result=AgentRunResult(final_message=final_text or text),
                    )
                    return
        yield AgentEvent("result", result=AgentRunResult(final_message=final_text or "No response generated."))
