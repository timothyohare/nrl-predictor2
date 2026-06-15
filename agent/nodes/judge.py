"""Synthesis Judge node — weighs primary vs challenger and produces final prediction."""
import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import Challenge, FinalPrediction, MatchPredictionState, PrimaryPrediction
from scrapers.shared.constants import SONNET_MODEL

logger = logging.getLogger(__name__)

_CONFIDENCE_TIERS = ["LOW", "MEDIUM", "HIGH"]


def _downgrade(confidence: str) -> str:
    """Drop a confidence tier (HIGH→MEDIUM→LOW), flooring at LOW."""
    idx = _CONFIDENCE_TIERS.index(confidence) if confidence in _CONFIDENCE_TIERS else 1
    return _CONFIDENCE_TIERS[max(0, idx - 1)]


def _fallback_from_primary(primary: PrimaryPrediction, challenge: Challenge) -> FinalPrediction:
    """Degraded final prediction used when the Judge's structured output can't be parsed.

    Defaults to accepting the primary (the WEAK-challenge path) so the pipeline still
    produces a prediction rather than throwing away ~4 upstream LLM calls. Softens
    confidence one tier when the challenge was MODERATE/STRONG, mirroring the decision
    framework. primary.key_factors is already validated to 2-4 items, so it's reused as-is.
    """
    confidence = primary.confidence
    if challenge.challenge_strength in ("MODERATE", "STRONG"):
        confidence = _downgrade(confidence)
    return FinalPrediction(
        predicted_winner=primary.predicted_winner,
        predicted_margin=primary.predicted_margin,
        confidence=confidence,
        accepted_primary=True,
        judge_rationale=(
            "Judge synthesis output could not be parsed (likely max_tokens truncation); "
            f"defaulted to the primary prediction with confidence softened for a "
            f"{challenge.challenge_strength} challenge."
        ),
        key_factors=list(primary.key_factors),
        reasoning=primary.reasoning,
    )

_SYSTEM = """\
You are the Chief NRL Analyst. You have received two competing predictions for the same match:
a Primary prediction and a Challenger counter-prediction. Your job is to weigh both cases
and produce the definitive final prediction.

Decision framework:
- WEAK challenge: accept the primary prediction. You may upgrade confidence if the challenge
  found nothing meaningful.
- MODERATE challenge: keep the primary winner but soften the margin by 2-4 points and
  consider dropping confidence by one tier.
- STRONG challenge: seriously re-evaluate. If the challenger's case is more compelling than
  the primary's, flip the predicted winner. Minimum confidence is LOW when challenge is STRONG.

Be explicit in your judge_rationale about why you sided with one view over the other.
set accepted_primary=true if you sided with the primary prediction, false if you flipped.
"""


def make_judge_node(llm=None):
    def judge_node(state: MatchPredictionState) -> dict:
        base_llm = llm
        if base_llm is None:
            from langchain_anthropic import ChatAnthropic
            from agent.lambda_handler import get_api_key
            # FinalPrediction has two prose fields (judge_rationale + reasoning), so its
            # structured output runs larger than the Challenger's; 1536 truncated it and
            # crashed with a max_tokens ValidationError. Give it room.
            base_llm = ChatAnthropic(model=SONNET_MODEL, api_key=get_api_key(), max_tokens=3072)

        structured = base_llm.with_structured_output(FinalPrediction)
        primary = state["primary_prediction"]
        challenge = state["challenge"]
        ctx = state.get("match_context", {})

        messages = [
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=(
                f"Match: {state['match_id']}\n"
                f"Difficulty: {state.get('difficulty', 'CONTESTED')}\n"
                f"Context: {json.dumps(ctx, default=str)}\n\n"
                f"PRIMARY PREDICTION:\n"
                f"  Winner: {primary.predicted_winner}\n"
                f"  Margin: {primary.predicted_margin}\n"
                f"  Confidence: {primary.confidence}\n"
                f"  Key factors: {primary.key_factors}\n"
                f"  Reasoning: {primary.reasoning}\n\n"
                f"CHALLENGER COUNTER-PREDICTION:\n"
                f"  Counter winner: {challenge.counter_winner}\n"
                f"  Counter margin: {challenge.counter_margin}\n"
                f"  Challenge strength: {challenge.challenge_strength}\n"
                f"  Key counterpoints: {challenge.key_counterpoints}\n"
                f"  Challenge reasoning: {challenge.challenge_reasoning}\n\n"
                "Weigh both cases and produce the final definitive prediction."
            )),
        ]
        try:
            result: FinalPrediction = structured.invoke(messages)
        except Exception as e:
            # max_tokens truncation or a transient parse failure must not sink the whole
            # pipeline (and the ~4 upstream LLM calls already spent). Fall back to the
            # primary prediction rather than raising.
            logger.warning(
                "Judge structured output failed for %s (%s) — falling back to primary",
                state["match_id"], e,
            )
            result = _fallback_from_primary(state["primary_prediction"], state["challenge"])
        return {"final_prediction": result}

    return judge_node
