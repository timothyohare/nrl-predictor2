"""AWS Lambda entry point for the v2 multi-agent NRL predictor."""
import json
import logging
import os
from datetime import datetime, timezone

import boto3

from agent.budget import BudgetExceeded, check_budget
from agent.graph import get_app

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BUDGET_THRESHOLD_USD = float(os.environ.get("BUDGET_THRESHOLD_USD", "50.0"))
PROMPT_VERSION = "v2.0"


def get_api_key() -> str:
    """Fetch Anthropic API key from Secrets Manager (cached within process lifetime)."""
    if not hasattr(get_api_key, "_key"):
        secret = boto3.client("secretsmanager").get_secret_value(
            SecretId="nrl-predictor/anthropic-api-key"
        )
        get_api_key._key = secret["SecretString"]
    return get_api_key._key


def load_match_context(match_id: str, round_number: int, season: int) -> dict:
    """Assemble match context from DynamoDB for the agent state."""
    ddb = boto3.resource("dynamodb")
    teams_table = ddb.Table(os.environ["TEAMS_TABLE"])

    # Load team sheet (home + away combined entry)
    response = teams_table.get_item(Key={"teamId": match_id, "round": str(round_number)})
    sheet = response.get("Item", {})

    # Load ladder for quick position lookup
    ladder_resp = teams_table.get_item(Key={"teamId": f"ladder#{season}", "round": "current"})
    ladder_item = ladder_resp.get("Item", {})
    positions = {p["team"]: int(p["position"]) for p in ladder_item.get("positions", [])}

    home_team = sheet.get("homeTeam", "")
    away_team = sheet.get("awayTeam", "")

    return {
        "match_id": match_id,
        "round_number": round_number,
        "season": season,
        "home_team": home_team,
        "away_team": away_team,
        "venue": sheet.get("venue", ""),
        "kick_off": sheet.get("kickOff", ""),
        "is_finals": round_number >= 27,
        "home_ladder_pos": positions.get(home_team),
        "away_ladder_pos": positions.get(away_team),
        "spine_injuries": [],  # populated by agent via get_injury_list tool
        "team_sheets": {
            "home": sheet.get("homePlayers", []),
            "away": sheet.get("awayPlayers", []),
        },
    }


def write_prediction(match_id: str, round_number: int, season: int, state: dict, generation: int = 1) -> None:
    """Write the final prediction + extended fields to DynamoDB."""
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(os.environ["PREDICTIONS_TABLE"])

    final = state["final_prediction"]
    extended = state.get("extended")
    generated_at = datetime.now(timezone.utc).isoformat()

    item = {
        "matchId": match_id,
        "generatedAt": generated_at,
        "roundNumber": round_number,
        "season": season,
        "status": "OK",
        "generation": generation,
        "prompt_version": PROMPT_VERSION,

        # Core prediction (from judge)
        "predicted_winner": final.predicted_winner,
        "predicted_margin": final.predicted_margin,
        "confidence": final.confidence,
        "key_factors": final.key_factors,
        "reasoning": final.reasoning,
        "judge_rationale": final.judge_rationale,

        # Multi-agent metadata
        "agent_difficulty": state.get("difficulty", "CONTESTED"),
        "difficulty_rationale": state.get("difficulty_rationale", ""),
        "primary_accepted": final.accepted_primary,
        "challenge_strength": state["challenge"].challenge_strength,
        "primary_reasoning": state["primary_prediction"].reasoning,
    }

    if extended:
        item.update({
            "first_try_candidates": [c.model_dump() for c in extended.first_try_scorer.candidates],
            "margin_bracket": extended.margin_bracket,
            "key_player_to_watch": extended.key_player_to_watch,
            "upset_probability": str(extended.upset_probability),
        })

    table.put_item(Item=item)
    logger.info("Wrote prediction for %s: %s by %d (%s)", match_id, final.predicted_winner, final.predicted_margin, final.confidence)


def write_trace(match_id: str, generated_at: str, state: dict) -> None:
    """Write the full agent trace to the agent_traces table."""
    traces_table_name = os.environ.get("AGENT_TRACES_TABLE")
    if not traces_table_name:
        return
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(traces_table_name)
    table.put_item(Item={
        "matchId": match_id,
        "generatedAt": generated_at,
        "trace_entries": state.get("agent_trace", []),
        "difficulty": state.get("difficulty"),
        "primary_model": state.get("primary_model"),
    })


def lambda_handler(event: dict, context) -> dict:
    match_id = event["matchId"]
    round_number = int(event["round"])
    season = int(event.get("season", 2026))
    generation = int(event.get("generation", 1))

    logger.info("Starting v2 prediction for %s round %d", match_id, round_number)

    try:
        check_budget(BUDGET_THRESHOLD_USD)
    except BudgetExceeded as e:
        logger.warning("Budget exceeded: %s — skipping prediction for %s", e, match_id)
        return {"status": "BUDGET_EXCEEDED", "matchId": match_id}

    match_context = load_match_context(match_id, round_number, season)

    initial_state = {
        "match_id": match_id,
        "round_number": round_number,
        "season": season,
        "match_context": match_context,
        "agent_trace": [],
    }

    app = get_app()
    result = app.invoke(initial_state)

    generated_at = datetime.now(timezone.utc).isoformat()
    write_prediction(match_id, round_number, season, result, generation)
    write_trace(match_id, generated_at, result)

    return {
        "status": "OK",
        "matchId": match_id,
        "winner": result["final_prediction"].predicted_winner,
        "margin": result["final_prediction"].predicted_margin,
        "confidence": result["final_prediction"].confidence,
        "difficulty": result.get("difficulty"),
        "challenge_strength": result["challenge"].challenge_strength,
    }
