import json
import logging
import os
from datetime import datetime, timezone

import anthropic
import boto3

from agent.tools.web_search import web_search
from retrospective.prompt import build_retrospective_prompt

logger = logging.getLogger(__name__)
_MODEL = "claude-sonnet-4-6"


def _get_anthropic_client() -> anthropic.Anthropic:
    secret = boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["ANTHROPIC_SECRET_ARN"]
    )
    raw = secret["SecretString"]
    api_key = json.loads(raw)["api_key"] if raw.startswith("{") else raw
    return anthropic.Anthropic(api_key=api_key)


def generate_retrospective(
    match_id: str,
    round_number: int,
    season: int,
    predictions_table,
    results_table,
    retrospectives_table,
    match_stats_table,
    anthropic_client=None,
    tavily_client=None,
) -> dict:
    # Idempotency: skip if already generated
    existing = retrospectives_table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        Limit=1,
    )
    if existing.get("Items"):
        logger.info("Retrospective already exists for %s, skipping", match_id)
        return existing["Items"][0]

    pred_resp = predictions_table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        ScanIndexForward=False,
        Limit=1,
    )
    prediction = pred_resp["Items"][0]

    result_resp = results_table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        ScanIndexForward=False,
        Limit=1,
    )
    result = result_resp["Items"][0]

    home_team = result.get("homeTeam", "")
    away_team = result.get("awayTeam", "")
    actual_winner = result["winner"]
    home_score = int(result["homeScore"])
    away_score = int(result["awayScore"])
    actual_margin = int(result["margin"])

    # Web search for post-match stats — store regardless of retrospective outcome
    query = (
        f"{home_team} vs {away_team} NRL Round {round_number} {season} "
        "match report try scorers result"
    )
    match_stats: list[str] = []
    try:
        match_stats = web_search(query, client=tavily_client)
        logger.info("Web search returned %d results for %s", len(match_stats), match_id)
    except Exception as e:
        logger.warning("Web search failed for %s: %s", match_id, e)

    scraped_at = datetime.now(timezone.utc).isoformat()
    match_stats_table.put_item(Item={
        "matchId": match_id,
        "scraped_at": scraped_at,
        "source": "web_search",
        "query": query,
        "stats": match_stats,
        "roundNumber": round_number,
        "season": season,
    })

    prompt = build_retrospective_prompt(
        home_team=home_team,
        away_team=away_team,
        predicted_winner=prediction["predicted_winner"],
        predicted_margin=int(prediction.get("predicted_margin", 0)),
        confidence=prediction.get("confidence", "MEDIUM"),
        key_factors=prediction.get("key_factors", []),
        reasoning=prediction.get("reasoning", ""),
        actual_winner=actual_winner,
        home_score=home_score,
        away_score=away_score,
        actual_margin=actual_margin,
        match_stats=match_stats,
    )

    client = anthropic_client or _get_anthropic_client()
    response = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text_block = next((b for b in response.content if getattr(b, "type", None) == "text"), None)
    if text_block is None:
        raise ValueError(f"No text block in Claude response for {match_id}")
    raw = text_block.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1].lstrip("json").strip()
    parsed = json.loads(raw)

    generated_at = datetime.now(timezone.utc).isoformat()
    item = {
        "matchId": match_id,
        "generatedAt": generated_at,
        "verdict": parsed["verdict"],
        "hit_factors": parsed.get("hit_factors", []),
        "missed_factors": parsed.get("missed_factors", []),
        "what_actually_happened": parsed.get("what_actually_happened", ""),
        "lesson": parsed.get("lesson", ""),
        "model_used": _MODEL,
        "prompt_version": prediction.get("prompt_version", "unknown"),
        "roundNumber": round_number,
        "season": season,
    }
    retrospectives_table.put_item(Item=item)
    logger.info("Retrospective written for %s", match_id)
    return item
