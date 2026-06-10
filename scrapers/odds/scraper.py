"""Odds scraper — fetches NRL betting odds from the-odds-api.com."""

import logging
import requests

logger = logging.getLogger(__name__)

_ODDS_URL = "https://api.the-odds-api.com/v4/sports/rugbyleague_nrl/odds"

# Map API full team names to our nicknames
TEAM_NAME_MAP = {
    "Penrith Panthers": "Panthers",
    "Melbourne Storm": "Storm",
    "Sydney Roosters": "Roosters",
    "Brisbane Broncos": "Broncos",
    "Cronulla Sharks": "Sharks",
    "Cronulla-Sutherland Sharks": "Sharks",
    "North Queensland Cowboys": "Cowboys",
    "Canterbury Bulldogs": "Bulldogs",
    "Canterbury-Bankstown Bulldogs": "Bulldogs",
    "Manly Sea Eagles": "Sea Eagles",
    "Manly-Warringah Sea Eagles": "Sea Eagles",
    "South Sydney Rabbitohs": "Rabbitohs",
    "Parramatta Eels": "Eels",
    "Newcastle Knights": "Knights",
    "Canberra Raiders": "Raiders",
    "New Zealand Warriors": "Warriors",
    "Gold Coast Titans": "Titans",
    "St George Illawarra Dragons": "Dragons",
    "Dolphins": "Dolphins",
    "The Dolphins": "Dolphins",
    "Wests Tigers": "Wests Tigers",
    "West Tigers": "Wests Tigers",
}


def fetch_odds(api_key: str, markets: str = "h2h,spreads") -> list[dict]:
    """Fetch current NRL odds from the-odds-api.com."""
    resp = requests.get(
        _ODDS_URL,
        params={
            "apiKey": api_key,
            "regions": "au",
            "markets": markets,
            "oddsFormat": "decimal",
        },
    )
    if resp.status_code != 200:
        logger.error("Odds API returned %d: %s", resp.status_code, resp.text[:200])
        return []
    return resp.json()


def _match_to_round(home_nick: str, away_nick: str, round_matches: list[dict]) -> str | None:
    """Find the matchId for a game based on team nicknames."""
    for m in round_matches:
        if m["home_team"] == home_nick and m["away_team"] == away_nick:
            return m["match_id"]
        if m["home_team"] == away_nick and m["away_team"] == home_nick:
            return m["match_id"]
    return None


def parse_odds(raw: list[dict], round_matches: list[dict]) -> list[dict]:
    """Parse API response into our odds format, matched to round fixtures."""
    results = []

    for game in raw:
        home_api = game.get("home_team", "")
        away_api = game.get("away_team", "")
        home_nick = TEAM_NAME_MAP.get(home_api)
        away_nick = TEAM_NAME_MAP.get(away_api)

        if not home_nick or not away_nick:
            logger.warning("Unmapped team: %s or %s", home_api, away_api)
            continue

        match_id = _match_to_round(home_nick, away_nick, round_matches)
        if not match_id:
            continue

        # Aggregate h2h odds across bookmakers
        home_odds_list = []
        away_odds_list = []
        spread_list = []

        for bk in game.get("bookmakers", []):
            for market in bk.get("markets", []):
                if market["key"] == "h2h":
                    for outcome in market.get("outcomes", []):
                        if TEAM_NAME_MAP.get(outcome["name"]) == home_nick:
                            home_odds_list.append(outcome["price"])
                        elif TEAM_NAME_MAP.get(outcome["name"]) == away_nick:
                            away_odds_list.append(outcome["price"])
                elif market["key"] == "spreads":
                    for outcome in market.get("outcomes", []):
                        if TEAM_NAME_MAP.get(outcome["name"]) == home_nick:
                            spread_list.append(abs(outcome.get("point", 0)))

        if not home_odds_list or not away_odds_list:
            continue

        avg_home = sum(home_odds_list) / len(home_odds_list)
        avg_away = sum(away_odds_list) / len(away_odds_list)
        avg_spread = sum(spread_list) / len(spread_list) if spread_list else 0

        # Normalise implied probabilities (remove overround)
        raw_home_prob = 1 / avg_home
        raw_away_prob = 1 / avg_away
        total_prob = raw_home_prob + raw_away_prob
        implied_home = round(raw_home_prob / total_prob, 3)
        implied_away = round(raw_away_prob / total_prob, 3)

        favourite = home_nick if avg_home < avg_away else away_nick

        results.append({
            "matchId": match_id,
            "market_favourite": favourite,
            "market_margin": round(avg_spread, 1),
            "home_odds": round(avg_home, 3),
            "away_odds": round(avg_away, 3),
            "implied_home_prob": implied_home,
            "implied_away_prob": implied_away,
            "commence_time": game.get("commence_time", ""),
        })

    return results
