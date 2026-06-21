"""Tests for scripts/migrate_identity.py — slugify is correct + idempotent; matchId cleanup
only deletes true duplicates."""
import boto3
import pytest
from moto import mock_aws

from scripts.migrate_identity import (
    find_deletable_matchid_rows,
    migrate_teams,
    slugify_item,
)


def test_slugify_item_flat_fields():
    item = {"homeTeam": "Manly Sea Eagles", "awayTeam": "Storm", "winner": "Melbourne Storm"}
    new, changed = slugify_item(item, ["homeTeam", "awayTeam", "winner"])
    assert changed
    assert new == {"homeTeam": "sea-eagles", "awayTeam": "storm", "winner": "storm"}


def test_slugify_item_idempotent():
    item = {"homeTeam": "sea-eagles", "winner": "storm"}
    new, changed = slugify_item(item, ["homeTeam", "winner"])
    assert not changed
    assert new == item


def test_slugify_nested_lists():
    item = {
        "positions": [{"team": "Wests Tigers", "position": 5}],
        "first_try_candidates": [{"team": "Canterbury Bulldogs", "player_name": "X"}],
    }
    new, changed = slugify_item(item, [])
    assert changed
    assert new["positions"][0]["team"] == "wests-tigers"
    assert new["first_try_candidates"][0]["team"] == "bulldogs"


def test_find_deletable_only_true_duplicates():
    rows = [
        {"matchId": "round-16-knights-v-dragons", "scoredAt": "t1", "homeTeam": "Knights", "awayTeam": "Dragons"},
        {"matchId": "dragons-v-knights", "scoredAt": "t1", "homeTeam": "Dragons", "awayTeam": "Knights"},  # dup
        {"matchId": "eels-v-storm", "scoredAt": "t9", "homeTeam": "Eels", "awayTeam": "Storm"},  # unique, no canonical
    ]
    deletable, kept = find_deletable_matchid_rows(rows)
    assert [d["matchId"] for d in deletable] == ["dragons-v-knights"]
    assert [k["matchId"] for k in kept] == ["eels-v-storm"]


@pytest.fixture
def results_table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="results",
            KeySchema=[{"AttributeName": "matchId", "KeyType": "HASH"},
                       {"AttributeName": "scoredAt", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "matchId", "AttributeType": "S"},
                                  {"AttributeName": "scoredAt", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        t = ddb.Table("results")
        t.put_item(Item={"matchId": "round-16-knights-v-dragons", "scoredAt": "t1",
                         "homeTeam": "Knights", "awayTeam": "Dragons", "winner": "Knights"})
        yield ddb


def test_migrate_teams_apply_then_idempotent(results_table):
    first = migrate_teams(results_table, ["results"], apply=True)
    assert first["results"] == 1
    item = results_table.Table("results").scan()["Items"][0]
    assert item["homeTeam"] == "knights" and item["winner"] == "knights"
    # second pass changes nothing
    second = migrate_teams(results_table, ["results"], apply=True)
    assert second["results"] == 0
