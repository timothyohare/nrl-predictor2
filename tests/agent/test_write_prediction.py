"""Regression tests for the DynamoDB write path.

The agent ran fine end-to-end but `write_prediction` crashed on `put_item` with
"Float types are not supported" — `first_try_candidates[*].probability` is a float,
which the boto3 DynamoDB resource client rejects. The full-graph integration test
never exercised the write, so the bug shipped and discarded every live run.

These tests call the write path against moto with float-bearing data, so the
serialisation regression cannot come back silently.
"""
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from agent.lambda_handler import write_prediction, write_trace
from agent.state import (
    Challenge,
    ExtendedPrediction,
    FinalPrediction,
    FirstTryPrediction,
    FirstTryScorerCandidate,
    PrimaryPrediction,
)

PREDICTIONS_TABLE = "predictions"
AGENT_TRACES_TABLE = "agent_traces"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("PREDICTIONS_TABLE", PREDICTIONS_TABLE)
    monkeypatch.setenv("AGENT_TRACES_TABLE", AGENT_TRACES_TABLE)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        for name in (PREDICTIONS_TABLE, AGENT_TRACES_TABLE):
            ddb.create_table(
                TableName=name,
                KeySchema=[
                    {"AttributeName": "matchId", "KeyType": "HASH"},
                    {"AttributeName": "generatedAt", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "matchId", "AttributeType": "S"},
                    {"AttributeName": "generatedAt", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        yield ddb


def _result_state() -> dict:
    """A finished graph state with floats nested in the extended prediction."""
    return {
        "difficulty": "CONTESTED",
        "difficulty_rationale": "Close on form.",
        "primary_prediction": PrimaryPrediction(
            predicted_winner="Panthers", predicted_margin=8, confidence="MEDIUM",
            key_factors=["Home", "Form"], reasoning="Panthers at home.",
        ),
        "challenge": Challenge(
            counter_winner="Broncos", counter_margin=4, challenge_strength="MODERATE",
            key_counterpoints=["Away form", "H2H"], challenge_reasoning="Broncos live.",
        ),
        "final_prediction": FinalPrediction(
            predicted_winner="Panthers", predicted_margin=6, confidence="MEDIUM",
            accepted_primary=True, judge_rationale="Primary held.",
            key_factors=["Home", "Form"], reasoning="Narrow Panthers win.",
        ),
        "extended": ExtendedPrediction(
            first_try_scorer=FirstTryPrediction(candidates=[
                FirstTryScorerCandidate(
                    player_name="Luai", team="Panthers", position="five-eighth",
                    probability=0.15, rationale="Off a scrum",
                ),
                FirstTryScorerCandidate(
                    player_name="To'o", team="Panthers", position="winger",
                    probability=0.125, rationale="Edge overlap",
                ),
            ]),
            margin_bracket="6-12",
            key_player_to_watch="Luai — playmaker",
            upset_probability=0.28,
        ),
    }


def test_write_prediction_persists_float_candidates(aws_env):
    """The exact crash: nested float probabilities must serialise, not raise."""
    write_prediction("round-15-panthers-v-broncos", 15, 2026, _result_state())

    table = aws_env.Table(PREDICTIONS_TABLE)
    items = table.scan()["Items"]
    assert len(items) == 1
    item = items[0]

    assert item["matchId"] == "round-15-panthers-v-broncos"
    assert item["prompt_version"] == "v2.0"
    assert item["predicted_winner"] == "panthers"  # canonical slug
    assert item["challenge_strength"] == "MODERATE"

    candidates = item["first_try_candidates"]
    assert len(candidates) == 2
    # The value that used to crash the write — now a round-tripped Decimal.
    assert candidates[0]["probability"] == Decimal("0.15")
    assert isinstance(candidates[0]["probability"], Decimal)
    assert all(not isinstance(c["probability"], float) for c in candidates)


def test_write_trace_persists_float_tool_inputs(aws_env):
    """trace_entries[*].input tool args can also carry floats."""
    state = {
        "difficulty": "CONTESTED",
        "primary_model": "haiku",
        "agent_trace": [
            {"node": "primary", "tool": "get_recent_form",
             "input": {"team": "Panthers", "decay": 0.85}, "output": "rising"},
        ],
    }
    write_trace("round-15-panthers-v-broncos", "2026-06-14T00:00:00+00:00", state)

    item = aws_env.Table(AGENT_TRACES_TABLE).scan()["Items"][0]
    assert item["primary_model"] == "haiku"
    assert item["trace_entries"][0]["input"]["decay"] == Decimal("0.85")


def test_write_prediction_without_extended(aws_env):
    """Extended is optional — the core write must still succeed."""
    state = _result_state()
    state.pop("extended")
    write_prediction("round-15-storm-v-eels", 15, 2026, state)

    item = aws_env.Table(PREDICTIONS_TABLE).scan()["Items"][0]
    assert "first_try_candidates" not in item
    assert item["predicted_winner"] == "panthers"  # canonical slug
