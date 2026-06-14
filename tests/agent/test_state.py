"""Tests for Pydantic models in agent/state.py."""
import pytest
from pydantic import ValidationError

from agent.state import (
    Challenge,
    ExtendedPrediction,
    FinalPrediction,
    FirstTryPrediction,
    FirstTryScorerCandidate,
    PrimaryPrediction,
    RouterOutput,
)


def test_router_output_valid():
    r = RouterOutput(
        difficulty="EASY",
        rationale="Large spread",
        primary_model="claude-haiku-4-5-20251001",
        challenger_model="claude-sonnet-4-6",
    )
    assert r.difficulty == "EASY"


def test_router_output_invalid_difficulty():
    with pytest.raises(ValidationError):
        RouterOutput(difficulty="HARD", rationale="x", primary_model="m", challenger_model="m")


def test_primary_prediction_valid():
    p = PrimaryPrediction(
        predicted_winner="Panthers",
        predicted_margin=10,
        confidence="HIGH",
        key_factors=["Home ground", "Form"],
        reasoning="Panthers are stronger.",
    )
    assert p.predicted_winner == "Panthers"


def test_primary_prediction_requires_two_factors():
    with pytest.raises(ValidationError):
        PrimaryPrediction(
            predicted_winner="Panthers",
            predicted_margin=10,
            confidence="HIGH",
            key_factors=["only one"],
            reasoning="x",
        )


def test_challenge_valid():
    c = Challenge(
        counter_winner="Broncos",
        counter_margin=4,
        challenge_strength="MODERATE",
        key_counterpoints=["Travel fatigue", "H2H record"],
        challenge_reasoning="Broncos have better road form.",
    )
    assert c.challenge_strength == "MODERATE"


def test_final_prediction_valid():
    f = FinalPrediction(
        predicted_winner="Panthers",
        predicted_margin=8,
        confidence="MEDIUM",
        accepted_primary=True,
        judge_rationale="Primary case was stronger.",
        key_factors=["Home ground", "Form"],
        reasoning="Panthers to win.",
    )
    assert f.accepted_primary is True


def test_extended_prediction_margin_bracket():
    e = ExtendedPrediction(
        first_try_scorer=FirstTryPrediction(candidates=[
            FirstTryScorerCandidate(player_name="Luai", team="Panthers", position="five-eighth", probability=0.12, rationale="Off the back of a scrum")
        ]),
        margin_bracket="6-12",
        key_player_to_watch="Luai — controls the game from dummy half",
        upset_probability=0.2,
    )
    assert e.margin_bracket == "6-12"


def test_extended_prediction_invalid_bracket():
    with pytest.raises(ValidationError):
        ExtendedPrediction(
            first_try_scorer=FirstTryPrediction(candidates=[
                FirstTryScorerCandidate(player_name="x", team="y", position="z", probability=0.1, rationale="r")
            ]),
            margin_bracket="7-15",
            key_player_to_watch="x",
            upset_probability=0.1,
        )


def test_upset_probability_clamped():
    with pytest.raises(ValidationError):
        ExtendedPrediction(
            first_try_scorer=FirstTryPrediction(candidates=[
                FirstTryScorerCandidate(player_name="x", team="y", position="z", probability=0.1, rationale="r")
            ]),
            margin_bracket="1-5",
            key_player_to_watch="x",
            upset_probability=1.5,
        )


# ── first_try_scorer coercion (Haiku emits a stringified / bare list) ─────────

_CANDS = [
    {"player_name": "Sione", "team": "Warriors", "position": "winger",
     "probability": 0.18, "rationale": "Edge speed"},
    {"player_name": "Nicoll-Klokstad", "team": "Warriors", "position": "fullback",
     "probability": 0.1, "rationale": "Support lines"},
]


def _extended(first_try):
    return ExtendedPrediction(
        first_try_scorer=first_try,
        margin_bracket="6-12",
        key_player_to_watch="x",
        upset_probability=0.2,
    )


def test_first_try_scorer_accepts_json_string():
    """The exact prod failure: a JSON string of a candidate list."""
    import json
    e = _extended(json.dumps(_CANDS))
    assert [c.player_name for c in e.first_try_scorer.candidates] == ["Sione", "Nicoll-Klokstad"]


def test_first_try_scorer_accepts_bare_list():
    e = _extended(_CANDS)
    assert len(e.first_try_scorer.candidates) == 2


def test_first_try_scorer_clamps_to_three():
    many = [dict(_CANDS[0], player_name=f"P{i}") for i in range(5)]
    e = _extended(many)
    assert len(e.first_try_scorer.candidates) == 3


def test_first_try_scorer_still_accepts_object():
    e = _extended(FirstTryPrediction(candidates=[FirstTryScorerCandidate(**_CANDS[0])]))
    assert e.first_try_scorer.candidates[0].player_name == "Sione"
