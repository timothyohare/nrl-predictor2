import os

import boto3
from langchain_core.tools import tool

from agent.tools.momentum import calculate_momentum
from common.teams import to_slug


def _get_recent_form(team: str, n: int = 5, table=None) -> dict:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    # Match on the canonical slug so any inbound form resolves, and so mixed stored
    # forms (nickname pre-migration, slug after) both match. Filter client-side.
    slug = to_slug(team)
    items = [
        i for i in tbl.scan().get("Items", [])
        if slug in (to_slug(i.get("homeTeam", "")), to_slug(i.get("awayTeam", "")))
    ]
    items = sorted(items, key=lambda x: x["scoredAt"], reverse=True)
    results = items[:n]
    momentum = calculate_momentum(results, team=team)
    return {"results": results, "momentum": momentum}


@tool
def get_recent_form(team: str, n: int = 5) -> dict:
    """Returns the last n match results for a team with momentum analysis."""
    return _get_recent_form(team=team, n=n)
