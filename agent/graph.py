"""LangGraph StateGraph for the multi-agent NRL prediction pipeline."""
from langgraph.graph import END, StateGraph

from agent.nodes.challenger import make_challenger_node
from agent.nodes.extended import make_extended_node
from agent.nodes.judge import make_judge_node
from agent.nodes.primary import make_primary_node
from agent.nodes.router import make_router_node
from agent.state import MatchPredictionState


def build_graph(
    router_llm=None,
    primary_llm=None,
    challenger_llm=None,
    judge_llm=None,
    extended_llm=None,
):
    """Compile and return the prediction graph. Pass LLM overrides for testing."""
    graph = StateGraph(MatchPredictionState)

    graph.add_node("router", make_router_node(llm=router_llm))
    graph.add_node("primary", make_primary_node(llm=primary_llm))
    graph.add_node("challenger", make_challenger_node(llm=challenger_llm))
    graph.add_node("judge", make_judge_node(llm=judge_llm))
    graph.add_node("extended", make_extended_node(llm=extended_llm))

    graph.set_entry_point("router")
    graph.add_edge("router", "primary")
    graph.add_edge("primary", "challenger")
    graph.add_edge("challenger", "judge")
    graph.add_edge("judge", "extended")
    graph.add_edge("extended", END)

    return graph.compile()


# Module-level compiled graph — cached after Lambda cold start
_app = None


def get_app():
    global _app
    if _app is None:
        _app = build_graph()
    return _app
