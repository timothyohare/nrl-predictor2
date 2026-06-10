import random
import time
import requests

MAX_RETRIES = 3
DELAY_MIN = 1.5
DELAY_MAX = 3.0

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class ScraperError(Exception):
    pass


def get_with_retry(url: str, headers: dict | None = None, max_retries: int = MAX_RETRIES, session=None) -> tuple[int, str]:
    merged_headers = {"User-Agent": _USER_AGENT}
    if headers:
        merged_headers.update(headers)

    requester = session or requests.Session()
    last_status = None

    for attempt in range(max_retries):
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        response = requester.get(url, headers=merged_headers)
        last_status = response.status_code

        if response.status_code == 200:
            return response.status_code, response.text

        # don't retry client errors
        if 400 <= response.status_code < 500:
            raise ScraperError(f"Client error {response.status_code} fetching {url}")

    raise ScraperError(f"Failed after {max_retries} attempts; last status {last_status} for {url}")
