"""URL context sub-agent definition (aysel__url_context_agent)."""
from __future__ import annotations

from typing import Any

URL_AGENT_NAME = "aysel_url_context_agent"
URL_AGENT_INSTRUCTION = (
    "Use URL context retrieval to fetch content from provided URLs and extract "
    "the key findings relevant to the research question."
)


def build_url_agent(model: Any) -> Any:
    from google.adk.agents import LlmAgent
    from google.adk.tools import url_context

    return LlmAgent(
        name=URL_AGENT_NAME,
        model=model,
        description="Retrieves and analyzes content from provided URLs.",
        instruction=URL_AGENT_INSTRUCTION,
        tools=[url_context],
    )
