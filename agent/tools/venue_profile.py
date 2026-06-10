"""Venue profile tool — returns ground characteristics."""
import re

from langchain_core.tools import tool

VENUE_PROFILES = {
    "accor-stadium": {"name": "Accor Stadium", "aliases": ["stadium australia", "anz stadium", "homebush"], "city": "Sydney", "capacity": 83500, "roof": "none", "surface": "grass", "weather_impact_notes": "Large open-air venue. Wind can swirl."},
    "allianz-stadium": {"name": "Allianz Stadium", "aliases": ["sydney football stadium", "sfs", "moore park"], "city": "Sydney", "capacity": 42512, "roof": "partial", "surface": "grass", "weather_impact_notes": "Partial roof cover. Moderate wind exposure."},
    "4-pines-park": {"name": "4 Pines Park", "aliases": ["brookvale oval", "brookvale", "lottoland", "manly oval"], "city": "Sydney", "capacity": 18000, "roof": "none", "surface": "grass", "weather_impact_notes": "Notorious for swirling wind. Favours forward-dominant teams."},
    "blubet-stadium": {"name": "BlueBet Stadium", "aliases": ["penrith stadium", "panthers stadium", "pepper stadium"], "city": "Penrith", "capacity": 22000, "roof": "none", "surface": "grass", "weather_impact_notes": "Western Sydney extremes. Dew late in evening games."},
    "commbank-stadium": {"name": "CommBank Stadium", "aliases": ["bankwest stadium", "parramatta stadium", "western sydney stadium"], "city": "Parramatta", "capacity": 30000, "roof": "partial", "surface": "grass", "weather_impact_notes": "Partially enclosed — reduced wind. Good surface."},
    "pointsbet-stadium": {"name": "PointsBet Stadium", "aliases": ["shark park", "remondis stadium", "endeavour field"], "city": "Sydney", "capacity": 22000, "roof": "none", "surface": "grass", "weather_impact_notes": "Coastal near Cronulla. Afternoon sea breeze."},
    "leichhardt-oval": {"name": "Leichhardt Oval", "aliases": ["leichhardt"], "city": "Sydney", "capacity": 20000, "roof": "none", "surface": "grass", "weather_impact_notes": "Tiny hostile ground. Tight sidelines."},
    "qld-country-bank-stadium": {"name": "Queensland Country Bank Stadium", "aliases": ["townsville stadium", "1300smiles stadium"], "city": "Townsville", "capacity": 25000, "roof": "none", "surface": "grass", "weather_impact_notes": "Tropical heat and humidity exhausts visiting teams."},
    "suncorp-stadium": {"name": "Suncorp Stadium", "aliases": ["lang park", "brisbane stadium"], "city": "Brisbane", "capacity": 52500, "roof": "none", "surface": "grass", "weather_impact_notes": "Subtropical. Enclosed feel reduces wind."},
    "cbus-super-stadium": {"name": "Cbus Super Stadium", "aliases": ["robina stadium", "metricon stadium", "gold coast stadium", "heritage bank stadium"], "city": "Gold Coast", "capacity": 27400, "roof": "none", "surface": "grass", "weather_impact_notes": "Subtropical. Afternoon storms possible."},
    "mcdonald-jones-stadium": {"name": "McDonald Jones Stadium", "aliases": ["newcastle stadium", "hunter stadium"], "city": "Newcastle", "capacity": 33000, "roof": "none", "surface": "grass", "weather_impact_notes": "Coastal. Can get windy."},
    "win-stadium": {"name": "WIN Stadium", "aliases": ["wollongong stadium", "wollongong"], "city": "Wollongong", "capacity": 23000, "roof": "none", "surface": "grass", "weather_impact_notes": "Coastal — wind off escarpment. Cold in winter."},
    "gio-stadium": {"name": "GIO Stadium", "aliases": ["canberra stadium", "bruce stadium"], "city": "Canberra", "capacity": 25011, "roof": "none", "surface": "grass", "weather_impact_notes": "Inland — cold winters with frost, hot dry summers."},
    "campbelltown-stadium": {"name": "Campbelltown Stadium", "aliases": ["campbelltown sports stadium", "c.ex stadium"], "city": "Campbelltown", "capacity": 21000, "roof": "none", "surface": "grass", "weather_impact_notes": "Western Sydney extremes."},
    "go-media-stadium": {"name": "Go Media Stadium", "aliases": ["mt smart stadium", "mount smart", "auckland"], "city": "Auckland", "capacity": 30000, "roof": "none", "surface": "grass", "weather_impact_notes": "NZ — significant travel factor. Can be wet and cold."},
    "kayo-stadium": {"name": "Kayo Stadium", "aliases": ["redcliffe stadium", "dolphins stadium", "moreton daily stadium"], "city": "Redcliffe", "capacity": 11500, "roof": "none", "surface": "grass", "weather_impact_notes": "Small suburban QLD ground."},
}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _find_venue(venue_name: str) -> dict | None:
    name_lower = venue_name.lower().strip()
    slug = _slugify(venue_name)
    for venue_slug, profile in VENUE_PROFILES.items():
        if slug == venue_slug or name_lower == profile["name"].lower():
            return profile
        for alias in profile.get("aliases", []):
            if name_lower == alias.lower() or alias.lower() in name_lower or name_lower in alias.lower():
                return profile
        if name_lower in profile["name"].lower() or profile["name"].lower() in name_lower:
            return profile
    return None


def _get_venue_profile(venue: str) -> dict:
    profile = _find_venue(venue)
    if profile:
        return {**profile, "known": True}
    return {"name": venue, "city": "Unknown", "capacity": 0, "roof": "unknown", "surface": "unknown",
            "weather_impact_notes": "No venue profile available.", "aliases": [], "known": False}


@tool
def get_venue_profile(venue: str) -> dict:
    """Returns venue profile including roof type, surface, capacity, and weather impact notes."""
    return _get_venue_profile(venue=venue)
