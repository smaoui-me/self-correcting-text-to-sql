"""Compile the bounded cycle; all dependencies are supplied by the caller."""
from langgraph.graph import END, START, StateGraph
from src.agent.edges import should_retry
from src.agent.nodes import AgentNodes, ChatModel
from src.agent.state import AgentState
from src.database import Database


def build_graph(database: Database, llm: ChatModel):
    nodes = AgentNodes(database, llm)
    builder = StateGraph(AgentState)
    for name in ("generate_sql", "execute_sql", "self_correct", "format_response", "graceful_failure"):
        builder.add_node(name, getattr(nodes, name))
    builder.add_edge(START, "generate_sql")
    builder.add_edge("generate_sql", "execute_sql")
    builder.add_conditional_edges("execute_sql", should_retry,
                                  {name: name for name in ("self_correct", "graceful_failure", "format_response")})
    builder.add_edge("self_correct", "execute_sql")
    builder.add_edge("format_response", END)
    builder.add_edge("graceful_failure", END)
    return builder.compile()
