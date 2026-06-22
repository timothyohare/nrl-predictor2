import json
import logging
import os
from datetime import datetime, timezone

import boto3

from scoring.metrics import aggregate_round, aggregate_season, aggregate_market_season
from scoring.scorer import ResultNotReady, score_prediction

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> None:
    match_id = event["matchId"]
    round_number = event["round"]
    season = event["season"]

    ddb = boto3.resource("dynamodb")
    pred_table = ddb.Table(os.environ["PREDICTIONS_TABLE"])
    results_table = ddb.Table(os.environ["RESULTS_TABLE"])
    metrics_table = ddb.Table(os.environ["METRICS_TABLE"])
    odds_table_name = os.environ.get("ODDS_TABLE")
    odds_table = ddb.Table(odds_table_name) if odds_table_name else None
    scored_at = datetime.now(timezone.utc).isoformat()

    try:
        scored = score_prediction(match_id, results_table, pred_table)

        # Read result item to carry homeTeam/score fields into scoring record
        result_resp = results_table.query(
            KeyConditionExpression="matchId = :m",
            ExpressionAttributeValues={":m": match_id},
            ScanIndexForward=False,
            Limit=1,
        )
        result_item = result_resp["Items"][0]

        results_table.put_item(Item={
            "matchId": match_id,
            "scoredAt": scored_at,
            # carry result fields so retrospective can read latest item cleanly
            "homeTeam": result_item.get("homeTeam", ""),
            "awayTeam": result_item.get("awayTeam", ""),
            "homeScore": result_item.get("homeScore", 0),
            "awayScore": result_item.get("awayScore", 0),
            "winner": result_item.get("winner", ""),
            "margin": result_item.get("margin", 0),
            "matchState": "FullTime",
            # scoring fields
            "correct_pick": scored.correct_pick,
            "predicted_margin_error": scored.predicted_margin_error,
            "within_6_pts": scored.within_6_pts,
            "within_12_pts": scored.within_12_pts,
            "brier_component": str(scored.brier_component),
            "confidence": scored.confidence,
            "prompt_version": scored.prompt_version,
            "roundNumber": round_number,
            "season": season,
        })
        logger.info(
            "Scored %s: correct=%s margin_err=%s confidence=%s prompt=%s",
            match_id, scored.correct_pick, scored.predicted_margin_error,
            scored.confidence, scored.prompt_version,
        )
        aggregate_round(round_number, season, results_table, metrics_table)
        aggregate_season(season, results_table, metrics_table)
        if odds_table:
            try:
                aggregate_market_season(season, odds_table, results_table, metrics_table)
            except Exception as e:
                logger.warning("Market accuracy aggregation failed: %s", e)

        # Trigger retrospective asynchronously — failure here must not affect scoring
        _invoke_retrospective(match_id, round_number, season)
    except ResultNotReady as e:
        logger.warning("Skipping %s — result not ready: %s", match_id, e)
        return {"status": "NO_RESULT", "matchId": match_id}
    except Exception as e:
        logger.error("Scoring failed for %s: %s", match_id, e, exc_info=True)
        raise


def _invoke_retrospective(match_id: str, round_number: int, season: int) -> None:
    fn_arn = os.environ.get("RETROSPECTIVE_FUNCTION_ARN")
    if not fn_arn:
        logger.debug("RETROSPECTIVE_FUNCTION_ARN not set, skipping retrospective trigger")
        return
    try:
        boto3.client("lambda").invoke(
            FunctionName=fn_arn,
            InvocationType="Event",  # async, fire-and-forget
            Payload=json.dumps({"matchId": match_id, "round": round_number, "season": season}),
        )
        logger.info("Triggered retrospective for %s", match_id)
    except Exception as e:
        logger.warning("Failed to trigger retrospective for %s: %s", match_id, e)
