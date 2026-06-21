"""The v2 tools must resolve any inbound team form AND match rows stored in either the old
nickname form or the new slug form (the migration window). This is the regression that sank
round 17: a full team name returned nothing because the stored data was short-form."""
import boto3
import pytest
from moto import mock_aws

from agent.tools.coaching_matchup import _get_coach
from agent.tools.head_to_head import _get_head_to_head
from agent.tools.recent_form import _get_recent_form

TABLE = "results"


@pytest.fixture
def results_table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "matchId", "KeyType": "HASH"},
                       {"AttributeName": "scoredAt", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "matchId", "AttributeType": "S"},
                                  {"AttributeName": "scoredAt", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        t = ddb.Table(TABLE)
        # Mixed storage: one row nickname-form (legacy), one slug-form (post-migration).
        t.put_item(Item={"matchId": "round-15-sea-eagles-v-storm", "scoredAt": "t2",
                         "homeTeam": "Sea Eagles", "awayTeam": "Storm",
                         "winner": "Sea Eagles", "margin": 4, "homeScore": 20, "awayScore": 16})
        t.put_item(Item={"matchId": "round-16-storm-v-sea-eagles", "scoredAt": "t1",
                         "homeTeam": "storm", "awayTeam": "sea-eagles",
                         "winner": "storm", "margin": 8, "homeScore": 24, "awayScore": 16})
        yield t


@pytest.mark.parametrize("name", ["Manly Sea Eagles", "Sea Eagles", "sea-eagles", "manly"])
def test_recent_form_resolves_any_form_across_mixed_storage(results_table, name):
    out = _get_recent_form(name, table=results_table)
    assert len(out["results"]) == 2  # both the nickname-row and the slug-row match


def test_head_to_head_resolves_long_names_across_mixed_storage(results_table):
    out = _get_head_to_head("Manly Sea Eagles", "Melbourne Storm", table=results_table)
    # one win each, regardless of which row stored which form
    assert out["team_a_wins"] == 1
    assert out["team_b_wins"] == 1
    assert len(out["last_3_results"]) == 2


def test_coaching_lookup_resolves_full_name():
    assert _get_coach("Manly Sea Eagles")["coach"] == "Anthony Seibold"
    assert _get_coach("sea-eagles")["coach"] == "Anthony Seibold"
