"""Tests for the Challenger node."""
from unittest.mock import MagicMock

import pytest

from agent.nodes.challenger import make_challenger_node
from agent.state import Challenge, PrimaryPrediction


def _primary():
    return PrimaryPrediction(
        predicted_winner="Panthers",
        predicted_margin=12,
        confidence="HIGH",
        key_factors=["Home advantage", "Form"],
        reasoning="Panthers dominant at home.",
    )


def _state(challenge_strength="MODERATE"):
    return {
        "match_id": "round-12-panthers-v-broncos",
        "round_number": 12,
        "season": 2026,
        "match_context": {"home_team": "Panthers", "away_team": "Broncos"},
        "primary_prediction": _primary(),
    }


def _make_llm(strength="MODERATE", counter="Broncos"):
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = Challenge(
        counter_winner=counter,
        counter_margin=6,
        challenge_strength=strength,
        key_counterpoints=["Travel advantage", "H2H record"],
        challenge_reasoning="Broncos have won 3 of last 5 here.",
    )
    return llm


def test_challenger_always_produces_counter():
    node = make_challenger_node(llm=_make_llm())
    result = node(_state())
    assert result["challenge"].counter_winner == "Broncos"


def test_challenger_can_return_weak():
    node = make_challenger_node(llm=_make_llm(strength="WEAK"))
    result = node(_state())
    assert result["challenge"].challenge_strength == "WEAK"


def test_challenger_can_return_strong():
    node = make_challenger_node(llm=_make_llm(strength="STRONG"))
    result = node(_state())
    assert result["challenge"].challenge_strength == "STRONG"


def test_challenger_counter_winner_differs():
    """The challenger should argue for the OTHER team."""
    node = make_challenger_node(llm=_make_llm(counter="Broncos"))
    result = node(_state())
    primary = _primary()
    assert result["challenge"].counter_winner != primary.predicted_winner
