import logging
import os

import boto3

from retrospective.retrospective import generate_retrospective

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    match_id = event["matchId"]
    round_number = event["round"]
    season = event["season"]

    ddb = boto3.resource("dynamodb")
    predictions_table = ddb.Table(os.environ["PREDICTIONS_TABLE"])
    results_table = ddb.Table(os.environ["RESULTS_TABLE"])
    retrospectives_table = ddb.Table(os.environ["RETROSPECTIVES_TABLE"])
    match_stats_table = ddb.Table(os.environ["MATCH_STATS_TABLE"])

    try:
        result = generate_retrospective(
            match_id=match_id,
            round_number=round_number,
            season=season,
            predictions_table=predictions_table,
            results_table=results_table,
            retrospectives_table=retrospectives_table,
            match_stats_table=match_stats_table,
        )
        logger.info("Retrospective complete for %s", match_id)
        return result
    except Exception as e:
        logger.error("Retrospective failed for %s: %s", match_id, e, exc_info=True)
        raise
