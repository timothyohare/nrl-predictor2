import os

import boto3
from langchain_core.tools import tool


def _get_head_to_head(team_a: str, team_b: str, venue: str | None = None, table=None) -> dict:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    response = tbl.scan(
        FilterExpression=(
            "(homeTeam = :a AND awayTeam = :b) OR (homeTeam = :b AND awayTeam = :a)"
        ),
        ExpressionAttributeValues={":a": team_a, ":b": team_b},
    )
    items = response.get("Items", [])
    if venue:
        items = [i for i in items if i.get("venue") == venue]
    if not items:
        return {"team_a_wins": 0, "team_b_wins": 0, "draws": 0, "avg_margin": 0, "last_3_results": []}
    a_wins = sum(1 for i in items if i["winner"] == team_a)
    b_wins = sum(1 for i in items if i["winner"] == team_b)
    draws = len(items) - a_wins - b_wins
    avg_margin = sum(int(i["margin"]) for i in items) / len(items)
    last_3 = sorted(items, key=lambda x: x["scoredAt"], reverse=True)[:3]
    return {
        "team_a_wins": a_wins,
        "team_b_wins": b_wins,
        "draws": draws,
        "avg_margin": round(avg_margin, 1),
        "last_3_results": last_3,
    }


@tool
def get_head_to_head(team_a: str, team_b: str, venue: str = "") -> dict:
    """Returns historical head-to-head record between two teams, optionally filtered by venue."""
    return _get_head_to_head(team_a=team_a, team_b=team_b, venue=venue or None)
