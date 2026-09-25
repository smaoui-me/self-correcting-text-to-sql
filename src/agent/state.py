"""State is the shared contract between nodes, not a conversation transcript."""
from typing import TypedDict
from src.database import QueryResult
from src.telemetry import ModelCall


class Attempt(TypedDict):
    sql: str
    result: QueryResult | None
    error: str | None
    execution_seconds: float
    correction_seconds: float


class AgentState(TypedDict):
    question: str  # Original user intent; never rewritten by the repair loop.
    schema: str  # SQLite DDL including foreign keys; inspected once per request.
    generated_sql: str  # Replaced by generate_sql and each self_correct call.
    execution_result: QueryResult | None  # None means no successful result yet.
    error_message: str | None  # Raw sqlite traceback; cleared on success.
    retry_count: int  # Number of failed executions (NOT number of LLM calls).
    final_answer: str  # User-facing response, set by a terminal node.
    attempts: list[Attempt]  # New list returned each time; no in-place mutation.
    correction_seconds: float  # Duration of the repair producing the next SQL.
    llm_error: str | None  # Provider failure is distinct from invalid SQL.
    model_calls: list[ModelCall]  # Includes formatter failures; one record per invoke.


def initial_state(question: str, schema: str) -> AgentState:
    if not question.strip():
        raise ValueError("Question must not be empty")
    return {"question": question.strip(), "schema": schema, "generated_sql": "",
            "execution_result": None, "error_message": None, "retry_count": 0,
            "final_answer": "", "attempts": [], "correction_seconds": 0.0,
            "llm_error": None, "model_calls": []}
