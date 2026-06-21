"""Canonical NRL team identity — the single source of truth for both repos.

Internally a team is *always* the lowercase slug ("sea-eagles"). The NRL `nickName`
("Sea Eagles"), the full name ("Manly Sea Eagles"), odds-API names and the LLM's free
text are all inbound forms that must be `to_slug`'d at the boundary before they touch a
table, a tool argument, or a comparison. Display strings (for the website) come from
`display()`. See docs/team-identity-plan.md.

Data lives in team_registry.json so the TS frontend can consume the same source.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).with_name("team_registry.json")


def _normalise(name: str) -> str:
    """Lower-case, collapse separators/whitespace so all inbound forms compare equal."""
    return re.sub(r"[\s\-_]+", " ", name.strip().lower()).strip()


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict]:
    return json.loads(_REGISTRY_PATH.read_text())


@lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    """Map every known inbound form (normalised) -> slug."""
    table: dict[str, str] = {}
    for slug, meta in _registry().items():
        table[_normalise(slug)] = slug
        table[_normalise(meta["nickname"])] = slug
        table[_normalise(meta["full_name"])] = slug
        for alias in meta.get("aliases", []):
            table[_normalise(alias)] = slug
    return table


def to_slug(name: str) -> str:
    """Resolve any inbound team string to its canonical slug.

    Total and idempotent: unknown input is returned unchanged (with a warning), and
    ``to_slug(to_slug(x)) == to_slug(x)``. No canonical nickname is a substring of
    another, so the substring fallback (for "Manly Sea Eagles" -> "sea-eagles") is
    unambiguous.
    """
    if not name:
        return name
    norm = _normalise(name)
    slug = _lookup().get(norm)
    if slug:
        return slug
    for slug, meta in _registry().items():
        if _normalise(meta["nickname"]) in norm:
            return slug
    logger.warning("to_slug: unrecognised team name %r — passing through unchanged", name)
    return name


def is_known(name: str) -> bool:
    """True if ``name`` resolves to a registered team."""
    return to_slug(name) in _registry()


def all_slugs() -> list[str]:
    return list(_registry().keys())


def display(slug: str) -> dict:
    """Slug -> display metadata ({slug, nickname, full_name, abbrev}). Falls back to a
    title-cased echo for an unknown slug so the UI degrades gracefully."""
    meta = _registry().get(slug)
    if not meta:
        return {"slug": slug, "nickname": slug, "full_name": slug, "abbrev": ""}
    return {"slug": slug, **{k: meta[k] for k in ("nickname", "full_name", "abbrev")}}


def display_name(slug: str) -> str:
    """Convenience: the short display name ("Sea Eagles") for a slug."""
    return display(slug)["nickname"]
