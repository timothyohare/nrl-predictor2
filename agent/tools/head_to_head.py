import os

import boto3
from langchain_core.tools import tool

from common.teams import to_slug


def _get_head_to_head(team_a: str, team_b: str, venue: str | None = None, table=None) -> dict:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    # Compare on canonical slugs so any inbound form resolves and mixed stored forms match.
    a, b = to_slug(team_a), to_slug(team_b)
    items = [
        i for i in tbl.scan().get("Items", [])
        if {to_slug(i.get("homeTeam", "")), to_slug(i.get("awayTeam", ""))} == {a, b}
    ]
    if venue:
        items = [i for i in items if i.get("venue") == venue]
    if not items:
        return {"team_a_wins": 0, "team_b_wins": 0, "draws": 0, "avg_margin": 0, "last_3_results": []}
    a_wins = sum(1 for i in items if to_slug(i["winner"]) == a)
    b_wins = sum(1 for i in items if to_slug(i["winner"]) == b)
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
