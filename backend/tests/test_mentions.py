# ruff: noqa

from uuid import uuid4

from app.models.agents import Agent
from app.services.mentions import extract_mentions, matches_agent_mention


def _agent(name: str, *, is_board_lead: bool = False) -> Agent:
    return Agent(name=name, gateway_id=uuid4(), is_board_lead=is_board_lead)


def test_extract_mentions_parses_tokens():
    assert extract_mentions("hi @Alex and @bob-2") == {"alex", "bob-2"}


def test_matches_agent_mention_matches_first_name():
    agent = _agent("Alice Cooper")
    assert matches_agent_mention(agent, {"alice"}) is True
    assert matches_agent_mention(agent, {"cooper"}) is False


def test_matches_agent_mention_no_mentions_is_false():
    agent = _agent("Alice")
    assert matches_agent_mention(agent, set()) is False


def test_matches_agent_mention_empty_agent_name_is_false():
    agent = _agent("   ")
    assert matches_agent_mention(agent, {"alice"}) is False


def test_matches_agent_mention_matches_full_normalized_name():
    agent = _agent("Alice Cooper")
    assert matches_agent_mention(agent, {"alice cooper"}) is True


def test_matches_agent_mention_supports_reserved_lead_shortcut():
    lead = _agent("Riya", is_board_lead=True)
    other = _agent("Lead", is_board_lead=False)
    assert matches_agent_mention(lead, {"lead"}) is True
    assert matches_agent_mention(other, {"lead"}) is False
