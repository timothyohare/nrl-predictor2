from __future__ import annotations

import json
from typing import Literal, TypedDict

from pydantic import BaseModel, Field, field_validator


# ── Pydantic output models ───────────────────────────────────────────────────

class RouterOutput(BaseModel):
    difficulty: Literal["EASY", "CONTESTED", "COMPLEX"]
    rationale: str
    primary_model: str
    challenger_model: str


class PrimaryPrediction(BaseModel):
    predicted_winner: str
    predicted_margin: int
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    key_factors: list[str] = Field(min_length=2, max_length=4)
    reasoning: str


class Challenge(BaseModel):
    counter_winner: str
    counter_margin: int
    challenge_strength: Literal["WEAK", "MODERATE", "STRONG"]
    key_counterpoints: list[str] = Field(min_length=2, max_length=4)
    challenge_reasoning: str


class FinalPrediction(BaseModel):
    predicted_winner: str
    predicted_margin: int
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    accepted_primary: bool
    judge_rationale: str
    key_factors: list[str] = Field(min_length=2, max_length=4)
    reasoning: str


class FirstTryScorerCandidate(BaseModel):
    player_name: str
    team: str
    position: str
    probability: float
    rationale: str


class FirstTryPrediction(BaseModel):
    candidates: list[FirstTryScorerCandidate] = Field(min_length=1, max_length=3)


class ExtendedPrediction(BaseModel):
    first_try_scorer: FirstTryPrediction
    margin_bracket: Literal["1-5", "6-12", "13-20", "21+"]
    key_player_to_watch: str
    upset_probability: float = Field(ge=0.0, le=1.0)

    @field_validator("first_try_scorer", mode="before")
    @classmethod
    def _coerce_first_try(cls, v):
        """Tolerate the LLM emitting the candidate list directly.

        Haiku's structured output for this nested field is unreliable: it often
        returns ``first_try_scorer`` as a JSON string or a bare list of candidate
        dicts instead of a ``{"candidates": [...]}`` object. Normalise those
        shapes (and clamp to the top 3) rather than crash the whole pipeline.
        """
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except (ValueError, TypeError):
                return v
        if isinstance(v, list):
            v = {"candidates": v}
        if isinstance(v, dict) and isinstance(v.get("candidates"), list):
            return {**v, "candidates": v["candidates"][:3]}
        return v


class TraceEntry(TypedDict):
    node: str
    tool: str
    input: dict
    output: str


# ── LangGraph state ──────────────────────────────────────────────────────────

class MatchPredictionState(TypedDict, total=False):
    match_id: str
    round_number: int
    season: int
    match_context: dict

    # Router outputs
    difficulty: str
    difficulty_rationale: str
    primary_model: str
    challenger_model: str

    # Node outputs
    primary_prediction: PrimaryPrediction
    challenge: Challenge
    final_prediction: FinalPrediction
    extended: ExtendedPrediction

    # Audit
    agent_trace: list[TraceEntry]
