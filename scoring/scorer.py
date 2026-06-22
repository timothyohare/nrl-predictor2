from dataclasses import dataclass

from common.predictions import latest_before_kickoff
from common.teams import to_slug

_CONFIDENCE_PROB = {"HIGH": 0.85, "MEDIUM": 0.65, "LOW": 0.55}


@dataclass
class ScoredResult:
    match_id: str
    correct_pick: bool
    predicted_margin_error: int
    within_6_pts: bool
    within_12_pts: bool
    brier_component: float
    confidence: str
    prompt_version: str


class ResultNotReady(Exception):
    """No (canonical) result row exists yet for this match — score later, don't crash."""


def score_prediction(match_id: str, results_table, predictions_table, kickoff=None) -> ScoredResult:
    result_resp = results_table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        ScanIndexForward=False,
        Limit=1,
    )
    if not result_resp["Items"]:
        raise ResultNotReady(f"No result row for {match_id}")
    result = result_resp["Items"][0]

    pred_resp = predictions_table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        ScanIndexForward=False,
    )
    ok_preds = [p for p in pred_resp["Items"] if p.get("status") == "OK"]
    if not ok_preds:
        raise ValueError(f"No OK prediction found for {match_id}")
    # Score the last prediction made BEFORE kickoff, not the latest overall — predictions get
    # regenerated post-kickoff, and scoring those would reward hindsight.
    prediction = latest_before_kickoff(ok_preds, kickoff)
    assert prediction is not None  # ok_preds is non-empty, guaranteed above

    actual_winner = result["winner"]
    actual_margin = int(result["margin"])
    predicted_winner = prediction["predicted_winner"]
    predicted_margin = int(prediction.get("predicted_margin", 0))
    confidence = prediction.get("confidence", "MEDIUM")
    prompt_version = prediction.get("prompt_version", "unknown")

    # Compare on canonical slug so mixed stored forms (nickname / slug) score correctly.
    correct = to_slug(predicted_winner) == to_slug(actual_winner)
    margin_error = abs(predicted_margin - actual_margin)
    p = _CONFIDENCE_PROB.get(confidence, 0.65)
    outcome = 1 if correct else 0
    brier = (p - outcome) ** 2

    return ScoredResult(
        match_id=match_id,
        correct_pick=correct,
        predicted_margin_error=margin_error,
        within_6_pts=margin_error <= 6,
        within_12_pts=margin_error <= 12,
        brier_component=round(brier, 6),
        confidence=confidence,
        prompt_version=prompt_version,
    )
