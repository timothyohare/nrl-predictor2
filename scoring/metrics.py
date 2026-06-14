from dataclasses import dataclass
from decimal import Decimal
import logging


from scoring.odds_accuracy import score_market

logger = logging.getLogger(__name__)


@dataclass
class RoundMetrics:
    round_number: int
    season: int
    correct_picks: int
    total: int
    pick_rate: float
    mean_margin_error: float
    brier_score: float


def _write_metric(metrics_table, period: str, metric_name: str, value: float,
                  correct_picks: int | None = None, total: int | None = None) -> None:
    item: dict = {
        "period": period,
        "metricName": metric_name,
        "value": Decimal(str(round(value, 6))),
    }
    if correct_picks is not None:
        item["correct_picks"] = correct_picks
    if total is not None:
        item["total"] = total
    metrics_table.put_item(Item=item)


def _confidence_pick_rates(items: list[dict]) -> dict[str, tuple[int, int]]:
    """Returns {confidence_level: (correct, total)} for HIGH/MEDIUM/LOW."""
    buckets: dict[str, list[bool]] = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for item in items:
        conf = item.get("confidence", "")
        if conf in buckets:
            buckets[conf].append(bool(item.get("correct_pick")))
    return {k: (sum(v), len(v)) for k, v in buckets.items()}


def _prompt_version_pick_rates(items: list[dict]) -> dict[str, tuple[int, int]]:
    """Returns {prompt_version: (correct, total)}."""
    versions: dict[str, list[bool]] = {}
    for item in items:
        pv = item.get("prompt_version", "unknown")
        versions.setdefault(pv, []).append(bool(item.get("correct_pick")))
    return {k: (sum(v), len(v)) for k, v in versions.items()}


def aggregate_round(round_number: int, season: int, results_table, metrics_table) -> RoundMetrics:
    response = results_table.scan(
        FilterExpression="roundNumber = :r AND season = :s",
        ExpressionAttributeValues={":r": round_number, ":s": season},
    )
    items = response.get("Items", [])
    # Deduplicate: keep only scored items (those with correct_pick field)
    scored = [i for i in items if "correct_pick" in i]
    # Further deduplicate per matchId: keep most recent scoredAt
    by_match: dict[str, dict] = {}
    for item in scored:
        mid = item["matchId"]
        if mid not in by_match or item.get("scoredAt", "") > by_match[mid].get("scoredAt", ""):
            by_match[mid] = item
    items = list(by_match.values())

    total = len(items)
    if total == 0:
        return RoundMetrics(round_number, season, 0, 0, 0.0, 0.0, 0.0)

    correct = sum(1 for i in items if i.get("correct_pick"))
    margin_errors = [int(i.get("predicted_margin_error", 0)) for i in items]
    brier_components = [float(i.get("brier_component", 0)) for i in items]

    pick_rate = correct / total
    mean_margin = sum(margin_errors) / total
    brier = sum(brier_components) / total

    period = f"{season}-round-{round_number}"
    _write_metric(metrics_table, period, "pick_rate", pick_rate, correct, total)
    _write_metric(metrics_table, period, "mean_margin_error", mean_margin)
    _write_metric(metrics_table, period, "brier_score", brier)

    return RoundMetrics(
        round_number=round_number,
        season=season,
        correct_picks=correct,
        total=total,
        pick_rate=pick_rate,
        mean_margin_error=mean_margin,
        brier_score=brier,
    )


def aggregate_season(season: int, results_table, metrics_table) -> None:
    response = results_table.scan(
        FilterExpression="season = :s",
        ExpressionAttributeValues={":s": season},
    )
    items = response.get("Items", [])
    # Keep only scored items, deduplicated per matchId
    scored = [i for i in items if "correct_pick" in i]
    by_match: dict[str, dict] = {}
    for item in scored:
        mid = item["matchId"]
        if mid not in by_match or item.get("scoredAt", "") > by_match[mid].get("scoredAt", ""):
            by_match[mid] = item
    items = list(by_match.values())

    total = len(items)
    if total == 0:
        return

    correct = sum(1 for i in items if i.get("correct_pick"))
    margin_errors = [int(i.get("predicted_margin_error", 0)) for i in items]
    brier_components = [float(i.get("brier_component", 0)) for i in items]

    pick_rate = correct / total
    mean_margin = sum(margin_errors) / total
    brier = sum(brier_components) / total

    period = f"{season}-season"
    _write_metric(metrics_table, period, "pick_rate", pick_rate, correct, total)
    _write_metric(metrics_table, period, "mean_margin_error", mean_margin)
    _write_metric(metrics_table, period, "brier_score", brier)

    # Confidence calibration
    for conf, (conf_correct, conf_total) in _confidence_pick_rates(items).items():
        if conf_total > 0:
            _write_metric(
                metrics_table, period,
                f"pick_rate_{conf.lower()}_confidence",
                conf_correct / conf_total, conf_correct, conf_total,
            )

    # Prompt version calibration
    for pv, (pv_correct, pv_total) in _prompt_version_pick_rates(items).items():
        safe_pv = pv.replace(".", "_")
        _write_metric(
            metrics_table, period,
            f"pick_rate_prompt_{safe_pv}",
            pv_correct / pv_total, pv_correct, pv_total,
        )


def aggregate_market_season(season: int, odds_table, results_table, metrics_table) -> None:
    """Compute and persist betting market accuracy for the season."""
    odds_resp = odds_table.scan(
        FilterExpression="season = :s",
        ExpressionAttributeValues={":s": season},
    )
    odds_items = odds_resp.get("Items", [])
    # Deduplicate: most recent scraped odds per match
    by_match: dict[str, dict] = {}
    for item in odds_items:
        mid = item["matchId"]
        if mid not in by_match or item.get("scrapedAt", "") > by_match[mid].get("scrapedAt", ""):
            by_match[mid] = item

    if not by_match:
        return

    scored = []
    for match_id in by_match:
        try:
            scored.append(score_market(match_id, odds_table, results_table))
        except Exception:
            pass  # match not yet played or result missing

    total = len(scored)
    if total == 0:
        return

    correct = sum(1 for s in scored if s.correct_pick)
    margin_errors = [s.predicted_margin_error for s in scored]
    brier_components = [s.brier_component for s in scored]

    period = f"{season}-season"
    _write_metric(metrics_table, period, "market_pick_rate", correct / total, correct, total)
    _write_metric(metrics_table, period, "market_mean_margin_error", sum(margin_errors) / total)
    _write_metric(metrics_table, period, "market_brier_score", sum(brier_components) / total)
