import json

from scrapers.shared.http_client import get_with_retry
from scrapers.shared.models import WeatherForecast

_BOM_SEARCH_URL = "https://api.weather.bom.gov.au/v1/locations?searchTerm={lat},{lon}"
_BOM_HOURLY_URL = "https://api.weather.bom.gov.au/v1/locations/{geohash}/forecasts/hourly"
_OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&hourly=temperature_2m,precipitation_probability,precipitation,windspeed_10m"
    "&forecast_days=7"
)


class WeatherDataUnavailable(Exception):
    pass


def get_geohash(lat: float, lon: float) -> str:
    url = _BOM_SEARCH_URL.format(lat=lat, lon=lon)
    _, body = get_with_retry(url)
    data = json.loads(body)
    # location search returns a 7-char geohash — truncate to 6 for hourly endpoint
    return data["data"][0]["geohash"][:6]


def fetch_bom_hourly(lat: float, lon: float) -> dict:
    geohash = get_geohash(lat, lon)
    _, body = get_with_retry(_BOM_HOURLY_URL.format(geohash=geohash))
    return json.loads(body)


def parse_bom_hourly(data: dict, target_utc_time: str, venue: str) -> WeatherForecast:
    target_prefix = target_utc_time[:13]  # "2026-05-16T09"
    for slot in data.get("data", []):
        if slot["time"][:13] == target_prefix:
            return WeatherForecast(
                venue=venue,
                date=target_utc_time[:10],
                hour=int(target_utc_time[11:13]),
                rain_chance_pct=slot["rain"]["chance"],
                rain_mm=slot["rain"]["amount"]["max"],
                wind_kmh=slot["wind"]["speed_kilometre"],
                temp_c=slot["temp"],
            )
    raise WeatherDataUnavailable(f"No BOM hourly slot for {target_utc_time}")


def fetch_open_meteo(lat: float, lon: float) -> dict:
    url = _OPEN_METEO_URL.format(lat=lat, lon=lon)
    _, body = get_with_retry(url)
    return json.loads(body)


def parse_open_meteo(data: dict, target_date: str, target_hour: int, venue: str) -> WeatherForecast:
    target_ts = f"{target_date}T{target_hour:02d}:00"
    hourly = data["hourly"]
    times = hourly["time"]
    if target_ts not in times:
        raise WeatherDataUnavailable(f"No Open-Meteo slot for {target_ts}")
    idx = times.index(target_ts)
    return WeatherForecast(
        venue=venue,
        date=target_date,
        hour=target_hour,
        rain_chance_pct=hourly["precipitation_probability"][idx],
        rain_mm=hourly["precipitation"][idx],
        wind_kmh=hourly["windspeed_10m"][idx],
        temp_c=hourly["temperature_2m"][idx],
    )


def get_forecast(venue: str, lat: float, lon: float, date: str, kickoff_utc: str) -> WeatherForecast:
    try:
        raw = fetch_bom_hourly(lat, lon)
        return parse_bom_hourly(raw, target_utc_time=kickoff_utc, venue=venue)
    except Exception:
        raw = fetch_open_meteo(lat, lon)
        hour = int(kickoff_utc[11:13])
        return parse_open_meteo(raw, target_date=date, target_hour=hour, venue=venue)
