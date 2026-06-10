"""Single Lambda entry point — routes by path to the correct handler."""
import json
import os

import boto3

from api.rate_limit import check_rate_limit


def lambda_handler(event: dict, context) -> dict:
    path = (event.get("rawPath") or event.get("path") or "").rstrip("/")
    source_ip = (event.get("requestContext") or {}).get("http", {}).get("sourceIp", "unknown")

    # Rate limit check
    rate_table_name = os.environ.get("RATE_LIMITS_TABLE")
    if rate_table_name:
        rate_table = boto3.resource("dynamodb").Table(rate_table_name)
        allowed, reason = check_rate_limit(source_ip, table=rate_table)
        if not allowed:
            return {
                "statusCode": 429,
                "headers": {"Content-Type": "application/json", "Retry-After": "3600"},
                "body": json.dumps({"error": reason}),
            }

    if path == "/health":
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": '{"status":"ok"}'}

    if path.startswith("/predictions"):
        from api.predictions import lambda_handler as predictions_handler
        return predictions_handler(event, context)

    if path == "/accuracy":
        from api.accuracy import lambda_handler as accuracy_handler
        return accuracy_handler(event, context)

    if path == "/tournament/leaderboard":
        from api.tournament import lambda_handler as tournament_handler
        return tournament_handler(event, context)

    return {
        "statusCode": 404,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": "Not found"}),
    }
