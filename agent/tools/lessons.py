import os

import boto3
from langchain_core.tools import tool


def _get_lessons(season: int, team: str | None = None, limit: int = 10, table=None) -> list[dict]:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RETROSPECTIVES_TABLE"])
    filter_expr = "season = :s"
    expr_values = {":s": season}
    if team:
        filter_expr += " AND contains(matchId, :t)"
        expr_values[":t"] = team.lower()
    response = tbl.scan(FilterExpression=filter_expr, ExpressionAttributeValues=expr_values)
    items = [i for i in response.get("Items", []) if i.get("lesson")]
    items.sort(key=lambda x: x.get("generatedAt", ""), reverse=True)
    return [
        {"matchId": i["matchId"], "roundNumber": i.get("roundNumber"), "lesson": i["lesson"], "generatedAt": i.get("generatedAt", "")}
        for i in items[:limit]
    ]


@tool
def get_lessons(season: int, team: str = "", limit: int = 10) -> list[dict]:
    """Returns lessons learned from post-match retrospectives for a season, optionally filtered by team slug."""
    return _get_lessons(season=season, team=team or None, limit=limit)
