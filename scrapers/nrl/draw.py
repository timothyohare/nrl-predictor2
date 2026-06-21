import json
import os
from datetime import datetime, timezone

import boto3

from common.match_id import match_id_from_url  # noqa: F401  re-exported for back-compat
from common.teams import to_slug
from scrapers.shared.http_client import get_with_retry
from scrapers.shared.models import Match
from scrapers.shared.s3_cache import save_raw

_DRAW_URL = "https://www.nrl.com/draw/data?competition=111&season={season}&round={round}"


def fetch_draw(season: int, round_number: int) -> dict:
    _, body = get_with_retry(_DRAW_URL.format(season=season, round=round_number))
    return json.loads(body)


def parse_draw(data: dict) -> list[Match]:
    matches = []
    for fixture in data.get("fixtures", []):
        url = fixture.get("matchCentreUrl")
        if not url:
            continue
        match_id = match_id_from_url(url)
        kick_off = fixture.get("clock", {}).get("kickOffTimeLong") or None
        # venue is a plain string in current API; guard against legacy dict form
        venue_raw = fixture.get("venue", "")
        venue = venue_raw if isinstance(venue_raw, str) else venue_raw.get("name", "")
        # Current API: roundTitle = "Round 11"; legacy fixture: roundNumber int
        round_title = fixture.get("roundTitle") or ""
        try:
            round_number = int(round_title.split()[-1])
        except (ValueError, IndexError):
            round_number = fixture.get("roundNumber", 0)
        matches.append(Match(
            match_id=match_id,
            home_team=to_slug(fixture["homeTeam"]["nickName"]),
            away_team=to_slug(fixture["awayTeam"]["nickName"]),
            venue=venue,
            round_number=round_number,
            kick_off=kick_off,
            match_state=fixture.get("matchState", ""),
            match_centre_url=url,
        ))
    return matches


def lambda_handler(event: dict, context) -> None:
    season = event["season"]
    round_number = event["round"]
    table_name = os.environ["TEAMS_TABLE"]
    bucket = os.environ["RAW_BUCKET"]
    scraped_at = datetime.now(timezone.utc).isoformat()

    raw = fetch_draw(season, round_number)
    save_raw(bucket, f"raw-scrapes/draw/{season}/round-{round_number}.json", json.dumps(raw))

    matches = parse_draw(raw)
    table = boto3.resource("dynamodb").Table(table_name)

    with table.batch_writer() as batch:
        for match in matches:
            for side, team in (("home", match.home_team), ("away", match.away_team)):
                batch.put_item(Item={
                    "teamId": f"{match.match_id}#{side}",
                    # Use the actual round number parsed from the fixture, not the
                    # event value (which may be "current")
                    "round": str(match.round_number),
                    "matchId": match.match_id,
                    "team": team,
                    "venue": match.venue,
                    "kickOff": match.kick_off or "",
                    "matchState": match.match_state,
                    "matchCentreUrl": match.match_centre_url,
                    "scraped_at": scraped_at,
                })
