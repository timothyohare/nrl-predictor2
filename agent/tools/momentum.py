from common.teams import to_slug


def calculate_momentum(
    results: list[dict],
    team: str,
    decay_factor: float = 0.7,
) -> dict:
    """Calculate momentum metrics from a list of results sorted by recency (most recent first)."""
    if not results:
        return {
            "weighted_win_rate": 0.0,
            "momentum_direction": "stable",
            "momentum_score": 0.0,
            "streak": "",
            "weighted_points_for": 0.0,
            "weighted_points_against": 0.0,
            "form_string": "",
        }

    wins = []
    points_for = []
    points_against = []
    weights = []

    for i, r in enumerate(results):
        w = decay_factor ** i
        weights.append(w)

        team_slug = to_slug(team)
        is_home = to_slug(r.get("homeTeam", "")) == team_slug
        pf = int(r.get("homeScore", 0) if is_home else r.get("awayScore", 0))
        pa = int(r.get("awayScore", 0) if is_home else r.get("homeScore", 0))
        won = to_slug(r.get("winner", "")) == team_slug

        wins.append(1.0 if won else 0.0)
        points_for.append(pf)
        points_against.append(pa)

    total_weight = sum(weights)
    weighted_win_rate = sum(w * v for w, v in zip(weights, wins)) / total_weight
    weighted_pf = sum(w * v for w, v in zip(weights, points_for)) / total_weight
    weighted_pa = sum(w * v for w, v in zip(weights, points_against)) / total_weight

    # Momentum direction: compare unweighted win rate of recent half vs older half
    # Use unweighted to avoid decay bias making alternating patterns look directional
    mid = len(results) // 2 if len(results) > 1 else 1
    recent_wins_slice = wins[:mid]
    older_wins_slice = wins[mid:]

    recent_rate = sum(recent_wins_slice) / len(recent_wins_slice) if recent_wins_slice else 0.0
    older_rate = sum(older_wins_slice) / len(older_wins_slice) if older_wins_slice else 0.0

    diff = recent_rate - older_rate
    if diff > 0.34:
        direction = "rising"
    elif diff < -0.34:
        direction = "falling"
    else:
        direction = "stable"

    # Momentum score: -1.0 to 1.0
    momentum_score = round(max(-1.0, min(1.0, diff)), 3)

    # Current streak
    streak_char = "W" if wins[0] == 1.0 else "L"
    streak_count = 0
    for v in wins:
        if (v == 1.0) == (streak_char == "W"):
            streak_count += 1
        else:
            break
    streak = f"{streak_char}{streak_count}"

    form_string = " ".join("W" if v == 1.0 else "L" for v in wins)

    return {
        "weighted_win_rate": round(weighted_win_rate, 3),
        "momentum_direction": direction,
        "momentum_score": momentum_score,
        "streak": streak,
        "weighted_points_for": round(weighted_pf, 1),
        "weighted_points_against": round(weighted_pa, 1),
        "form_string": form_string,
    }
