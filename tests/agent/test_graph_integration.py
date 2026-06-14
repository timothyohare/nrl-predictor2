"""Integration test — full graph run with all LLMs mocked."""
import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from agent.graph import build_graph
from agent.state import (
    Challenge,
    ExtendedPrediction,
    FinalPrediction,
    FirstTryPrediction,
    FirstTryScorerCandidate,
    RouterOutput,
)
from scrapers.shared.constants import HAIKU_MODEL, SONNET_MODEL


def _structured_llm(return_value):
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = return_value
    return llm


def _tool_llm(json_payload: dict):
    """LLM that produces a JSON text response (no tool calls) for the Primary node."""
    msg = AIMessage(content=json.dumps(json_payload))
    msg.tool_calls = []
    llm = MagicMock()
    llm.bind_tools.return_value.invoke.return_value = msg
    return llm


@pytest.fixture
def full_graph():
    router_llm = _structured_llm(RouterOutput(
        difficulty="CONTESTED",
        rationale="Close match",
        primary_model=HAIKU_MODEL,
        challenger_model=SONNET_MODEL,
    ))
    primary_llm = _tool_llm({
        "predicted_winner": "Panthers",
        "predicted_margin": 8,
        "confidence": "MEDIUM",
        "key_factors": ["Home ground", "Better form"],
        "reasoning": "Panthers win at home.",
    })
    challenger_llm = _structured_llm(Challenge(
        counter_winner="Broncos",
        counter_margin=4,
        challenge_strength="MODERATE",
        key_counterpoints=["Away form", "H2H"],
        challenge_reasoning="Broncos could upset.",
    ))
    judge_llm = _structured_llm(FinalPrediction(
        predicted_winner="Panthers",
        predicted_margin=6,
        confidence="MEDIUM",
        accepted_primary=True,
        judge_rationale="Primary held up against moderate challenge.",
        key_factors=["Home ground", "Form"],
        reasoning="Panthers win narrowly.",
    ))
    extended_llm = _structured_llm(ExtendedPrediction(
        first_try_scorer=FirstTryPrediction(candidates=[
            FirstTryScorerCandidate(player_name="Luai", team="Panthers", position="five-eighth", probability=0.15, rationale="Off a scrum"),
        ]),
        margin_bracket="6-12",
        key_player_to_watch="Luai — key playmaker",
        upset_probability=0.28,
    ))
    return build_graph(
        router_llm=router_llm,
        primary_llm=primary_llm,
        challenger_llm=challenger_llm,
        judge_llm=judge_llm,
        extended_llm=extended_llm,
    )


def test_full_graph_runs(full_graph):
    state = {
        "match_id": "round-12-panthers-v-broncos",
        "round_number": 12,
        "season": 2026,
        "match_context": {"home_team": "Panthers", "away_team": "Broncos", "venue": "BlueBet Stadium", "is_finals": False, "home_ladder_pos": 1, "away_ladder_pos": 8, "spine_injuries": []},
        "agent_trace": [],
    }
    result = full_graph.invoke(state)
    assert result["final_prediction"].predicted_winner == "Panthers"
    assert result["final_prediction"].confidence == "MEDIUM"
    assert result["extended"].margin_bracket == "6-12"
    assert result["difficulty"] == "CONTESTED"
    assert result["challenge"].challenge_strength == "MODERATE"


def test_full_graph_state_keys(full_graph):
    state = {
        "match_id": "round-12-panthers-v-broncos",
        "round_number": 12,
        "season": 2026,
        "match_context": {},
        "agent_trace": [],
    }
    result = full_graph.invoke(state)
    for key in ("difficulty", "primary_prediction", "challenge", "final_prediction", "extended"):
        assert key in result, f"Missing key: {key}"
