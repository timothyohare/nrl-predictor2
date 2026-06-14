"""Lambda handler for odds scraping."""

import logging
import os
from datetime import datetime, timezone

import boto3

from scrapers.odds.scraper import fetch_odds, parse_odds

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    season = event.get("season", datetime.now(timezone.utc).year)
    round_number = event.get("round")
    scraped_at = datetime.now(timezone.utc).isoformat()

    # Get API key from env (set from Secrets Manager via CDK)
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        secret = boto3.client("secretsmanager").get_secret_value(
            SecretId="nrl-predictor/odds-api-key"
        )
        api_key = secret["SecretString"]

    # Get round matches from the teams table (draw entries)
    teams_table = boto3.resource("dynamodb").Table(os.environ["TEAMS_TABLE"])
    if round_number:
        # Scan for draw entries in this round
        response = teams_table.scan(
            FilterExpression="round = :r AND contains(teamId, :home)",
            ExpressionAttributeValues={":r": str(round_number), ":home": "#home"},
        )
        round_matches = [
            {
                "match_id": item["matchId"],
                "home_team": item["team"],
                "away_team": "",  # filled below
            }
            for item in response.get("Items", [])
        ]
        # Fill away teams
        for match in round_matches:
            away_resp = teams_table.scan(
                FilterExpression="matchId = :m AND contains(teamId, :away)",
                ExpressionAttributeValues={":m": match["match_id"], ":away": "#away"},
            )
            away_items = away_resp.get("Items", [])
            if away_items:
                match["away_team"] = away_items[0]["team"]
    else:
        round_matches = []

    # Fetch and parse odds
    raw = fetch_odds(api_key=api_key)
    if not raw:
        logger.warning("No odds returned from API")
        return {"matches": 0}

    parsed = parse_odds(raw, round_matches)

    # Write to odds table
    odds_table = boto3.resource("dynamodb").Table(os.environ["ODDS_TABLE"])
    for odds in parsed:
        odds["scrapedAt"] = scraped_at
        odds["season"] = season
        if round_number:
            odds["roundNumber"] = round_number
        odds_table.put_item(Item=odds)

    logger.info("Wrote %d odds entries for round %s", len(parsed), round_number)
    return {"matches": len(parsed), "round": round_number}
