#!/usr/bin/env python3
"""Run the v2 agent Lambda locally — no deploy, no Lambda, no waiting on CDK.

Drives the real ``agent.lambda_handler.lambda_handler`` against either in-process
moto DynamoDB (default, hermetic, free) or real AWS, with either mocked LLMs
(default, deterministic) or the real Anthropic API. This is the fast pre-deploy
loop: the float→Decimal write crash and the extended-node schema crash would both
have surfaced here in seconds/minutes instead of via a 56s CDK deploy + a billed
~190s live invoke.

Modes
-----
            LLM = mock (default)              LLM = real (--real-llm)
moto (def)  free smoke of the full read→      real Anthropic against seeded moto
            graph→write→trace path; catches    tables (tools see sparse data)
            serialization/wiring bugs
--aws       real DynamoDB, mock graph          THE debug loop: the exact deployed
            (rarely useful)                    handler, real data, real LLM, locally

Examples
--------
    python3 -m tools.local_invoke                          # moto + mock (free)
    python3 -m tools.local_invoke --real-llm               # moto + real Anthropic
    python3 -m tools.local_invoke --aws --real-llm \
        --match round-15-warriors-v-sharks --round 15      # real data + real LLM, local

--real-llm needs ANTHROPIC_API_KEY in the environment (and TAVILY_API_KEY if the
agent uses web search). --aws uses your real DynamoDB and ap-southeast-2 creds.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tables to stand up under moto, with their prod key schemas. Keyed by the env
# var the handler/tools read for the table name.
TABLES = {
    "TEAMS_TABLE": ("teams", "teamId", "round"),
    "RESULTS_TABLE": ("results", "matchId", "scoredAt"),
    "INJURIES_TABLE": ("injuries", "pk", "sk"),
    "WEATHER_TABLE": ("weather", "pk", "sk"),
    "CLAUDE_USAGE_TABLE": ("claude_usage", "yearMonth", "invokedAt"),
    "RETROSPECTIVES_TABLE": ("retrospectives", "matchId", "generatedAt"),
    "PREDICTIONS_TABLE": ("predictions", "matchId", "generatedAt"),
    "AGENT_TRACES_TABLE": ("agent_traces", "matchId", "generatedAt"),
}
RAW_BUCKET = "nrl-predictor-raw-scrapes"


# ── env ──────────────────────────────────────────────────────────────────────

def set_env(real_aws: bool) -> None:
    for env_name, (table, _, _) in TABLES.items():
        os.environ[env_name] = table
    os.environ["RAW_BUCKET"] = RAW_BUCKET
    os.environ.setdefault("BUDGET_THRESHOLD_USD", "50.0")
    os.environ["AWS_REGION"] = "ap-southeast-2" if real_aws else "us-east-1"
    os.environ["AWS_DEFAULT_REGION"] = os.environ["AWS_REGION"]
    if not real_aws:
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")


# ── moto setup + seed ────────────────────────────────────────────────────────

def create_tables(ddb) -> None:
    for table, hash_key, range_key in TABLES.values():
        ddb.create_table(
            TableName=table,
            KeySchema=[
                {"AttributeName": hash_key, "KeyType": "HASH"},
                {"AttributeName": range_key, "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": hash_key, "AttributeType": "S"},
                {"AttributeName": range_key, "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )


def teams_from_slug(match_id: str) -> tuple[str, str]:
    slug = match_id.split("-", 2)[-1] if match_id.startswith("round-") else match_id
    parts = slug.split("-v-")
    titled = [p.replace("-", " ").title() for p in parts] + ["Home", "Away"]
    return titled[0], titled[1]


def seed(ddb, match_id: str, round_number: int, season: int) -> None:
    home, away = teams_from_slug(match_id)
    players = [{"name": f"{home} Player {i}", "number": i, "position": "back"} for i in range(1, 4)]
    teams = ddb.Table("teams")
    teams.put_item(Item={
        "teamId": match_id, "round": str(round_number),
        "homeTeam": home, "awayTeam": away,
        "venue": "Local Stadium", "kickOff": "2026-06-14T19:35:00+10:00",
        "matchState": "Pre", "homePlayers": players, "awayPlayers": players,
    })
    teams.put_item(Item={
        "teamId": f"ladder#{season}", "round": "current",
        "positions": [{"team": home, "position": 3}, {"team": away, "position": 9}],
    })
    ddb.Table("results").put_item(Item={
        "matchId": match_id.split("-", 2)[-1], "scoredAt": "2026-06-13T00:00:00+00:00",
        "winner": home, "homeTeam": home, "awayTeam": away,
        "homeScore": 24, "awayScore": 12, "margin": 12, "matchState": "FullTime",
    })


def seed_secrets() -> None:
    sm = boto3.client("secretsmanager")
    for name, env in (("nrl-predictor/anthropic-api-key", "ANTHROPIC_API_KEY"),
                      ("nrl-predictor/tavily-api-key", "TAVILY_API_KEY")):
        if os.environ.get(env):
            sm.create_secret(Name=name, SecretString=os.environ[env])


# ── mocked LLMs (reuse the integration-test shapes) ──────────────────────────

def mock_graph():
    from langchain_core.messages import AIMessage

    from agent.graph import build_graph
    from agent.state import (
        Challenge, ExtendedPrediction, FinalPrediction, FirstTryPrediction,
        FirstTryScorerCandidate, PrimaryPrediction, RouterOutput,
    )
    from scrapers.shared.constants import HAIKU_MODEL, SONNET_MODEL

    def structured(value):
        llm = MagicMock()
        llm.with_structured_output.return_value.invoke.return_value = value
        return llm

    def primary(value):
        """Primary node calls BOTH bind_tools (ReAct loop) and with_structured_output."""
        no_tool_calls = AIMessage(content="analysis complete")
        no_tool_calls.tool_calls = []  # break the loop immediately
        llm = MagicMock()
        llm.bind_tools.return_value.invoke.return_value = no_tool_calls
        llm.with_structured_output.return_value.invoke.return_value = value
        return llm

    return build_graph(
        router_llm=structured(RouterOutput(
            difficulty="CONTESTED", rationale="Close on form.",
            primary_model=HAIKU_MODEL, challenger_model=SONNET_MODEL)),
        primary_llm=primary(PrimaryPrediction(
            predicted_winner="Warriors", predicted_margin=8, confidence="MEDIUM",
            key_factors=["Home form", "Spine fit"], reasoning="Warriors at home.")),
        challenger_llm=structured(Challenge(
            counter_winner="Sharks", counter_margin=4, challenge_strength="MODERATE",
            key_counterpoints=["Away record", "H2H"], challenge_reasoning="Sharks live.")),
        judge_llm=structured(FinalPrediction(
            predicted_winner="Warriors", predicted_margin=6, confidence="MEDIUM",
            accepted_primary=True, judge_rationale="Primary held.",
            key_factors=["Home form", "Spine"], reasoning="Narrow Warriors win.")),
        extended_llm=structured(ExtendedPrediction(
            first_try_scorer=FirstTryPrediction(candidates=[
                FirstTryScorerCandidate(player_name="Montoya", team="Warriors",
                                        position="winger", probability=0.18, rationale="Edge")]),
            margin_bracket="6-12", key_player_to_watch="Metcalf — spark",
            upset_probability=0.28)),  # floats here exercise the _ddb_safe write path
    )


# ── output ───────────────────────────────────────────────────────────────────

def _dec(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o))


def dump_written(match_id: str) -> None:
    ddb = boto3.resource("dynamodb")
    pred = ddb.Table("predictions").query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
    ).get("Items", [])
    trace = ddb.Table("agent_traces").query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
    ).get("Items", [])
    print(f"\n── predictions rows for {match_id}: {len(pred)} ──")
    if pred:
        latest = max(pred, key=lambda p: p.get("generatedAt", ""))
        print(json.dumps(latest, indent=2, default=_dec))
    print(f"\n── agent_traces rows for {match_id}: {len(trace)} ──")
    if trace:
        latest = max(trace, key=lambda t: t.get("generatedAt", ""))
        entries = latest.get("trace_entries", [])
        print(f"  difficulty={latest.get('difficulty')} primary_model={latest.get('primary_model')} "
              f"trace_entries={len(entries)}")


# ── run ──────────────────────────────────────────────────────────────────────

def run(args) -> int:
    set_env(real_aws=args.aws)

    with contextlib.ExitStack() as stack:
        if not args.aws:
            from moto import mock_aws
            stack.enter_context(mock_aws())
            ddb = boto3.resource("dynamodb")
            create_tables(ddb)
            seed(ddb, args.match, args.round, args.season)
            boto3.client("s3").create_bucket(
                Bucket=RAW_BUCKET,
                CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
            )
            if args.real_llm:
                seed_secrets()

        import agent.lambda_handler as lh
        if not args.real_llm:
            graph = mock_graph()
            lh.get_app = lambda: graph  # noqa: E731 — inject mocked pipeline

        backend = "real-AWS" if args.aws else "moto"
        brain = "real-LLM" if args.real_llm else "mock-LLM"
        print(f"▶ local invoke [{backend} · {brain}] {args.match} round {args.round}\n")

        event = {"matchId": args.match, "round": args.round, "season": args.season}
        result = lh.lambda_handler(event, None)
        print("handler returned:", json.dumps(result, default=_dec))
        if result.get("status") == "OK":
            dump_written(args.match)
        return 0 if result.get("status") == "OK" else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="local_invoke", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--match", default="round-15-warriors-v-sharks", help="matchId")
    ap.add_argument("--round", type=int, default=15)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--real-llm", action="store_true", help="use the real Anthropic API")
    ap.add_argument("--aws", action="store_true", help="use real DynamoDB instead of moto")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
