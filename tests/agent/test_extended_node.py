"""Tests for the Extended Predictor node."""
from unittest.mock import MagicMock

import pytest

from agent.nodes.extended import make_extended_node
from agent.state import (
    Challenge,
    ExtendedPrediction,
    FinalPrediction,
    FirstTryPrediction,
    FirstTryScorerCandidate,
)


def _final():
    return FinalPrediction(
        predicted_winner="Panthers",
        predicted_margin=10,
        confidence="MEDIUM",
        accepted_primary=True,
        judge_rationale="Primary case held up.",
        key_factors=["Home advantage", "Form"],
        reasoning="Panthers win narrowly.",
    )


def _challenge():
    return Challenge(
        counter_winner="Broncos",
        counter_margin=4,
        challenge_strength="MODERATE",
        key_counterpoints=["Away form", "H2H"],
        challenge_reasoning="Broncos could upset.",
    )


def _state():
    return {
        "match_id": "round-12-panthers-v-broncos",
        "round_number": 12,
        "season": 2026,
        "match_context": {"team_sheets": {"home": [], "away": []}},
        "final_prediction": _final(),
        "challenge": _challenge(),
    }


def _make_llm():
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = ExtendedPrediction(
        first_try_scorer=FirstTryPrediction(candidates=[
            FirstTryScorerCandidate(player_name="Luai", team="Panthers", position="five-eighth", probability=0.15, rationale="Off a scrum"),
            FirstTryScorerCandidate(player_name="To'o", team="Panthers", position="winger", probability=0.12, rationale="Dangerous edge"),
            FirstTryScorerCandidate(player_name="Staggs", team="Broncos", position="centre", probability=0.10, rationale="Physical carry"),
        ]),
        margin_bracket="6-12",
        key_player_to_watch="Luai — controls pace from the ruck",
        upset_probability=0.28,
    )
    return llm


def test_extended_returns_candidates():
    node = make_extended_node(llm=_make_llm())
    result = node(_state())
    assert len(result["extended"].first_try_scorer.candidates) == 3


def test_extended_margin_bracket_valid():
    node = make_extended_node(llm=_make_llm())
    result = node(_state())
    assert result["extended"].margin_bracket in ("1-5", "6-12", "13-20", "21+")


def test_extended_upset_probability_in_range():
    node = make_extended_node(llm=_make_llm())
    result = node(_state())
    prob = result["extended"].upset_probability
    assert 0.0 <= prob <= 1.0


def test_extended_key_player_non_empty():
    node = make_extended_node(llm=_make_llm())
    result = node(_state())
    assert len(result["extended"].key_player_to_watch) > 0
