"""Internal agent metadata schemas (not part of the wire protocol)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentRunResult(BaseModel):
    """Normalized output of one agent execution, produced by AgentRunner."""

    final_message: Optional[str] = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status_reason: Optional[str] = None  # e.g. "input-required" trigger
