"""Extended Predictor node — adds first-try scorer, margin bracket, and upset probability."""
import json

from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import ExtendedPrediction, MatchPredictionState
from scrapers.shared.constants import HAIKU_MODEL

_SYSTEM = """\
You are an NRL prop-betting specialist. Given a final match prediction and team sheets,
produce player-level predictions for entertainment and prop markets.

For first_try_scorer candidates: pick the top 3 most likely first try scorers from the
team sheets. Wingers and centres who play close to the line are most likely. Probability
should sum to less than 1.0 (the field is not included).

For margin_bracket: group the predicted margin into one of: "1-5", "6-12", "13-20", "21+".

For key_player_to_watch: name one player who is pivotal to the predicted winner's performance
and give a one-line reason.

For upset_probability: the probability (0.0-1.0) that the predicted underdog wins.
LOW confidence prediction with a STRONG challenge → higher upset probability (0.3-0.45).
HIGH confidence prediction with a WEAK challenge → low upset probability (0.05-0.15).
"""


def make_extended_node(llm=None):
    def extended_node(state: MatchPredictionState) -> dict:
        base_llm = llm
        if base_llm is None:
            from langchain_anthropic import ChatAnthropic
            from agent.lambda_handler import get_api_key
            base_llm = ChatAnthropic(model=HAIKU_MODEL, api_key=get_api_key(), max_tokens=1024)

        structured = base_llm.with_structured_output(ExtendedPrediction)
        final = state["final_prediction"]
        challenge = state["challenge"]
        ctx = state.get("match_context", {})

        messages = [
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=(
                f"Match: {state['match_id']}\n\n"
                f"FINAL PREDICTION:\n"
                f"  Winner: {final.predicted_winner}\n"
                f"  Margin: {final.predicted_margin}\n"
                f"  Confidence: {final.confidence}\n"
                f"  Reasoning: {final.reasoning}\n\n"
                f"Challenge strength: {challenge.challenge_strength}\n\n"
                f"Team sheets: {json.dumps(ctx.get('team_sheets', {}), default=str)}\n\n"
                "Produce the extended prediction (first try scorer candidates, margin bracket, "
                "key player to watch, upset probability)."
            )),
        ]
        result: ExtendedPrediction = structured.invoke(messages)
        return {"extended": result}

    return extended_node
