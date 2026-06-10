from dataclasses import dataclass, field


@dataclass
class Match:
    match_id: str
    home_team: str
    away_team: str
    venue: str
    round_number: int
    kick_off: str | None
    match_state: str
    match_centre_url: str = ""


@dataclass
class Player:
    jersey_number: int
    first_name: str
    last_name: str
    position: str
    is_starting: bool
    player_id: str


@dataclass
class TeamSide:
    team_id: str
    nick_name: str
    score: int | None
    players: list[Player] = field(default_factory=list)


@dataclass
class TeamSheet:
    match_id: str
    round: int
    kick_off: str | None
    match_state: str
    home_team: TeamSide
    away_team: TeamSide
    scraped_at: str = ""


@dataclass
class LadderPosition:
    position: int
    team_name: str
    played: int
    wins: int
    losses: int
    draws: int
    points: int
    for_against_diff: int
    percentage: float


@dataclass
class MatchResult:
    match_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    winner: str
    margin: int
    match_state: str


@dataclass
class WeatherForecast:
    venue: str
    date: str
    hour: int | None
    rain_chance_pct: int
    rain_mm: float
    wind_kmh: int
    temp_c: float


@dataclass
class Article:
    title: str
    url: str
    published_at: str
    source: str


@dataclass
class InjuryMention:
    player: str
    team: str
    status: str
    detail: str
