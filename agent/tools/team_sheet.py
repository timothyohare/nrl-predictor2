import os
from datetime import datetime, timezone, timedelta

import boto3
from langchain_core.tools import tool

MAX_DATA_AGE_HOURS = int(os.environ.get("MAX_DATA_AGE_HOURS", "24"))


class ToolError(Exception):
    pass


def _get_team_sheet(match_id: str, round_number: int, table=None) -> dict:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["TEAMS_TABLE"])
    response = tbl.get_item(Key={"teamId": match_id, "round": str(round_number)})
    item = response.get("Item")
    if not item:
        raise ToolError(f"No team sheet found for {match_id} round {round_number}")
    scraped_at = datetime.fromisoformat(item["scraped_at"])
    if scraped_at.tzinfo is None:
        scraped_at = scraped_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - scraped_at
    if age > timedelta(hours=MAX_DATA_AGE_HOURS):
        raise ToolError(f"Team sheet for {match_id} is stale ({age.total_seconds()/3600:.1f}h old)")
    return item


@tool
def get_team_sheet(match_id: str, round_number: int) -> dict:
    """Returns the official starting 1-17 + bench for a team and round from DynamoDB."""
    return _get_team_sheet(match_id=match_id, round_number=round_number)
