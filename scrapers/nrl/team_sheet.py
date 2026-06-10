import json
import logging
import os
from datetime import datetime, timezone

import boto3
from bs4 import BeautifulSoup

from scrapers.shared.http_client import get_with_retry
from scrapers.shared.models import Player, TeamSheet, TeamSide
from scrapers.shared.s3_cache import save_raw

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.nrl.com"


class TeamSheetNotFound(Exception):
    pass


def fetch_team_sheet_page(match_centre_url: str) -> dict:
    url = _BASE_URL + match_centre_url if match_centre_url.startswith("/") else match_centre_url
    _, html = get_with_retry(url)
    soup = BeautifulSoup(html, "lxml")
    el = soup.find(id="vue-match-centre")
    if not el or not el.get("q-data"):
        raise TeamSheetNotFound(f"No q-data found at {url}")
    return json.loads(el["q-data"])


def parse_team_sheet(q_data: dict) -> TeamSheet:
    match = q_data.get("match")
    if not match:
        raise TeamSheetNotFound("'match' key missing from q-data")

    home_players = _parse_players(match["homeTeam"].get("players", []))
    away_players = _parse_players(match["awayTeam"].get("players", []))
    if not home_players and not away_players:
        raise TeamSheetNotFound("Both player lists are empty")

    return TeamSheet(
        match_id=match["matchId"],
        round=match.get("roundNumber", 0),
        kick_off=match.get("startTime") or None,
        match_state=match.get("matchState", ""),
        home_team=TeamSide(
            team_id=match["homeTeam"]["teamId"],
            nick_name=match["homeTeam"]["nickName"],
            score=match["homeTeam"].get("score"),
            players=home_players,
        ),
        away_team=TeamSide(
            team_id=match["awayTeam"]["teamId"],
            nick_name=match["awayTeam"]["nickName"],
            score=match["awayTeam"].get("score"),
            players=away_players,
        ),
    )


def _parse_players(raw: list[dict]) -> list[Player]:
    return [
        Player(
            jersey_number=p["number"],
            first_name=p["firstName"],
            last_name=p["lastName"],
            position=p["position"],
            is_starting=p["isOnField"],
            player_id=p["playerId"],
        )
        for p in raw
    ]


def lambda_handler(event: dict, context) -> None:
    match_centre_url = event["matchCentreUrl"]
    table_name = os.environ["TEAMS_TABLE"]
    bucket = os.environ["RAW_BUCKET"]
    scraped_at = datetime.now(timezone.utc).isoformat()

    try:
        q_data = fetch_team_sheet_page(match_centre_url)
    except TeamSheetNotFound as e:
        logger.warning("Team sheet not found: %s", e)
        return

    save_raw(bucket, f"raw-scrapes/team-sheet/{match_centre_url.strip('/')}.json", json.dumps(q_data))

    ts = parse_team_sheet(q_data)
    ts.scraped_at = scraped_at

    table = boto3.resource("dynamodb").Table(table_name)
    table.put_item(Item={
        "teamId": ts.match_id,
        "round": str(ts.round),
        "matchState": ts.match_state,
        "kickOff": ts.kick_off or "",
        "homeTeam": ts.home_team.nick_name,
        "awayTeam": ts.away_team.nick_name,
        "homePlayers": [p.__dict__ for p in ts.home_team.players],
        "awayPlayers": [p.__dict__ for p in ts.away_team.players],
        "homeScore": ts.home_team.score,
        "awayScore": ts.away_team.score,
        "scraped_at": scraped_at,
    })
