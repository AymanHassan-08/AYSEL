"""Search sub-agent definition (aysel__google_search_agent).

NOTE: verify the google-adk tool import path for your pinned version —
Google Search tooling moved between ADK releases (e.g. `google.adk.tools`
built-ins vs. `google.adk.tools.google_search`). The definition below uses
the AgentTool wiring from the design doc.
"""
from __future__ import annotations

from typing import Any

SEARCH_AGENT_NAME = "aysel_google_search_agent"
SEARCH_AGENT_INSTRUCTION = (
    "Use Google Search to find current, relevant information on the web. "
    "Prefer authoritative and recent sources, cite them, and report findings concisely."
)


def build_search_agent(model: Any) -> Any:
    from google.adk.agents import LlmAgent

    return LlmAgent(
        name=SEARCH_AGENT_NAME,
        model=model,
        description="Finds real-time information on the web via Google Search.",
        instruction=SEARCH_AGENT_INSTRUCTION,
        tools=[],
    )
