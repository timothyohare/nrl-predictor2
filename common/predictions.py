"""Prediction selection — avoid hindsight scoring.

Predictions get regenerated repeatedly for the same match (the orchestrator re-runs while
the round is still "current", plus manual runs), so the *latest* prediction can be timestamped
AFTER kickoff. Scoring/displaying that one rewards hindsight. The honest choice is the last
prediction made strictly before kickoff. See docs/matchid-identity-plan.md (timing note).
"""
from __future__ import annotations

from datetime import UTC, datetime


def parse_ts(ts) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerating a trailing 'Z') to an aware UTC datetime."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def latest_before_kickoff(preds: list[dict], kickoff, ts_key: str = "generatedAt") -> dict | None:
    """Return the prediction with the greatest ``ts_key`` that is <= kickoff.

    Falls back to the latest overall when kickoff is unknown/unparseable or no prediction
    predates it (so a fully-hindsight match still scores, rather than silently dropping).
    Returns None only for an empty list. Use ``is_hindsight`` to tell which case applied.
    """
    if not preds:
        return None
    by_recent = sorted(preds, key=lambda p: p.get(ts_key, ""), reverse=True)
    ko = parse_ts(kickoff)
    if ko is not None:
        for p in by_recent:  # by_recent is newest-first, so the first match is the latest pre-KO
            pts = parse_ts(p.get(ts_key))
            if pts is not None and pts <= ko:
                return p
    return by_recent[0]


def is_hindsight(pred: dict, kickoff, ts_key: str = "generatedAt") -> bool:
    """True if ``pred`` was generated at/after kickoff (i.e. the selection fell back)."""
    ko, pts = parse_ts(kickoff), parse_ts(pred.get(ts_key)) if pred else None
    return ko is not None and pts is not None and pts > ko
