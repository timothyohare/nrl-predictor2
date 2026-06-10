import os

import boto3
from langchain_core.tools import tool


class ToolError(Exception):
    pass


def _get_weather(venue: str, date: str, table=None) -> dict:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["WEATHER_TABLE"])
    response = tbl.get_item(Key={"pk": f"weather#{venue}", "sk": date})
    item = response.get("Item")
    if not item:
        raise ToolError(f"No weather forecast for {venue} on {date}")
    return item


@tool
def get_weather(venue: str, date: str) -> dict:
    """Returns the venue weather forecast for a match date (YYYY-MM-DD)."""
    return _get_weather(venue=venue, date=date)
