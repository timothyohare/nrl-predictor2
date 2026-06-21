#!/usr/bin/env python3
"""Derive round numbers for scripts/daily_update.sh from DynamoDB.

Subcommands:
  current          Print the highest round that has predictions — the round currently
                   being predicted. Prints nothing if the predictions table is empty.
  scorable R...    Print the highest of the given rounds whose matches have FullTime
                   results in the results table (i.e. the last completed round). Prints
                   nothing if none are complete, so the caller can skip scoring.

Read-only. "current" reads the highest roundNumber in the predictions table.
"scorable" reads completion straight from the results table: a round is complete
when it has FullTime rows keyed by a round-prefixed slug ("round-16-broncos-v-roosters").
We deliberately do NOT match on team-pair alone — round-less keys ("broncos-v-roosters")
accumulate across every meeting, so a round-blind join falsely marks an unplayed round
complete against an earlier fixture (this is what produced bogus round-17 "results").
"""
import argparse
import os

import boto3

from common.match_id import round_of

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-2"


def cmd_current(_args) -> None:
    table = boto3.resource("dynamodb", region_name=REGION).Table("predictions")
    highest = None
    kwargs = {"ProjectionExpression": "roundNumber"}
    while True:
        resp = table.scan(**kwargs)
        for item in resp.get("Items", []):
            try:
                rnd = int(item["roundNumber"])
            except (KeyError, TypeError, ValueError):
                continue
            if highest is None or rnd > highest:
                highest = rnd
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    if highest is not None:
        print(highest)


def _completed_rounds() -> set[int]:
    table = boto3.resource("dynamodb", region_name=REGION).Table("results")
    done: set[int] = set()
    kwargs = {"ProjectionExpression": "matchId, matchState"}
    while True:
        resp = table.scan(**kwargs)
        for item in resp.get("Items", []):
            if item.get("matchState") != "FullTime":
                continue
            rnd = round_of(str(item.get("matchId", "")))
            if rnd is not None:
                done.add(rnd)
        if "LastEvaluatedKey" not in resp:
            return done
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def cmd_scorable(args) -> None:
    done = _completed_rounds()
    candidates = [r for r in {int(r) for r in args.rounds} if r in done]
    if candidates:
        print(max(candidates))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("current").set_defaults(func=cmd_current)
    p_score = sub.add_parser("scorable")
    p_score.add_argument("rounds", nargs="+", type=int)
    p_score.set_defaults(func=cmd_scorable)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
