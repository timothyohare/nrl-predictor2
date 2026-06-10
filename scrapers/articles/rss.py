import json
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from scrapers.shared.http_client import get_with_retry
from scrapers.shared.models import Article

_NRL_TEAMS = [
    "Panthers", "Broncos", "Storm", "Roosters", "Sharks", "Raiders",
    "Warriors", "Cowboys", "Titans", "Eels", "Dragons", "Bulldogs",
    "Knights", "Sea Eagles", "Rabbitohs", "Wests Tigers", "Dolphins",
]
_MAX_AGE_HOURS = 48


def fetch_rss(url: str) -> str:
    _, body = get_with_retry(url)
    return body


def parse_rss(
    xml_text: str,
    source_name: str,
    nrl_teams: list[str] | None = None,
    now: datetime | None = None,
) -> list[Article]:
    teams = nrl_teams or _NRL_TEAMS
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=_MAX_AGE_HOURS)
    root = ElementTree.fromstring(xml_text)
    articles = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()

        if not title or not url or not pub_raw:
            continue

        try:
            published_at = parsedate_to_datetime(pub_raw).astimezone(timezone.utc)
        except Exception:
            continue

        if published_at < cutoff:
            continue

        if not any(team.lower() in title.lower() for team in teams):
            continue

        articles.append(Article(
            title=title,
            url=url,
            published_at=published_at.isoformat(),
            source=source_name,
        ))
    return articles
