"""Synthesis Judge node — weighs primary vs challenger and produces final prediction."""
import json

from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import FinalPrediction, MatchPredictionState
from scrapers.shared.constants import SONNET_MODEL

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
            base_llm = ChatAnthropic(model=SONNET_MODEL, api_key=get_api_key(), max_tokens=1536)

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
        result: FinalPrediction = structured.invoke(messages)
        return {"final_prediction": result}

    return judge_node
