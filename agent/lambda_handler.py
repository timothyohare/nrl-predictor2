"""AWS Lambda entry point for the v2 multi-agent NRL predictor."""
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from agent.budget import BudgetExceeded, check_budget
from agent.graph import get_app
from common.teams import to_slug

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BUDGET_THRESHOLD_USD = float(os.environ.get("BUDGET_THRESHOLD_USD", "50.0"))
PROMPT_VERSION = "v2.0"


def _ddb_safe(obj):
    """Recursively convert floats to Decimal so boto3 can serialise the item.

    The DynamoDB resource client rejects Python floats (e.g. nested
    ``first_try_candidates[*].probability``); they must be Decimal. Using
    ``Decimal(str(x))`` avoids binary float-precision noise.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, list):
        return [_ddb_safe(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _ddb_safe(v) for k, v in obj.items()}
    return obj


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

    # Load ladder for quick position lookup (key positions on the canonical slug)
    ladder_resp = teams_table.get_item(Key={"teamId": f"ladder#{season}", "round": "current"})
    ladder_item = ladder_resp.get("Item", {})
    positions = {
        to_slug(p.get("team") or p.get("team_name", "")): int(p["position"])
        for p in ladder_item.get("positions", [])
    }

    home_team = to_slug(sheet.get("homeTeam", ""))
    away_team = to_slug(sheet.get("awayTeam", ""))

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


def assess_data_completeness(match_context: dict) -> list[str]:
    """Return a list of missing essential inputs; empty means OK to predict.

    The agent produces near-random output when the structured data layer is empty.
    In round 17 every match ran with no team sheet, so ``recent_form``/``head_to_head``
    found nothing (the agent fell back to full team names off web_search, which never
    match the short names stored in the results table) and the agent predicted blind.
    Gate on the inputs the prediction actually depends on rather than burning five LLM
    calls to produce a guess off an empty context.
    """
    missing: list[str] = []
    if not match_context.get("home_team") or not match_context.get("away_team"):
        missing.append("team names")
    sheets = match_context.get("team_sheets", {})
    if not sheets.get("home"):
        missing.append("home team sheet")
    if not sheets.get("away"):
        missing.append("away team sheet")
    return missing


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

        # Core prediction (from judge) — team identity stored as canonical slug
        "predicted_winner": to_slug(final.predicted_winner),
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
        candidates = []
        for c in extended.first_try_scorer.candidates:
            cd = c.model_dump()
            cd["team"] = to_slug(cd.get("team", ""))
            candidates.append(cd)
        item.update({
            "first_try_candidates": candidates,
            "margin_bracket": extended.margin_bracket,
            "key_player_to_watch": extended.key_player_to_watch,
            "upset_probability": str(extended.upset_probability),
        })

    table.put_item(Item=_ddb_safe(item))
    logger.info("Wrote prediction for %s: %s by %d (%s)", match_id, final.predicted_winner, final.predicted_margin, final.confidence)


def write_trace(match_id: str, generated_at: str, state: dict) -> None:
    """Write the full agent trace to the agent_traces table."""
    traces_table_name = os.environ.get("AGENT_TRACES_TABLE")
    if not traces_table_name:
        return
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(traces_table_name)
    table.put_item(Item=_ddb_safe({
        "matchId": match_id,
        "generatedAt": generated_at,
        "trace_entries": state.get("agent_trace", []),
        "difficulty": state.get("difficulty"),
        "primary_model": state.get("primary_model"),
    }))


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

    missing = assess_data_completeness(match_context)
    if missing:
        logger.warning(
            "Insufficient data for %s round %d: missing %s — skipping prediction",
            match_id, round_number, ", ".join(missing),
        )
        return {"status": "INSUFFICIENT_DATA", "matchId": match_id, "missing": missing}

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
