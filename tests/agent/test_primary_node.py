"""Tests for the Primary Predictor node."""
import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from agent.nodes.primary import make_primary_node
from agent.state import PrimaryPrediction


def _make_final_ai_message() -> AIMessage:
    """Simulate an AIMessage with no tool calls (final answer)."""
    payload = json.dumps({
        "predicted_winner": "Panthers",
        "predicted_margin": 12,
        "confidence": "HIGH",
        "key_factors": ["Home ground advantage", "Superior form"],
        "reasoning": "Panthers have been dominant at BlueBet all season and are 5 from last 5.",
    })
    msg = AIMessage(content=payload)
    msg.tool_calls = []
    return msg


def _make_state():
    return {
        "match_id": "round-12-panthers-v-broncos",
        "round_number": 12,
        "season": 2026,
        "primary_model": "claude-haiku-4-5-20251001",
        "match_context": {"home_team": "Panthers", "away_team": "Broncos"},
        "agent_trace": [],
    }


def _make_prediction():
    return PrimaryPrediction(
        predicted_winner="Panthers",
        predicted_margin=12,
        confidence="HIGH",
        key_factors=["Home ground advantage", "Superior form"],
        reasoning="Panthers have been dominant at BlueBet all season and are 5 from last 5.",
    )


def test_primary_returns_valid_prediction():
    llm = MagicMock()
    llm.bind_tools.return_value.invoke.return_value = _make_final_ai_message()
    llm.with_structured_output.return_value.invoke.return_value = _make_prediction()
    node = make_primary_node(llm=llm)
    result = node(_make_state())
    assert isinstance(result["primary_prediction"], PrimaryPrediction)
    assert result["primary_prediction"].predicted_winner == "Panthers"
    assert result["primary_prediction"].confidence == "HIGH"


def test_primary_preserves_trace():
    llm = MagicMock()
    llm.bind_tools.return_value.invoke.return_value = _make_final_ai_message()
    llm.with_structured_output.return_value.invoke.return_value = _make_prediction()
    node = make_primary_node(llm=llm)
    result = node(_make_state())
    assert isinstance(result["agent_trace"], list)


def test_primary_uses_router_model():
    """Primary should use whichever model the router selected."""
    llm = MagicMock()
    llm.bind_tools.return_value.invoke.return_value = _make_final_ai_message()
    llm.with_structured_output.return_value.invoke.return_value = _make_prediction()
    node = make_primary_node(llm=llm)
    state = _make_state()
    state["primary_model"] = "claude-sonnet-4-6"
    node(state)
    llm.bind_tools.assert_called_once()


def test_primary_raises_on_extraction_failure(monkeypatch):
    """Primary should propagate if structured output extraction fails."""
    llm = MagicMock()
    llm.bind_tools.return_value.invoke.return_value = _make_final_ai_message()
    llm.with_structured_output.return_value.invoke.side_effect = ValueError("Output parsing failed")
    node = make_primary_node(llm=llm)
    with pytest.raises(Exception):
        node(_make_state())
