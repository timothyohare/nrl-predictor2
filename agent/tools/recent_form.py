import os

import boto3
from langchain_core.tools import tool

from agent.tools.momentum import calculate_momentum


def _get_recent_form(team: str, n: int = 5, table=None) -> dict:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    response = tbl.scan(
        FilterExpression="homeTeam = :t OR awayTeam = :t",
        ExpressionAttributeValues={":t": team},
    )
    items = sorted(response.get("Items", []), key=lambda x: x["scoredAt"], reverse=True)
    results = items[:n]
    momentum = calculate_momentum(results, team=team)
    return {"results": results, "momentum": momentum}


@tool
def get_recent_form(team: str, n: int = 5) -> dict:
    """Returns the last n match results for a team with momentum analysis."""
    return _get_recent_form(team=team, n=n)
