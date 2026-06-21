"""Tests for the canonical team registry (common/teams.py)."""
import pytest

from common.teams import all_slugs, display, display_name, is_known, to_slug


@pytest.mark.parametrize("supplied,expected", [
    ("sea-eagles", "sea-eagles"),
    ("Sea Eagles", "sea-eagles"),
    ("Manly Sea Eagles", "sea-eagles"),
    ("Manly-Warringah Sea Eagles", "sea-eagles"),
    ("manly", "sea-eagles"),
    ("Melbourne Storm", "storm"),
    ("STORM", "storm"),
    ("Canterbury-Bankstown Bulldogs", "bulldogs"),
    ("South Sydney Rabbitohs", "rabbitohs"),
    ("souths", "rabbitohs"),
    ("Wests Tigers", "wests-tigers"),
    ("wests-tigers", "wests-tigers"),
    ("tigers", "wests-tigers"),
    ("Dolphins", "dolphins"),
    ("redcliffe", "dolphins"),
])
def test_to_slug_resolves_known_forms(supplied, expected):
    assert to_slug(supplied) == expected


def test_to_slug_is_idempotent():
    for slug in all_slugs():
        assert to_slug(slug) == slug
        assert to_slug(to_slug(slug)) == slug


def test_to_slug_total_on_unknown():
    assert to_slug("Some Expansion FC") == "Some Expansion FC"
    assert to_slug("") == ""
    assert not is_known("Some Expansion FC")


def test_registry_has_17_teams():
    assert len(all_slugs()) == 17


def test_display_round_trips_every_team():
    for slug in all_slugs():
        d = display(slug)
        assert d["slug"] == slug
        assert d["nickname"] and d["full_name"] and d["abbrev"]
        # the displayed nickname must resolve back to the same slug
        assert to_slug(d["nickname"]) == slug
        assert to_slug(d["full_name"]) == slug


def test_display_degrades_for_unknown_slug():
    assert display("nonexistent")["nickname"] == "nonexistent"
    assert display_name("storm") == "Storm"
