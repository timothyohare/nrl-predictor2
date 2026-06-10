import os
import time

import boto3

HOURLY_LIMIT = 20
DAILY_LIMIT = 100


def check_rate_limit(ip: str, table=None) -> tuple[bool, str]:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RATE_LIMITS_TABLE"])
    now = int(time.time())
    hour_key = f"{ip}#hour#{now // 3600}"

    try:
        resp = tbl.update_item(
            Key={"pk": hour_key},
            UpdateExpression="ADD #cnt :one SET #ttl = if_not_exists(#ttl, :ttl)",
            ExpressionAttributeNames={"#cnt": "count", "#ttl": "ttl"},
            ExpressionAttributeValues={":one": 1, ":ttl": now + 7200},
            ReturnValues="UPDATED_NEW",
        )
        count = int(resp["Attributes"]["count"])
    except Exception:
        return True, "ok"  # fail open

    if count > HOURLY_LIMIT:
        return False, f"Rate limit exceeded: {HOURLY_LIMIT} requests/hour"

    return True, "ok"
