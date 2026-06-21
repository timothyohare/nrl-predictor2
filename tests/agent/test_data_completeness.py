"""Regression tests for the insufficient-data guard.

Round 17 was generated ~6 days before kickoff, before the NRL named line-ups. Every
match ran with an empty team sheet, so the structured tools (recent_form, head_to_head)
returned nothing and the agent predicted blind off web_search — 1/7 winners. The guard
short-circuits before the five-call graph runs when the essential inputs are absent.
"""
from agent.lambda_handler import assess_data_completeness


def _full_context() -> dict:
    return {
        "home_team": "Sea Eagles",
        "away_team": "Storm",
        "team_sheets": {"home": ["Garrick", "Saab"], "away": ["Papenhuyzen", "Coates"]},
    }


def test_complete_context_has_no_missing_fields():
    assert assess_data_completeness(_full_context()) == []


def test_empty_team_sheet_is_flagged():
    ctx = _full_context()
    ctx["team_sheets"] = {"home": [], "away": []}
    missing = assess_data_completeness(ctx)
    assert "home team sheet" in missing
    assert "away team sheet" in missing


def test_missing_team_names_are_flagged():
    """The exact round-17 shape: no sheet item found, so names default to ''."""
    ctx = {"home_team": "", "away_team": "", "team_sheets": {"home": [], "away": []}}
    missing = assess_data_completeness(ctx)
    assert "team names" in missing


def test_one_sided_sheet_is_flagged():
    ctx = _full_context()
    ctx["team_sheets"]["away"] = []
    missing = assess_data_completeness(ctx)
    assert missing == ["away team sheet"]
