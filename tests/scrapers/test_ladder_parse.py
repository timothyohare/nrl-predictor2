"""Regression: the ladder parser must track the live NRL feed shape.

The 2026 feed dropped the per-entry ``position`` field (rank is now the array
order) and renamed several ``stats`` keys: ``losses``→``lost``, ``draws``→``drawn``,
``pointsDiff``→``points difference``. The old parser hard-indexed ``p["position"]``
(KeyError → nrl-predictor-ladder-errors alarm) and silently read 0 for the renamed
stats. This pins the parser to a fixture in the real shape.
"""
from scrapers.nrl.ladder import parse_ladder

# Two entries in the exact shape the live feed returns (see S3 raw-scrapes/ladder),
# deliberately given in ladder order with no explicit `position` key.
RAW = {
    "positions": [
        {
            "teamNickname": "Panthers",
            "stats": {"played": 15, "wins": 12, "lost": 3, "drawn": 0,
                      "points": 28, "points difference": 258},
        },
        {
            "teamNickname": "Sea Eagles",
            "stats": {"played": 14, "wins": 8, "lost": 6, "drawn": 0,
                      "points": 20, "points difference": 116},
        },
    ]
}


def test_rank_derived_from_array_order():
    ladder = parse_ladder(RAW)
    assert [p.position for p in ladder] == [1, 2]


def test_renamed_stats_keys_are_read():
    top = parse_ladder(RAW)[0]
    assert top.team_name == "panthers"  # to_slug'd at the boundary
    assert (top.played, top.wins, top.losses, top.draws) == (15, 12, 3, 0)
    assert top.points == 28
    assert top.for_against_diff == 258


def test_empty_feed_is_safe():
    assert parse_ladder({}) == []
