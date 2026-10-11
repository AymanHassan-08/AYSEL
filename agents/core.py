"""Google ADK agent definitions.

Imports are lazy and defensive: the scaffold runs its tests without the ADK
installed, and ADK tool module names have shifted across 1.x releases —
verify the exact import paths against your pinned google-adk version before
deploying.

Also fixed vs. the design doc: the root agent is named `aysel_root_agent`
(no trailing underscore), so it doesn't leak an odd `Aysel_` into logs,
metadata, and A2A responses.
"""
from services.agent_runner import AdkAgentRunner, AgentEvent, AgentRunner, ROOT_INSTRUCTION

__all__ = ["AdkAgentRunner", "AgentEvent", "AgentRunner", "ROOT_INSTRUCTION"]
