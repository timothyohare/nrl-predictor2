"""Regression: team sheets must be stored under the SAME match_id the agent queries.

The agent is fanned out with the draw slug (``round-15-warriors-v-sharks``) and
looks up team sheets / spine synergy by it. Team sheets used to be stored under the
numeric NRL ``matchId`` (``20261111530``), so every lookup missed and the agent ran
blind on team sheets. These tests pin the id to the draw slug derived from the
match-centre URL — the single source of truth.
"""
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

import scrapers.nrl.team_sheet as tsmod
from scrapers.nrl.draw import match_id_from_url, parse_draw

URL = "/draw/nrl-premiership/2026/round-15/warriors-v-sharks/"
SLUG = "round-15-warriors-v-sharks"
NUMERIC = "20261111530"


def test_match_id_from_url():
    assert match_id_from_url(URL) == SLUG
    assert match_id_from_url(URL.rstrip("/")) == SLUG  # trailing slash optional


def test_storage_id_matches_draw_id():
    """The id the writer keys on == the id parse_draw (hence the agent) produces."""
    draw = {"fixtures": [{
        "matchCentreUrl": URL,
        "homeTeam": {"nickName": "Warriors"},
        "awayTeam": {"nickName": "Sharks"},
        "roundTitle": "Round 15",
        "venue": "Go Media Stadium",
        "matchState": "Pre",
        "clock": {"kickOffTimeLong": "2026-06-14T19:35:00"},
    }]}
    match = parse_draw(draw)[0]
    assert match.match_id == SLUG
    assert match_id_from_url(match.match_centre_url) == match.match_id


@pytest.fixture
def teams_table(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("TEAMS_TABLE", "teams")
    monkeypatch.setenv("RAW_BUCKET", "bucket")
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
        yield ddb.Table("teams")


def test_team_sheet_lambda_stores_under_slug(teams_table, monkeypatch):
    """The standalone scraper keys on the URL slug, not the numeric NRL matchId."""
    ts = SimpleNamespace(
        match_id=NUMERIC, round=15, match_state="Pre", kick_off=None,
        home_team=SimpleNamespace(nick_name="Warriors", players=[], score=None),
        away_team=SimpleNamespace(nick_name="Sharks", players=[], score=None),
    )
    monkeypatch.setattr(tsmod, "fetch_team_sheet_page", lambda url: {"q": "data"})
    monkeypatch.setattr(tsmod, "parse_team_sheet", lambda q: ts)
    monkeypatch.setattr(tsmod, "save_raw", lambda *a, **k: None)

    tsmod.lambda_handler({"matchCentreUrl": URL}, None)

    items = teams_table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["teamId"] == SLUG
    assert items[0]["teamId"] != NUMERIC
    assert items[0]["homeTeam"] == "Warriors"
