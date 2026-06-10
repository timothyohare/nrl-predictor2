#!/usr/bin/env python3
"""
Invoke the scoring Lambda for all matches in a given round.

Usage:
    python3 scripts/score_round.py --round 11 --season 2026
    python3 scripts/score_round.py --round 11 --season 2026 --dry-run

Reads matchIds from the predictions table, then invokes nrl-predictor-scoring
for each. The scoring Lambda auto-triggers the retrospective Lambda after scoring.
"""
import argparse
import json
import time
import boto3


SCORING_FUNCTION = "nrl-predictor-scoring"
REGION = "ap-southeast-2"


def get_match_ids(round_number: int, season: int) -> list[str]:
    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table("predictions")
    resp = table.scan(
        FilterExpression="roundNumber = :r",
        ExpressionAttributeValues={":r": round_number},
        ProjectionExpression="matchId",
    )
    seen = set()
    for item in resp.get("Items", []):
        seen.add(item["matchId"])
    return sorted(seen)


def invoke_scoring(match_id: str, round_number: int, season: int, dry_run: bool) -> None:
    payload = {"matchId": match_id, "round": round_number, "season": season}
    if dry_run:
        print(f"  [dry-run] would invoke scoring for {match_id}")
        return

    client = boto3.client("lambda", region_name=REGION)
    resp = client.invoke(
        FunctionName=SCORING_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    status = resp["StatusCode"]
    fn_error = resp.get("FunctionError")
    if fn_error:
        body = resp["Payload"].read().decode()
        print(f"  ERROR {match_id}: {fn_error} — {body}")
    else:
        print(f"  OK    {match_id} (HTTP {status})")


def main():
    parser = argparse.ArgumentParser(description="Score all matches in a round")
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    match_ids = get_match_ids(args.round, args.season)
    if not match_ids:
        print(f"No predictions found for round {args.round} season {args.season}")
        return

    print(f"Round {args.round} — {len(match_ids)} matches:")
    for mid in match_ids:
        print(f"  {mid}")

    print()
    for mid in match_ids:
        invoke_scoring(mid, args.round, args.season, args.dry_run)
        if not args.dry_run:
            time.sleep(1)  # avoid Lambda throttling


if __name__ == "__main__":
    main()
