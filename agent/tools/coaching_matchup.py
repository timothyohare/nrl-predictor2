"""Coaching matchup tool — returns coach-vs-coach record filtered to current tenures."""
import os

import boto3
from langchain_core.tools import tool

from common.teams import to_slug

COACH_MAP = {
    "Panthers": {"coach": "Ivan Cleary", "from": "2019-01-01"},
    "Storm": {"coach": "Craig Bellamy", "from": "2003-01-01"},
    "Roosters": {"coach": "Trent Robinson", "from": "2013-01-01"},
    "Broncos": {"coach": "Michael Maguire", "from": "2025-01-01"},
    "Sharks": {"coach": "Craig Fitzgibbon", "from": "2022-01-01"},
    "Cowboys": {"coach": "Todd Payten", "from": "2021-01-01"},
    "Bulldogs": {"coach": "Cameron Ciraldo", "from": "2023-01-01"},
    "Sea Eagles": {"coach": "Anthony Seibold", "from": "2023-01-01"},
    "Rabbitohs": {"coach": "Wayne Bennett", "from": "2025-01-01"},
    "Eels": {"coach": "Jason Ryles", "from": "2025-01-01"},
    "Knights": {"coach": "Adam O'Brien", "from": "2020-01-01"},
    "Raiders": {"coach": "Ricky Stuart", "from": "2014-01-01"},
    "Warriors": {"coach": "Andrew Webster", "from": "2023-01-01"},
    "Titans": {"coach": "Des Hasler", "from": "2024-01-01"},
    "Dragons": {"coach": "Shane Flanagan", "from": "2024-01-01"},
    "Dolphins": {"coach": "Kristian Woolf", "from": "2025-01-01"},
    "Wests Tigers": {"coach": "Benji Marshall", "from": "2024-01-01"},
}


def _get_coach(team: str) -> dict | None:
    slug = to_slug(team)
    for t, info in COACH_MAP.items():
        if to_slug(t) == slug:
            return {"team": t, **info}
    return None


def _get_coaching_matchup(team_a: str, team_b: str, table=None) -> dict:
    coach_a = _get_coach(team_a)
    coach_b = _get_coach(team_b)
    if not coach_a or not coach_b:
        missing = team_a if not coach_a else team_b
        return {"error": f"No coach found for {missing}", "coaches": COACH_MAP}
    tenure_start = max(coach_a["from"], coach_b["from"])
    tbl = table or boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    response = tbl.scan(
        FilterExpression="(homeTeam = :a AND awayTeam = :b) OR (homeTeam = :b AND awayTeam = :a)",
        ExpressionAttributeValues={":a": coach_a["team"], ":b": coach_b["team"]},
    )
    items = [i for i in response.get("Items", []) if i.get("scoredAt", "") >= tenure_start]
    items.sort(key=lambda x: x.get("scoredAt", ""), reverse=True)
    a_wins = sum(1 for i in items if i.get("winner") == coach_a["team"])
    b_wins = sum(1 for i in items if i.get("winner") == coach_b["team"])
    draws = len(items) - a_wins - b_wins
    last_3 = [
        {
            "winner": i.get("winner"),
            "score": f"{i.get('homeTeam')} {i.get('homeScore', 0)} - {i.get('awayTeam')} {i.get('awayScore', 0)}",
            "date": i.get("scoredAt", "")[:10],
        }
        for i in items[:3]
    ]
    total = len(items)
    if total == 0:
        edge = "No previous meetings under current coaches"
    elif a_wins > b_wins:
        edge = f"{coach_a['coach']} ({coach_a['team']}) leads {a_wins}-{b_wins} ({round(a_wins/total*100)}% win rate)"
    elif b_wins > a_wins:
        edge = f"{coach_b['coach']} ({coach_b['team']}) leads {b_wins}-{a_wins} ({round(b_wins/total*100)}% win rate)"
    else:
        edge = f"Even record: {a_wins}-{b_wins}"
    return {
        "coach_a": {"name": coach_a["coach"], "team": coach_a["team"], "tenure_start": coach_a["from"][:4]},
        "coach_b": {"name": coach_b["coach"], "team": coach_b["team"], "tenure_start": coach_b["from"][:4]},
        "tenure_overlap_since": tenure_start[:4],
        "total_games": total,
        "record": {"a_wins": a_wins, "b_wins": b_wins, "draws": draws},
        "last_3": last_3,
        "edge": edge,
    }


@tool
def get_coaching_matchup(team_a: str, team_b: str) -> dict:
    """Returns the head-to-head record between the current coaches of two teams during their tenures."""
    return _get_coaching_matchup(team_a=team_a, team_b=team_b)
