def build_retrospective_prompt(
    home_team: str,
    away_team: str,
    predicted_winner: str,
    predicted_margin: int,
    confidence: str,
    key_factors: list[str],
    reasoning: str,
    actual_winner: str,
    home_score: int,
    away_score: int,
    actual_margin: int,
    match_stats: list[str],
) -> str:
    factors_text = "\n".join(f"- {f}" for f in key_factors)
    stats_text = "\n\n".join(match_stats) if match_stats else "No post-match stats retrieved."
    correct = predicted_winner == actual_winner
    pick_summary = (
        f"CORRECT pick ({predicted_winner} won as predicted, margin off by {abs(predicted_margin - actual_margin)} pts)"
        if correct
        else f"WRONG pick (predicted {predicted_winner} by {predicted_margin}, actual {actual_winner} by {actual_margin})"
    )
    return f"""You are an NRL analyst reviewing a pre-match prediction against the actual result.

ORIGINAL PREDICTION
Match: {home_team} vs {away_team}
Predicted winner: {predicted_winner} by {predicted_margin} pts
Confidence: {confidence}
Outcome: {pick_summary}
Key factors cited:
{factors_text}

Original reasoning:
{reasoning}

ACTUAL RESULT
{home_team} {home_score} – {away_team} {away_score}
Winner: {actual_winner} by {actual_margin} pts

POST-MATCH INFORMATION
{stats_text}

Your task: Compare the prediction to what actually happened. Assess each cited key factor.

Output a single JSON object — no text before or after:
{{
  "verdict": "<1-2 sentences: was the pick correct, and what was the decisive factor>",
  "hit_factors": ["<factor from prediction that played out as stated>"],
  "missed_factors": ["<factor that was wrong, overweighted, or a significant omission>"],
  "what_actually_happened": "<50-100 words describing the key match events>",
  "lesson": "<one concrete lesson for future predictions of this type of matchup>"
}}"""
