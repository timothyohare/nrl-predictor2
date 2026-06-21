import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from common.teams import to_slug
from scrapers.shared.http_client import get_with_retry
from scrapers.shared.models import LadderPosition
from scrapers.shared.s3_cache import save_raw

_LADDER_URL = "https://www.nrl.com/ladder/data?competition=111&season={season}"


def fetch_ladder(season: int) -> dict:
    _, body = get_with_retry(_LADDER_URL.format(season=season))
    return json.loads(body)


def parse_ladder(data: dict) -> list[LadderPosition]:
    positions = []
    for p in data.get("positions", []):
        stats = p.get("stats", {})
        positions.append(LadderPosition(
            position=p["position"],
            team_name=to_slug(p["teamNickname"]),
            played=stats.get("played", 0),
            wins=stats.get("wins", 0),
            losses=stats.get("losses", 0),
            draws=stats.get("draws", 0),
            points=stats.get("points", 0),
            for_against_diff=stats.get("pointsDiff", 0),
            percentage=stats.get("percentage", 0.0),
        ))
    return sorted(positions, key=lambda x: x.position)


def lambda_handler(event: dict, context) -> None:
    season = event["season"]
    table_name = os.environ["TEAMS_TABLE"]
    bucket = os.environ["RAW_BUCKET"]
    scraped_at = datetime.now(timezone.utc).isoformat()

    raw = fetch_ladder(season)
    save_raw(bucket, f"raw-scrapes/ladder/{season}.json", json.dumps(raw))

    ladder = parse_ladder(raw)
    table = boto3.resource("dynamodb").Table(table_name)
    table.put_item(Item={
        "teamId": f"ladder#{season}",
        "round": "current",
        "season": season,
        "positions": [
            {k: Decimal(str(v)) if isinstance(v, float) else v for k, v in p.__dict__.items()}
            for p in ladder
        ],
        "scraped_at": scraped_at,
    })
