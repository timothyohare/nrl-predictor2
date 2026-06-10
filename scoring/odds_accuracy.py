from dataclasses import dataclass


@dataclass
class ScoredMarket:
    match_id: str
    correct_pick: bool
    predicted_margin_error: int
    within_6_pts: bool
    within_12_pts: bool
    brier_component: float
    market_favourite: str
    market_margin: float


def score_market(match_id: str, odds_table, results_table) -> ScoredMarket:
    """Score the betting market's accuracy for a single match."""
    odds_resp = odds_table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        ScanIndexForward=False,
    )
    if not odds_resp["Items"]:
        raise ValueError(f"No odds found for {match_id}")
    odds = odds_resp["Items"][0]

    result_resp = results_table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        ScanIndexForward=False,
        Limit=1,
    )
    result = result_resp["Items"][0]

    market_fav = odds["market_favourite"]
    market_margin = float(odds["market_margin"])
    actual_winner = result["winner"]
    actual_margin = int(result["margin"])

    correct = market_fav == actual_winner
    margin_error = abs(round(market_margin) - actual_margin)

    # Brier score using the implied probability of the market favourite
    home_team = result.get("homeTeam", "")
    if market_fav == home_team:
        p = float(odds["implied_home_prob"])
    else:
        p = float(odds["implied_away_prob"])
    outcome = 1 if correct else 0
    brier = round((p - outcome) ** 2, 6)

    return ScoredMarket(
        match_id=match_id,
        correct_pick=correct,
        predicted_margin_error=margin_error,
        within_6_pts=abs(market_margin - actual_margin) <= 6,
        within_12_pts=abs(market_margin - actual_margin) <= 12,
        brier_component=brier,
        market_favourite=market_fav,
        market_margin=market_margin,
    )


def find_outlier(match_id: str, odds_table, predictions_table) -> dict | None:
    """Return outlier info if prediction and market disagree; None if they agree or data is missing."""
    odds_resp = odds_table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        ScanIndexForward=False,
        Limit=1,
    )
    if not odds_resp["Items"]:
        return None
    odds = odds_resp["Items"][0]

    pred_resp = predictions_table.query(
        KeyConditionExpression="matchId = :m",
        ExpressionAttributeValues={":m": match_id},
        ScanIndexForward=False,
    )
    ok_preds = [p for p in pred_resp["Items"] if p.get("status") == "OK"]
    if not ok_preds:
        return None
    pred = ok_preds[0]

    market_fav = odds["market_favourite"]
    market_margin = float(odds["market_margin"])
    pred_winner = pred.get("predicted_winner", "")
    pred_margin = int(pred.get("predicted_margin", 0))

    if pred_winner != market_fav:
        return {
            "match_id": match_id,
            "reason": "winner_disagrees",
            "market_favourite": market_fav,
            "predicted_winner": pred_winner,
            "market_margin": market_margin,
            "predicted_margin": pred_margin,
        }
    if abs(pred_margin - market_margin) > 6:
        return {
            "match_id": match_id,
            "reason": "margin_diverges",
            "market_favourite": market_fav,
            "predicted_winner": pred_winner,
            "market_margin": market_margin,
            "predicted_margin": pred_margin,
        }
    return None
