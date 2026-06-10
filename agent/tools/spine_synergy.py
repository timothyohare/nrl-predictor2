"""Spine synergy tool — analyses how many games a team's spine has played together."""
import os

import boto3
from langchain_core.tools import tool

_SPINE_NUMBERS = {1, 6, 7, 9}
_ESTABLISHED_THRESHOLD = 5


def _extract_spine(players: list[dict]) -> dict[int, str]:
    spine = {}
    for p in players:
        num = int(p.get("jersey_number", 0))
        if num in _SPINE_NUMBERS:
            spine[num] = p.get("last_name", "Unknown")
    return spine


def _analyse_team(team: str, current_spine: dict[int, str], current_round: int, teams_table, results_table) -> dict:
    response = teams_table.scan(
        FilterExpression="(homeTeam = :t OR awayTeam = :t) AND attribute_exists(homePlayers)",
        ExpressionAttributeValues={":t": team},
    )
    historical = [i for i in response.get("Items", []) if _safe_round(i) < current_round]
    full_spine_games = full_spine_wins = halves_games = halves_wins = 0
    current_halves = {k: v for k, v in current_spine.items() if k in (6, 7)}
    for sheet in historical:
        players = sheet.get("homePlayers", []) if sheet.get("homeTeam") == team else sheet.get("awayPlayers", [])
        hist_spine = _extract_spine(players)
        full_match = all(hist_spine.get(n) == current_spine.get(n) for n in _SPINE_NUMBERS)
        halves_match = all(hist_spine.get(n) == current_halves.get(n) for n in (6, 7))
        match_id = sheet.get("teamId", "")
        res = results_table.query(KeyConditionExpression="matchId = :m", ExpressionAttributeValues={":m": match_id}, Limit=1).get("Items", [])
        won = res[0].get("winner") == team if res else False
        if full_match:
            full_spine_games += 1
            if won:
                full_spine_wins += 1
        if halves_match:
            halves_games += 1
            if won:
                halves_wins += 1
    is_established = full_spine_games >= _ESTABLISHED_THRESHOLD
    flags = []
    spine_names = "-".join(current_spine.get(n, "?") for n in sorted(_SPINE_NUMBERS))
    if not is_established:
        flags.append(f"Spine {spine_names} has only {full_spine_games} games together (threshold: {_ESTABLISHED_THRESHOLD})")
    if halves_games < _ESTABLISHED_THRESHOLD:
        halves_names = f"{current_spine.get(6, '?')}-{current_spine.get(7, '?')}"
        flags.append(f"Halves pairing {halves_names} is relatively new ({halves_games} games)")
    return {
        "team": team,
        "spine": {"fullback": current_spine.get(1, "Unknown"), "five_eighth": current_spine.get(6, "Unknown"), "halfback": current_spine.get(7, "Unknown"), "hooker": current_spine.get(9, "Unknown")},
        "full_spine_games_together": full_spine_games,
        "full_spine_win_rate": round(full_spine_wins / full_spine_games, 2) if full_spine_games > 0 else 0,
        "halves_games_together": halves_games,
        "halves_win_rate": round(halves_wins / halves_games, 2) if halves_games > 0 else 0,
        "is_established": is_established,
        "flags": flags,
    }


def _safe_round(item: dict) -> int:
    try:
        return int(item.get("round", "0"))
    except (ValueError, TypeError):
        return 0


def _get_spine_synergy(match_id: str, round_number: int, teams_table=None, results_table=None) -> dict:
    t_tbl = teams_table or boto3.resource("dynamodb").Table(os.environ["TEAMS_TABLE"])
    r_tbl = results_table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    response = t_tbl.get_item(Key={"teamId": match_id, "round": str(round_number)})
    item = response.get("Item")
    if not item:
        return {"error": f"No team sheet found for {match_id} round {round_number}"}
    home_team = item.get("homeTeam", "Unknown")
    away_team = item.get("awayTeam", "Unknown")
    home_spine = _extract_spine(item.get("homePlayers", []))
    away_spine = _extract_spine(item.get("awayPlayers", []))
    home_analysis = _analyse_team(home_team, home_spine, round_number, t_tbl, r_tbl)
    away_analysis = _analyse_team(away_team, away_spine, round_number, t_tbl, r_tbl)
    hg = home_analysis["full_spine_games_together"]
    ag = away_analysis["full_spine_games_together"]
    if hg > ag + 3:
        edge = f"{home_team} have a significant spine synergy advantage ({hg} games together vs {ag})"
    elif ag > hg + 3:
        edge = f"{away_team} have a significant spine synergy advantage ({ag} games together vs {hg})"
    elif hg > ag:
        edge = f"{home_team} have a slight spine synergy edge ({hg} vs {ag} games together)"
    elif ag > hg:
        edge = f"{away_team} have a slight spine synergy edge ({ag} vs {hg} games together)"
    else:
        edge = f"Even spine synergy ({hg} games together each)"
    return {"home_team": home_analysis, "away_team": away_analysis, "synergy_edge": edge}


@tool
def get_spine_synergy(match_id: str, round_number: int) -> dict:
    """Analyses how many games each team's spine (1,6,7,9) have played together this season."""
    return _get_spine_synergy(match_id=match_id, round_number=round_number)
