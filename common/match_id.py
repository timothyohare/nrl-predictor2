"""Canonical match identity — the single source of truth for the matchId key.

A matchId is the round-qualified slug ``round-<N>-<home>-v-<away>`` where the team
slugs come from the official match-centre URL order (the draw decides which side is
home). Every writer keys on this; every cross-table join is round-aware (by matchId or
roundNumber), never a round-blind team-pair. See docs/matchid-identity-plan.md.
"""
from __future__ import annotations

import re

from common.teams import to_slug

_ROUND_PREFIX = re.compile(r"^round-\d+-")


def match_id_from_url(match_centre_url: str) -> str:
    """Canonical matchId from a match-centre URL.

    ``/draw/nrl-premiership/2026/round-11/panthers-v-broncos/`` -> ``round-11-panthers-v-broncos``.
    The last two path segments (``round-11`` + ``panthers-v-broncos``) are joined; the team
    portion is left in the URL's official home-v-away order.
    """
    parts = match_centre_url.rstrip("/").rsplit("/", 2)
    return f"{parts[-2]}-{parts[-1]}" if len(parts) >= 3 else parts[-1]


def match_id(round_no: int, home: str, away: str) -> str:
    """Canonical matchId from structured fields. ``home``/``away`` may be any inbound team
    form; they are slugged but NOT reordered (the caller supplies official home/away)."""
    return f"round-{int(round_no)}-{to_slug(home)}-v-{to_slug(away)}"


def is_canonical(match_id_str: str) -> bool:
    """True if the matchId carries the ``round-<N>-`` prefix (i.e. is round-qualified)."""
    return bool(_ROUND_PREFIX.match(match_id_str or ""))


def round_of(match_id_str: str) -> int | None:
    """Extract the round number from a round-prefixed matchId, or None."""
    m = re.match(r"^round-(\d+)-", match_id_str or "")
    return int(m.group(1)) if m else None
