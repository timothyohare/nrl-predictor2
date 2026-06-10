"""Tests for the Synthesis Judge node."""
from unittest.mock import MagicMock

import pytest

from agent.nodes.judge import make_judge_node
from agent.state import Challenge, FinalPrediction, PrimaryPrediction


def _primary(winner="Panthers", margin=14, confidence="HIGH"):
    return PrimaryPrediction(
        predicted_winner=winner,
        predicted_margin=margin,
        confidence=confidence,
        key_factors=["Home advantage", "Form"],
        reasoning="Panthers are the better team.",
    )


def _challenge(strength="MODERATE", counter="Broncos"):
    return Challenge(
        counter_winner=counter,
        counter_margin=4,
        challenge_strength=strength,
        key_counterpoints=["Away form", "H2H"],
        challenge_reasoning="Broncos have upset potential.",
    )


def _state(primary=None, challenge=None):
    return {
        "match_id": "round-12-panthers-v-broncos",
        "round_number": 12,
        "season": 2026,
        "difficulty": "CONTESTED",
        "match_context": {"home_team": "Panthers", "away_team": "Broncos"},
        "primary_prediction": primary or _primary(),
        "challenge": challenge or _challenge(),
    }


def _make_llm(winner="Panthers", margin=10, confidence="MEDIUM", accepted=True):
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = FinalPrediction(
        predicted_winner=winner,
        predicted_margin=margin,
        confidence=confidence,
        accepted_primary=accepted,
        judge_rationale="Primary case was more compelling despite MODERATE challenge.",
        key_factors=["Home advantage", "Better form"],
        reasoning="Panthers win on balance of evidence.",
    )
    return llm


def test_judge_accepts_primary_on_weak_challenge():
    node = make_judge_node(llm=_make_llm(accepted=True))
    result = node(_state(challenge=_challenge(strength="WEAK")))
    assert result["final_prediction"].accepted_primary is True


def test_judge_can_flip_on_strong_challenge():
    node = make_judge_node(llm=_make_llm(winner="Broncos", accepted=False))
    result = node(_state(challenge=_challenge(strength="STRONG", counter="Broncos")))
    assert result["final_prediction"].accepted_primary is False
    assert result["final_prediction"].predicted_winner == "Broncos"


def test_judge_produces_valid_final_prediction():
    node = make_judge_node(llm=_make_llm())
    result = node(_state())
    pred = result["final_prediction"]
    assert isinstance(pred, FinalPrediction)
    assert pred.confidence in ("LOW", "MEDIUM", "HIGH")
    assert len(pred.key_factors) >= 2


def test_judge_includes_rationale():
    node = make_judge_node(llm=_make_llm())
    result = node(_state())
    assert len(result["final_prediction"].judge_rationale) > 10
