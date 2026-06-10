import os
from datetime import datetime, timezone, timedelta

import boto3
from langchain_core.tools import tool

_MAX_AGE_HOURS = 48


def _get_injury_list(team: str, table=None) -> list[dict]:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["INJURIES_TABLE"])
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_MAX_AGE_HOURS)).isoformat()
    prefix = f"injury#{team}#"
    response = tbl.scan(
        FilterExpression="begins_with(pk, :prefix) AND sk > :cutoff",
        ExpressionAttributeValues={":prefix": prefix, ":cutoff": cutoff},
    )
    return response.get("Items", [])


@tool
def get_injury_list(team: str) -> list[dict]:
    """Returns current injury/unavailability list for a team."""
    return _get_injury_list(team=team)
