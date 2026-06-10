import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

_COSTS = {
    "claude-haiku-4-5-20251001": {"input": Decimal("0.00080"), "output": Decimal("0.00400")},
    "claude-sonnet-4-6":         {"input": Decimal("0.00300"), "output": Decimal("0.01500")},
}
_DEFAULT_COST = {"input": Decimal("0.00300"), "output": Decimal("0.01500")}


class BudgetExceeded(Exception):
    pass


def record_usage(input_tokens: int, output_tokens: int, model: str, table=None) -> None:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["CLAUDE_USAGE_TABLE"])
    costs = _COSTS.get(model, _DEFAULT_COST)
    cost_usd = (
        Decimal(input_tokens) / 1000 * costs["input"] +
        Decimal(output_tokens) / 1000 * costs["output"]
    )
    tbl.put_item(Item={
        "yearMonth": datetime.now(timezone.utc).strftime("%Y-%m"),
        "invokedAt": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    })


def get_month_to_date_spend(table=None) -> float:
    tbl = table or boto3.resource("dynamodb").Table(os.environ["CLAUDE_USAGE_TABLE"])
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    response = tbl.query(
        KeyConditionExpression="yearMonth = :m",
        ExpressionAttributeValues={":m": month},
    )
    return float(sum(Decimal(str(item.get("cost_usd", 0))) for item in response.get("Items", [])))


def check_budget(threshold_usd: float, table=None) -> None:
    spend = get_month_to_date_spend(table=table)
    if spend >= threshold_usd:
        raise BudgetExceeded(f"Month-to-date spend ${spend:.4f} exceeds threshold ${threshold_usd}")
