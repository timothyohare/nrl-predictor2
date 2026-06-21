"""Tests for the canonical matchId helper (common/match_id.py)."""
import pytest

from common.match_id import is_canonical, match_id, match_id_from_url, round_of


@pytest.mark.parametrize("url,expected", [
    ("/draw/nrl-premiership/2026/round-11/panthers-v-broncos/", "round-11-panthers-v-broncos"),
    ("/draw/nrl-premiership/2026/round-11/panthers-v-broncos", "round-11-panthers-v-broncos"),
    ("https://www.nrl.com/draw/nrl-premiership/2026/round-3/sea-eagles-v-storm/", "round-3-sea-eagles-v-storm"),
    ("/draw/nrl/2026/finals-week-1/eels-v-storm/", "finals-week-1-eels-v-storm"),
])
def test_match_id_from_url(url, expected):
    assert match_id_from_url(url) == expected


def test_match_id_from_fields_slugs_but_keeps_order():
    assert match_id(16, "Manly Sea Eagles", "Melbourne Storm") == "round-16-sea-eagles-v-storm"
    # home/away order is preserved (the draw decides it) — not alphabetised
    assert match_id(16, "Storm", "Sea Eagles") == "round-16-storm-v-sea-eagles"


def test_is_canonical_and_round_of():
    assert is_canonical("round-16-knights-v-dragons")
    assert not is_canonical("knights-v-dragons")
    assert round_of("round-17-sea-eagles-v-storm") == 17
    assert round_of("sea-eagles-v-storm") is None
