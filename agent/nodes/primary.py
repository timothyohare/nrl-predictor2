"""Primary Predictor node — ReAct tool loop producing PrimaryPrediction."""
import json
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.state import MatchPredictionState, PrimaryPrediction
from agent.tools import ALL_TOOLS
from scrapers.shared.constants import HAIKU_MODEL

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 12

_SYSTEM = """\
You are an experienced NRL analyst. For each match you will be given access to tools that
retrieve team sheets, injury lists, recent form, head-to-head records, weather forecasts,
venue profiles, coaching matchups, trap game indicators, spine synergy data, and news.

Work through the evidence in this order:
1. TEAM SHEET QUALITY — Retrieve both team sheets AND spine synergy. Identify spine absences
   (fullback 1, five-eighth 6, halfback 7, hooker 9). A new spine combination (<5 games)
   is a significant risk factor.
2. RECENT FORM — Assess momentum using the weighted form data. Pay attention to momentum
   direction (rising/falling/stable) and weighted win rate.
3. HEAD-TO-HEAD + COACHING MATCHUP — Recent H2H at venue and overall. Coaching tenure record.
4. HOME/AWAY ADVANTAGE — Quantify home ground advantage.
5. VENUE AND WEATHER — Combine venue characteristics with the actual forecast.
6. INJURY NEWS — Check injury list for late changes, suspensions.
7. TRAP GAME CHECK — Run detect_trap_game. If trap_score >= 2, seriously consider whether
   the favourite is vulnerable.
8. VERDICT — State who wins, margin, and confidence.

Rules:
- Cite the data source for every factual claim.
- Do not rely on training-data statistics — use only what the tools return.
- Named players must appear on the retrieved team sheet.
- After completing your analysis using the tools above, you will be asked to output your
  structured prediction. Use ALL of the evidence you gathered above.
"""

_EXTRACT_PROMPT = (
    "Based on your analysis above, provide your structured match prediction. "
    "Use the evidence from all the tools you called."
)


def make_primary_node(llm=None):
    def primary_node(state: MatchPredictionState) -> dict:
        model_name = state.get("primary_model", HAIKU_MODEL)
        tools = ALL_TOOLS
        tools_by_name = {t.name: t for t in tools}

        base_llm = llm
        if base_llm is None:
            from langchain_anthropic import ChatAnthropic
            from agent.lambda_handler import get_api_key
            base_llm = ChatAnthropic(model=model_name, api_key=get_api_key(), max_tokens=2048)

        bound = base_llm.bind_tools(tools)

        ctx = state.get("match_context", {})
        messages = [
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=(
                f"Analyse this match and produce a prediction.\n\n"
                f"match_id: {state['match_id']}\n"
                f"round: {state.get('round_number')}\n"
                f"season: {state.get('season')}\n"
                f"context: {json.dumps(ctx, default=str)}\n\n"
                "Use the available tools to gather evidence before producing your prediction."
            )),
        ]

        trace: list[dict] = list(state.get("agent_trace") or [])

        for _ in range(MAX_ITERATIONS):
            response: AIMessage = bound.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                break

            for tc in response.tool_calls:
                trace.append({"node": "primary", "tool": tc["name"], "input": tc["args"], "output": ""})
                try:
                    result = tools_by_name[tc["name"]].invoke(tc["args"])
                    result_str = json.dumps(result, default=str)
                    trace[-1]["output"] = result_str[:500]
                    messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))
                except Exception as e:
                    err = f"Error: {e}"
                    trace[-1]["output"] = err
                    messages.append(ToolMessage(content=err, tool_call_id=tc["id"]))
        else:
            logger.warning("Primary agent hit MAX_ITERATIONS for %s — extracting best-effort prediction", state["match_id"])

        # Extract structured prediction from the conversation history via a dedicated
        # structured-output call. This avoids fragile JSON parsing from raw text and
        # handles all content-block formats LangChain may return.
        structured = base_llm.with_structured_output(PrimaryPrediction)
        prediction: PrimaryPrediction = structured.invoke(
            messages + [HumanMessage(content=_EXTRACT_PROMPT)]
        )
        return {"primary_prediction": prediction, "agent_trace": trace}

    return primary_node
