"""Pure routing functions: inspect state without mutating it."""
from typing import Literal
from src.agent.state import AgentState

MAX_FAILURES = 3


def should_retry(state: AgentState) -> Literal["self_correct", "graceful_failure", "format_response"]:
    if state["llm_error"]:
        return "graceful_failure"
    if state["error_message"] is not None:
        return "self_correct" if state["retry_count"] < MAX_FAILURES else "graceful_failure"
    return "format_response"
