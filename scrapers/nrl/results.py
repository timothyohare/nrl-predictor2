import json
import os
from datetime import datetime, timezone

import boto3

from common.match_id import match_id_from_url
from common.teams import to_slug
from scrapers.shared.http_client import get_with_retry
from scrapers.shared.models import MatchResult
from scrapers.shared.s3_cache import save_raw

_DRAW_URL = "https://www.nrl.com/draw/data?competition=111&season={season}&round={round}"


def fetch_results(season: int, round_number: int) -> dict:
    _, body = get_with_retry(_DRAW_URL.format(season=season, round=round_number))
    return json.loads(body)


def parse_results(data: dict) -> list[MatchResult]:
    results = []
    for fixture in data.get("fixtures", []):
        if fixture.get("matchState") != "FullTime":
            continue
        home = fixture["homeTeam"]
        away = fixture["awayTeam"]
        home_score = home.get("score", 0) or 0
        away_score = away.get("score", 0) or 0
        winner = home["nickName"] if home_score >= away_score else away["nickName"]
        url = fixture.get("matchCentreUrl", "")
        match_id = match_id_from_url(url) if url else ""
        results.append(MatchResult(
            match_id=match_id,
            home_team=to_slug(home["nickName"]),
            away_team=to_slug(away["nickName"]),
            home_score=home_score,
            away_score=away_score,
            winner=to_slug(winner),
            margin=abs(home_score - away_score),
            match_state="FullTime",
        ))
    return results


def lambda_handler(event: dict, context) -> None:
    season = event["season"]
    round_number = event["round"]
    table_name = os.environ["RESULTS_TABLE"]
    bucket = os.environ["RAW_BUCKET"]
    scored_at = datetime.now(timezone.utc).isoformat()

    raw = fetch_results(season, round_number)
    save_raw(bucket, f"raw-scrapes/results/{season}/round-{round_number}.json", json.dumps(raw))

    results = parse_results(raw)
    table = boto3.resource("dynamodb").Table(table_name)
    with table.batch_writer() as batch:
        for r in results:
            batch.put_item(Item={
                "matchId": r.match_id,
                "scoredAt": scored_at,
                "homeTeam": r.home_team,
                "awayTeam": r.away_team,
                "homeScore": r.home_score,
                "awayScore": r.away_score,
                "winner": r.winner,
                "margin": r.margin,
                "matchState": r.match_state,
            })
