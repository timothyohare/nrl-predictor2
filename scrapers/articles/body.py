from bs4 import BeautifulSoup

from scrapers.shared.http_client import get_with_retry


def fetch_article_body(url: str) -> str:
    _, html = get_with_retry(url)
    return html


def extract_body_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["nav", "footer", "header", "script", "style", "aside"]):
        tag.decompose()
    article = soup.find("article") or soup.find("main") or soup.body
    if article is None:
        return ""
    return " ".join(article.get_text(separator=" ").split())
