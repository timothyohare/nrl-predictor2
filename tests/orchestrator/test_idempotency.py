"""The orchestrator must be idempotent per (season, round).

A synchronous ``aws lambda invoke`` of the ~73s handler overruns the CLI's 60s read
timeout; botocore retries fire the orchestrator 2-3x and the agent fan-out with it
(observed 2026-06-15: 25 agent starts + 17 duplicate round-16 predictions). A
conditional-write lock keyed on (season, round) lets only the first run in the window
proceed; ``force: true`` overrides it.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

import orchestrator.lambda_handler as oh


def _match(slug="round-16-knights-v-dragons"):
    return SimpleNamespace(
        match_id=slug, round_number=16, home_team="Knights", away_team="Dragons",
        venue="McDonald Jones", kick_off="", match_state="Pre",
        match_centre_url="/draw/nrl-premiership/2026/round-16/knights-v-dragons/",
    )


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    monkeypatch.setenv("RAW_BUCKET", "bucket")
    monkeypatch.setenv("AGENT_FUNCTION_NAME", "agent-fn")
    monkeypatch.setenv("AGENT_INVOKE_STAGGER_SECONDS", "0")  # no real sleeps in tests

    # Avoid all network: stub the draw + team-sheet scrape.
    monkeypatch.setattr(oh, "fetch_draw", lambda s, r: {"fixtures": []})
    monkeypatch.setattr(oh, "parse_draw", lambda raw: [_match()])
    monkeypatch.setattr(oh, "save_raw", lambda *a, **k: None)

    def _no_sheet(url):  # simulate "line-ups not published yet"
        raise oh.TeamSheetNotFound("no team sheet")
    monkeypatch.setattr(oh, "fetch_team_sheet_page", _no_sheet)

    # Capture agent fan-out without a real Lambda.
    fake_lambda = MagicMock()
    real_client = boto3.client

    def fake_client(name, *a, **k):
        return fake_lambda if name == "lambda" else real_client(name, *a, **k)
    monkeypatch.setattr(oh.boto3, "client", fake_client)

    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="teams",
            KeySchema=[{"AttributeName": "teamId", "KeyType": "HASH"},
                       {"AttributeName": "round", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "teamId", "AttributeType": "S"},
                                  {"AttributeName": "round", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield fake_lambda, ddb.Table("teams")


def test_first_run_fans_out(setup):
    fake_lambda, _ = setup
    result = oh.lambda_handler({"season": 2026, "round": "current"}, None)
    assert result["agent_triggered"] == ["round-16-knights-v-dragons"]
    assert fake_lambda.invoke.call_count == 1


def test_duplicate_run_is_skipped(setup):
    """The retry that triggered the triple-fire must now no-op the fan-out."""
    fake_lambda, _ = setup
    oh.lambda_handler({"season": 2026, "round": "current"}, None)
    second = oh.lambda_handler({"season": 2026, "round": "current"}, None)
    assert second["skipped"] == "locked"
    assert second["agent_triggered"] == []
    assert fake_lambda.invoke.call_count == 1  # NOT 2 — the duplicate was suppressed


def test_force_overrides_lock(setup):
    fake_lambda, _ = setup
    oh.lambda_handler({"season": 2026, "round": "current"}, None)
    forced = oh.lambda_handler({"season": 2026, "round": "current", "force": True}, None)
    assert "skipped" not in forced
    assert forced["agent_triggered"] == ["round-16-knights-v-dragons"]
    assert fake_lambda.invoke.call_count == 2


def test_expired_lock_allows_rerun(setup):
    """Once the lock window passes, a fresh run proceeds again."""
    fake_lambda, table = setup
    oh.lambda_handler({"season": 2026, "round": "current"}, None)
    # Expire the lock by rewinding lockedUntil into the past.
    table.update_item(
        Key={"teamId": oh._LOCK_TEAM_ID, "round": "2026#16"},
        UpdateExpression="SET lockedUntil = :p",
        ExpressionAttributeValues={":p": 0},
    )
    again = oh.lambda_handler({"season": 2026, "round": "current"}, None)
    assert again["agent_triggered"] == ["round-16-knights-v-dragons"]
    assert fake_lambda.invoke.call_count == 2
