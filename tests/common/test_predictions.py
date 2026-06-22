"""Tests for hindsight-safe prediction selection (common/predictions.py)."""
from common.predictions import is_hindsight, latest_before_kickoff, parse_ts

KO = "2026-06-19T10:00:00Z"


def _p(ts):
    return {"generatedAt": ts, "predicted_winner": ts}  # winner echoes ts for identity


def test_picks_latest_before_kickoff():
    preds = [_p("2026-06-15T10:00:00+00:00"),
             _p("2026-06-18T07:00:00+00:00"),   # last before KO
             _p("2026-06-21T11:00:00+00:00")]   # post-KO regeneration
    assert latest_before_kickoff(preds, KO)["generatedAt"] == "2026-06-18T07:00:00+00:00"


def test_falls_back_to_latest_when_all_post_kickoff():
    preds = [_p("2026-06-19T10:30:00+00:00"), _p("2026-06-21T11:00:00+00:00")]
    chosen = latest_before_kickoff(preds, KO)
    assert chosen["generatedAt"] == "2026-06-21T11:00:00+00:00"
    assert is_hindsight(chosen, KO)


def test_falls_back_to_latest_when_kickoff_unknown():
    preds = [_p("2026-06-15T10:00:00+00:00"), _p("2026-06-21T11:00:00+00:00")]
    chosen = latest_before_kickoff(preds, None)
    assert chosen["generatedAt"] == "2026-06-21T11:00:00+00:00"
    assert not is_hindsight(chosen, None)


def test_pre_kickoff_choice_is_not_hindsight():
    preds = [_p("2026-06-15T10:00:00+00:00"), _p("2026-06-21T11:00:00+00:00")]
    chosen = latest_before_kickoff(preds, KO)
    assert chosen["generatedAt"] == "2026-06-15T10:00:00+00:00"
    assert not is_hindsight(chosen, KO)


def test_empty_returns_none():
    assert latest_before_kickoff([], KO) is None


def test_parse_ts_handles_z_and_offset_and_naive():
    assert parse_ts("2026-06-19T10:00:00Z") == parse_ts("2026-06-19T10:00:00+00:00")
    assert parse_ts("2026-06-19T10:00:00").tzinfo is not None  # naive -> assumed UTC
    assert parse_ts("") is None and parse_ts(None) is None
