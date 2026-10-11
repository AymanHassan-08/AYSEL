"""Agent Card discovery endpoint tests."""
from __future__ import annotations

from schemas.a2a import AgentCard


async def test_agent_card_returns_valid_card(client):
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = AgentCard.model_validate(resp.json())
    assert card.name == "Aysel"
    assert card.capabilities.streaming is True
    assert card.capabilities.pushNotifications is False
    assert card.capabilities.stateTransitionHistory is True
    assert {s.id for s in card.skills} == {
        "market-gap-analysis",
        "global-financing-systems",
        "web-search",
        "url-content-analysis",
    }


async def test_agent_card_description_is_a_summary(client):
    """Fix check: description should be a one-line capability summary,
    not the long root-agent pitch paragraph."""
    resp = await client.get("/.well-known/agent.json")
    description = resp.json()["description"]
    assert "market gap" in description.lower()
    assert len(description) < 400
