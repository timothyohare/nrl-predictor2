"""Router node — classifies match difficulty and selects model tier."""
import json

from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import MatchPredictionState, RouterOutput
from scrapers.shared.constants import HAIKU_MODEL, SONNET_MODEL

_SYSTEM = """\
You are an NRL match classifier. Given a match context, classify the match difficulty
and select the appropriate model tier for the primary predictor.

Difficulty rules:
- EASY: betting spread implied by form/H2H > 12pts AND no spine injuries AND H2H favours favourite 4+/5
- CONTESTED: moderate advantage (6-12pt implied spread) OR one spine injury OR close H2H OR venue disadvantage
- COMPLEX: implied spread < 6pts OR multiple spine injuries OR finals/elimination match
  OR local derby OR away team on strong form vs home side slumping

primary_model should be:
- "claude-haiku-4-5-20251001" for EASY matches
- "claude-sonnet-4-6" for CONTESTED or COMPLEX matches

challenger_model is always "claude-sonnet-4-6".
"""


def make_router_node(llm=None):
    def router_node(state: MatchPredictionState) -> dict:
        model = llm
        if model is None:
            from langchain_anthropic import ChatAnthropic
            from agent.lambda_handler import get_api_key
            model = ChatAnthropic(model=HAIKU_MODEL, api_key=get_api_key(), max_tokens=512)

        structured = model.with_structured_output(RouterOutput)
        context_summary = json.dumps({
            "match_id": state["match_id"],
            "home_team": state.get("match_context", {}).get("home_team"),
            "away_team": state.get("match_context", {}).get("away_team"),
            "venue": state.get("match_context", {}).get("venue"),
            "is_finals": state.get("match_context", {}).get("is_finals", False),
            "home_ladder_pos": state.get("match_context", {}).get("home_ladder_pos"),
            "away_ladder_pos": state.get("match_context", {}).get("away_ladder_pos"),
            "spine_injuries": state.get("match_context", {}).get("spine_injuries", []),
        }, default=str)

        messages = [
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=f"Classify this NRL match:\n{context_summary}"),
        ]
        result: RouterOutput = structured.invoke(messages)
        return {
            "difficulty": result.difficulty,
            "difficulty_rationale": result.rationale,
            "primary_model": result.primary_model,
            "challenger_model": result.challenger_model,
        }

    return router_node
