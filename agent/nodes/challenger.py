"""Challenger node — argues the opposite case to stress-test the primary prediction."""
import json

from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import Challenge, MatchPredictionState
from scrapers.shared.constants import SONNET_MODEL

_SYSTEM = """\
You are a contrarian NRL analyst. You have been given a match prediction.
Your job is to argue AGAINST it — find the strongest possible case for the other team.

Look for:
- Overlooked injuries or form slumps the primary missed
- Home ground narratives or travel fatigue
- Form anomalies (team with poor record at this venue)
- Referee tendencies or historic coaching X-factors
- Trap game signals (emotional letdown, sandwich fixture, dead rubber, revenge game)
- Overconfidence signals — a team being written off that has recent upset form

You MUST produce a structured counter-prediction, even if you personally think the
original is correct. Your role is to find holes, not to be right.
Rate the strength of your challenge as WEAK, MODERATE, or STRONG:
- WEAK: you found minor quibbles, primary case is solid
- MODERATE: you found genuine reasons to doubt the primary's margin or confidence
- STRONG: you have a compelling case for the other team winning
"""


def make_challenger_node(llm=None):
    def challenger_node(state: MatchPredictionState) -> dict:
        base_llm = llm
        if base_llm is None:
            from langchain_anthropic import ChatAnthropic
            from agent.lambda_handler import get_api_key
            base_llm = ChatAnthropic(model=SONNET_MODEL, api_key=get_api_key(), max_tokens=2048)

        structured = base_llm.with_structured_output(Challenge)
        primary = state["primary_prediction"]
        ctx = state.get("match_context", {})

        messages = [
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=(
                f"Match: {state['match_id']}\n"
                f"Context: {json.dumps(ctx, default=str)}\n\n"
                f"Primary prediction:\n"
                f"  Winner: {primary.predicted_winner}\n"
                f"  Margin: {primary.predicted_margin}\n"
                f"  Confidence: {primary.confidence}\n"
                f"  Key factors: {primary.key_factors}\n"
                f"  Reasoning: {primary.reasoning}\n\n"
                "Now argue the strongest possible case AGAINST this prediction."
            )),
        ]
        result: Challenge = structured.invoke(messages)
        return {"challenge": result}

    return challenger_node
