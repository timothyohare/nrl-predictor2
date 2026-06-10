"""
Run once to populate the results table with historical data.

Usage:
    python3 -m scrapers.nrl.backfill --seasons 2025 2026
"""
import argparse
import logging
import os
import time
from datetime import datetime, timezone

import boto3

from scrapers.nrl.results import fetch_results, parse_results
from scrapers.shared.s3_cache import save_raw
import json

logger = logging.getLogger(__name__)


def backfill_season(season: int, max_round: int = 27) -> None:
    table_name = os.environ["RESULTS_TABLE"]
    bucket = os.environ["RAW_BUCKET"]
    table = boto3.resource("dynamodb").Table(table_name)
    records_written = 0
    records_skipped = 0

    for round_number in range(1, max_round + 1):
        raw = fetch_results(season, round_number)
        fixtures = raw.get("fixtures", [])
        if not fixtures:
            logger.info("Round %d/%d: empty — skipping", round_number, season)
            time.sleep(2)
            continue

        save_raw(bucket, f"raw-scrapes/results/{season}/round-{round_number}.json", json.dumps(raw))
        results = parse_results(raw)

        if not results:
            logger.info("Round %d/%d: no FullTime results — skipping", round_number, season)
            time.sleep(2)
            continue

        scored_at = datetime.now(timezone.utc).isoformat()
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
                    "season": season,
                    "roundNumber": round_number,
                })
        records_written += len(results)
        logger.info("Round %d/%d: wrote %d records", round_number, season, len(results))
        time.sleep(2)

    logger.info(
        "Backfill complete — season %d: %d written, %d skipped",
        season, records_written, records_skipped,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", type=int, default=[2025, 2026])
    parser.add_argument("--max-round", type=int, default=27)
    args = parser.parse_args()
    for season in args.seasons:
        backfill_season(season=season, max_round=args.max_round)
