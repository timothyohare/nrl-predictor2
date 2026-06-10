"""Trap game detection — identifies schedule context that favours upsets."""
import os

import boto3
from langchain_core.tools import tool

_DEAD_RUBBER_MIN_ROUND = 18
_TRAP_THRESHOLD = 2.0


def _get_ladder_positions(season: int, teams_table) -> dict[str, int]:
    response = teams_table.get_item(Key={"teamId": f"ladder#{season}", "round": "current"})
    item = response.get("Item")
    if not item:
        return {}
    return {p["team"]: int(p["position"]) for p in item.get("positions", [])}


def _get_previous_result(team: str, results_table) -> dict | None:
    response = results_table.scan(
        FilterExpression="homeTeam = :t OR awayTeam = :t",
        ExpressionAttributeValues={":t": team},
    )
    items = response.get("Items", [])
    if not items:
        return None
    items.sort(key=lambda x: x.get("scoredAt", ""), reverse=True)
    return items[0]


def _get_earlier_meetings(home_team: str, away_team: str, current_match_id: str, results_table) -> list[dict]:
    response = results_table.scan(
        FilterExpression="(homeTeam = :a AND awayTeam = :b) OR (homeTeam = :b AND awayTeam = :a)",
        ExpressionAttributeValues={":a": home_team, ":b": away_team},
    )
    return [i for i in response.get("Items", []) if i.get("matchId") != current_match_id]


def _ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _check_emotional_letdown(team: str, results_table) -> dict | None:
    last = _get_previous_result(team, results_table)
    if not last:
        return None
    winner = last.get("winner")
    margin = int(last.get("margin", 0))
    if winner == team and margin >= 20:
        loser = last["awayTeam"] if last["homeTeam"] == team else last["homeTeam"]
        return {"type": "emotional_letdown", "points": 1.0, "detail": f"{team} won last game by {margin} points (beat {loser})"}
    return None


def _check_dead_rubber(favourite: str, underdog: str, round_number: int, ladder: dict) -> dict | None:
    if round_number < _DEAD_RUBBER_MIN_ROUND:
        return None
    fav_pos = ladder.get(favourite, 17)
    dog_pos = ladder.get(underdog, 17)
    if fav_pos <= 4 and 7 <= dog_pos <= 10:
        return {"type": "dead_rubber", "points": 1.5, "detail": f"{favourite} ({fav_pos}{_ordinal(fav_pos)}) has top-4 secured; {underdog} ({dog_pos}{_ordinal(dog_pos)}) fighting for finals"}
    return None


def _check_revenge(home_team: str, away_team: str, match_id: str, ladder: dict, results_table) -> dict | None:
    fav_pos = ladder.get(home_team, 17)
    dog_pos = ladder.get(away_team, 17)
    favourite = home_team if fav_pos < dog_pos else away_team
    underdog = away_team if favourite == home_team else home_team
    meetings = _get_earlier_meetings(home_team, away_team, match_id, results_table)
    for m in meetings:
        if m.get("winner") == favourite and int(m.get("margin", 0)) < 8:
            return {"type": "revenge_game", "points": 0.5, "detail": f"{underdog} lost to {favourite} by {m.get('margin')} earlier this season"}
    return None


def _detect_trap_game(match_id: str, round_number: int, season: int, home_team: str, away_team: str, teams_table=None, results_table=None) -> dict:
    t_tbl = teams_table or boto3.resource("dynamodb").Table(os.environ["TEAMS_TABLE"])
    r_tbl = results_table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    ladder = _get_ladder_positions(season, t_tbl)
    home_pos = ladder.get(home_team, 17)
    away_pos = ladder.get(away_team, 17)
    favourite = home_team if home_pos < away_pos else away_team
    underdog = away_team if favourite == home_team else home_team
    indicators = []
    letdown = _check_emotional_letdown(favourite, r_tbl)
    if letdown:
        indicators.append(letdown)
    dead = _check_dead_rubber(favourite, underdog, round_number, ladder)
    if dead:
        indicators.append(dead)
    revenge = _check_revenge(home_team, away_team, match_id, ladder, r_tbl)
    if revenge:
        indicators.append(revenge)
    trap_score = sum(i["points"] for i in indicators)
    is_trap = trap_score >= _TRAP_THRESHOLD
    result = {"trap_score": round(trap_score, 1), "is_trap_game": is_trap, "indicators": indicators, "favourite": favourite, "underdog": underdog}
    if is_trap:
        result["recommendation"] = f"Consider downgrading {favourite} confidence. Trap score {trap_score:.1f}/5."
    return result


@tool
def detect_trap_game(match_id: str, round_number: int, season: int, home_team: str, away_team: str) -> dict:
    """Analyses schedule context to detect trap game conditions (sandwich games, letdowns, dead rubbers, revenge games)."""
    return _detect_trap_game(match_id=match_id, round_number=round_number, season=season, home_team=home_team, away_team=away_team)
