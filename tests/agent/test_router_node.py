"""Tests for the Router node."""
from unittest.mock import MagicMock


from agent.nodes.router import make_router_node
from agent.state import RouterOutput
from scrapers.shared.constants import HAIKU_MODEL, SONNET_MODEL


def _make_llm(output: RouterOutput):
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = output
    return llm


def _state(home="Panthers", away="Broncos", is_finals=False, spine_injuries=None):
    return {
        "match_id": f"round-12-{home.lower()}-v-{away.lower()}",
        "round_number": 12,
        "season": 2026,
        "match_context": {
            "home_team": home,
            "away_team": away,
            "venue": "BlueBet Stadium",
            "is_finals": is_finals,
            "home_ladder_pos": 1,
            "away_ladder_pos": 8,
            "spine_injuries": spine_injuries or [],
        },
    }


def test_router_returns_easy():
    llm = _make_llm(RouterOutput(difficulty="EASY", rationale="Dominant home side", primary_model=HAIKU_MODEL, challenger_model=SONNET_MODEL))
    node = make_router_node(llm=llm)
    result = node(_state())
    assert result["difficulty"] == "EASY"
    assert result["primary_model"] == HAIKU_MODEL
    assert result["challenger_model"] == SONNET_MODEL


def test_router_returns_complex():
    llm = _make_llm(RouterOutput(difficulty="COMPLEX", rationale="Finals match", primary_model=SONNET_MODEL, challenger_model=SONNET_MODEL))
    node = make_router_node(llm=llm)
    result = node(_state(is_finals=True))
    assert result["difficulty"] == "COMPLEX"
    assert result["primary_model"] == SONNET_MODEL


def test_router_stores_rationale():
    llm = _make_llm(RouterOutput(difficulty="CONTESTED", rationale="Close H2H", primary_model=SONNET_MODEL, challenger_model=SONNET_MODEL))
    node = make_router_node(llm=llm)
    result = node(_state())
    assert result["difficulty_rationale"] == "Close H2H"


def test_router_calls_with_structured_output():
    llm = _make_llm(RouterOutput(difficulty="EASY", rationale="x", primary_model=HAIKU_MODEL, challenger_model=SONNET_MODEL))
    node = make_router_node(llm=llm)
    node(_state())
    llm.with_structured_output.assert_called_once_with(RouterOutput)
