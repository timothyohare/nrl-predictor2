import json
import logging

from scrapers.shared.constants import HAIKU_MODEL
from scrapers.shared.models import InjuryMention

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "Extract all player injury and availability mentions from the following rugby league article. "
    "Return a JSON array only, with no other text. Each element: "
    '{{"player": "<full name>", "team": "<NRL team nickname>", "status": "<out|doubtful|available|returning>", "detail": "<brief detail>"}}. '
    "If there are no mentions return [].\n\nARTICLE:\n{text}"
)


def extract_injury_mentions(article_text: str, claude_client) -> list[InjuryMention]:
    response = claude_client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": _PROMPT_TEMPLATE.format(text=article_text)}],
    )
    raw = response.content[0].text.strip()
    try:
        items = json.loads(raw)
        return [
            InjuryMention(
                player=item["player"],
                team=item["team"],
                status=item["status"],
                detail=item["detail"],
            )
            for item in items
        ]
    except Exception:
        logger.warning("Haiku extractor returned malformed JSON: %r", raw[:200])
        return []
