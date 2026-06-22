"""Scorer regression: missing result must raise ResultNotReady, not IndexError (which
500'd the scoring lambda on 2026-06-21), and slug-vs-slug winner comparison must hold."""
import boto3
import pytest
from moto import mock_aws

from scoring.scorer import ResultNotReady, score_prediction

PRED, RES = "predictions", "results"
MID = "round-16-roosters-v-sharks"


@pytest.fixture
def tables():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        for name, sk in [(PRED, "generatedAt"), (RES, "scoredAt")]:
            ddb.create_table(
                TableName=name,
                KeySchema=[{"AttributeName": "matchId", "KeyType": "HASH"},
                           {"AttributeName": sk, "KeyType": "RANGE"}],
                AttributeDefinitions=[{"AttributeName": "matchId", "AttributeType": "S"},
                                      {"AttributeName": sk, "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        yield ddb.Table(PRED), ddb.Table(RES)


def _seed_pred(t, winner):
    t.put_item(Item={"matchId": MID, "generatedAt": "2026-06-16T20:00:00Z",
                     "predicted_winner": winner, "predicted_margin": 6,
                     "confidence": "MEDIUM", "status": "OK"})


def test_result_not_ready_raises_not_indexerror(tables):
    pred, res = tables
    _seed_pred(pred, "roosters")
    with pytest.raises(ResultNotReady):
        score_prediction(MID, res, pred)


def test_scores_slug_vs_slug(tables):
    pred, res = tables
    _seed_pred(pred, "Sydney Roosters")  # full name from the model
    res.put_item(Item={"matchId": MID, "scoredAt": "2026-06-16T22:00:00Z",
                       "homeTeam": "roosters", "awayTeam": "sharks", "winner": "roosters",
                       "homeScore": 27, "awayScore": 8, "margin": 19, "matchState": "FullTime"})
    scored = score_prediction(MID, res, pred)
    assert scored.correct_pick is True  # "Sydney Roosters" -> roosters == winner roosters


def test_scores_last_prediction_before_kickoff(tables):
    """A post-kickoff regeneration must NOT be the one scored — pick the last pre-kickoff pred."""
    pred, res = tables
    ko = "2026-06-16T20:00:00Z"
    # pre-kickoff forecast: sharks (wrong); post-kickoff hindsight: roosters (right)
    pred.put_item(Item={"matchId": MID, "generatedAt": "2026-06-14T09:00:00Z",
                        "predicted_winner": "sharks", "predicted_margin": 4,
                        "confidence": "MEDIUM", "status": "OK"})
    pred.put_item(Item={"matchId": MID, "generatedAt": "2026-06-17T09:00:00Z",
                        "predicted_winner": "roosters", "predicted_margin": 18,
                        "confidence": "HIGH", "status": "OK"})
    res.put_item(Item={"matchId": MID, "scoredAt": "2026-06-16T22:00:00Z",
                       "homeTeam": "roosters", "awayTeam": "sharks", "winner": "roosters",
                       "homeScore": 27, "awayScore": 8, "margin": 19, "matchState": "FullTime"})
    scored = score_prediction(MID, res, pred, kickoff=ko)
    assert scored.correct_pick is False  # scored the pre-KO 'sharks' pick, not the hindsight one
