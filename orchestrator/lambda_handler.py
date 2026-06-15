import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from scrapers.nrl.draw import fetch_draw, parse_draw
from scrapers.nrl.team_sheet import (
    TeamSheetNotFound,
    fetch_team_sheet_page,
    parse_team_sheet,
)
from scrapers.shared.s3_cache import save_raw

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Idempotency lock lives as a single item in the teams table. The agent never reads it
# (spine_synergy scans filter on `team`; get_team_sheet uses an exact match-slug key).
_LOCK_TEAM_ID = "__orchestrator_lock__"


def _acquire_round_lock(teams_table, season: int, round_number: int, now: datetime, window_s: int) -> bool:
    """Claim a per-(season, round) lock so duplicate orchestrator runs within ``window_s``
    don't repeat the expensive team-sheet scrape + agent fan-out.

    A synchronous ``aws lambda invoke`` of this ~73s handler overruns the CLI's 60s read
    timeout, so botocore retries it — firing the orchestrator (and the fan-out) 2-3x.
    EventBridge and async invokes can also redeliver / retry on error. This conditional
    write lets only the first run within the window proceed. Returns True if this run won
    the lock, False if another run already holds it.
    """
    now_epoch = int(now.timestamp())
    try:
        teams_table.put_item(
            Item={
                "teamId": _LOCK_TEAM_ID,
                "round": f"{season}#{round_number}",
                "lockedUntil": now_epoch + window_s,
                "lockedAt": now.isoformat(),
            },
            ConditionExpression="attribute_not_exists(teamId) OR lockedUntil < :now",
            ExpressionAttributeValues={":now": now_epoch},
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def lambda_handler(event: dict, context) -> dict:
    season = int(event.get("season", 2026))
    round_input = event.get("round")
    if round_input is None:
        raise ValueError("orchestrator event must include 'round' (int or 'current')")
    round_for_fetch = round_input if round_input == "current" else int(round_input)

    bucket = os.environ["RAW_BUCKET"]
    teams_table_name = os.environ["TEAMS_TABLE"]
    agent_fn_name = os.environ["AGENT_FUNCTION_NAME"]
    scraped_at = datetime.now(timezone.utc).isoformat()

    # 1. Scrape draw
    raw_draw = fetch_draw(season, round_for_fetch)
    matches = parse_draw(raw_draw)
    if not matches:
        logger.warning("No matches parsed for season=%s round=%s", season, round_input)
        return {"matches": 0, "agent_triggered": []}

    actual_round = matches[0].round_number
    save_raw(bucket, f"raw-scrapes/draw/{season}/round-{actual_round}.json", json.dumps(raw_draw))
    logger.info("Parsed %d matches for round %s", len(matches), actual_round)

    teams_table = boto3.resource("dynamodb").Table(teams_table_name)

    # Idempotency guard: skip the team-sheet scrape + agent fan-out if another orchestrator
    # run already claimed this round within the lock window. `force: true` overrides it.
    lock_window_s = int(os.environ.get("ORCHESTRATOR_LOCK_WINDOW_SECONDS", "900"))
    if not event.get("force") and lock_window_s > 0:
        if not _acquire_round_lock(teams_table, season, actual_round, datetime.now(timezone.utc), lock_window_s):
            logger.warning(
                "Orchestrator already ran for season=%s round=%s within %ds — skipping "
                "fan-out (pass force=true to override).", season, actual_round, lock_window_s,
            )
            return {"round": actual_round, "matches": len(matches), "agent_triggered": [], "skipped": "locked"}

    # 2. Write draw entries to teams table
    with teams_table.batch_writer() as batch:
        for match in matches:
            for side, team in (("home", match.home_team), ("away", match.away_team)):
                batch.put_item(Item={
                    "teamId": f"{match.match_id}#{side}",
                    "round": str(match.round_number),
                    "matchId": match.match_id,
                    "team": team,
                    "venue": match.venue,
                    "kickOff": match.kick_off or "",
                    "matchState": match.match_state,
                    "matchCentreUrl": match.match_centre_url,
                    "scraped_at": scraped_at,
                })

    # 3. Scrape team sheets inline (best-effort — agent runs regardless)
    for match in matches:
        if not match.match_centre_url:
            continue
        try:
            q_data = fetch_team_sheet_page(match.match_centre_url)
            save_raw(
                bucket,
                f"raw-scrapes/team-sheet/{match.match_centre_url.strip('/')}.json",
                json.dumps(q_data),
            )
            ts = parse_team_sheet(q_data)
            ts.scraped_at = scraped_at
            # Key by the draw slug (match.match_id) that the agent is fanned out
            # with and looks the sheet up by — NOT the numeric NRL matchId on ts.
            teams_table.put_item(Item={
                "teamId": match.match_id,
                "round": str(match.round_number),
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
        except TeamSheetNotFound as e:
            logger.warning("Team sheet not available for %s: %s", match.match_id, e)
        except Exception as e:
            logger.error("Team sheet scrape failed for %s: %s", match.match_id, e, exc_info=True)

    # 4. Fan out: invoke agent async per match, staggered to stay under the
    # Anthropic 50K input-tokens/minute rate limit. Each agent run uses
    # roughly 8-12K input tokens, so 8s between starts keeps us well below.
    stagger_s = float(os.environ.get("AGENT_INVOKE_STAGGER_SECONDS", "8"))
    lambda_client = boto3.client("lambda")
    agent_triggered: list[str] = []
    for i, match in enumerate(matches):
        if i > 0 and stagger_s > 0:
            time.sleep(stagger_s)
        try:
            lambda_client.invoke(
                FunctionName=agent_fn_name,
                InvocationType="Event",
                Payload=json.dumps({"matchId": match.match_id, "round": match.round_number}),
            )
            agent_triggered.append(match.match_id)
        except Exception as e:
            logger.error("Failed to invoke agent for %s: %s", match.match_id, e, exc_info=True)

    logger.info("Triggered agent for %d/%d matches", len(agent_triggered), len(matches))
    return {
        "round": actual_round,
        "matches": len(matches),
        "agent_triggered": agent_triggered,
    }
