"""Tournament leaderboard API endpoint."""
import json
import os
from decimal import Decimal

import boto3

from tournament.variant_scorer import get_leaderboard


def _serialise(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")


def lambda_handler(event: dict, context) -> dict:
    metrics_table_name = os.environ.get("VARIANT_METRICS_TABLE")
    if not metrics_table_name:
        return {
            "statusCode": 503,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Tournament not configured"}),
        }

    from datetime import datetime, timezone
    season = int((event.get("queryStringParameters") or {}).get("season", datetime.now(timezone.utc).year))

    metrics_table = boto3.resource("dynamodb").Table(metrics_table_name)
    leaderboard = get_leaderboard(season, metrics_table)

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=300",
        },
        "body": json.dumps({"season": season, "leaderboard": leaderboard}, default=_serialise),
    }
