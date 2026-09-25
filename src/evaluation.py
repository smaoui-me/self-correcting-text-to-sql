"""Deterministic execution scoring shared by pytest and the live benchmark."""
import math
from collections import deque
from typing import Any

from src.agent.state import initial_state
from src.database import Database, QueryResult


def cell_equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-6)
    return type(left) is type(right) and left == right


def results_equal(actual: QueryResult | None, expected: QueryResult, ordered: bool) -> bool:
    """Compare values by column position; aliases don't affect SQL semantics.

    Unordered comparisons retain duplicates (bag semantics). Bipartite matching
    handles ambiguous floating-point tolerance without greedy pairing errors.
    """
    if actual is None or len(actual["columns"]) != len(expected["columns"]):
        return False
    left, right = actual["rows"], expected["rows"]
    if len(left) != len(right):
        return False

    def row_equal(a, b):
        return len(a) == len(b) and all(cell_equal(x, y) for x, y in zip(a, b))

    if ordered:
        return all(row_equal(a, b) for a, b in zip(left, right))
    adjacency = [[j for j, b in enumerate(right) if row_equal(a, b)] for a in left]
    matched = {}  # expected row index -> actual row index
    assigned = {}  # actual row index -> expected row index

    def augment(start):
        # Iterative search avoids Python's recursion limit on duplicate-heavy bags.
        queue = deque([start])
        parent = {}
        while queue:
            i = queue.popleft()
            for j in adjacency[i]:
                if j in parent:
                    continue
                parent[j] = i
                if j in matched:
                    queue.append(matched[j])
                    continue
                # Flip each pair along the path to this previously unmatched row.
                while True:
                    i = parent[j]
                    previous = assigned.get(i)
                    matched[j] = i
                    assigned[i] = j
                    if previous is None:
                        return True
                    j = previous
        return False

    return all(augment(i) for i in range(len(left)))


def score_case(case: dict, state: dict, expected: QueryResult) -> dict:
    attempts = state["attempts"]
    first = attempts[0] if attempts else None
    initial_failed = first is not None and first["error"] is not None
    final_correct = results_equal(state["execution_result"], expected, case["ordered"])
    return {"id": case["id"], "initial_execution_failed": initial_failed,
            "first_try_correct": bool(first and results_equal(first["result"], expected, case["ordered"])),
            "final_correct": final_correct,
            "execution_recovered": initial_failed and state["execution_result"] is not None,
            "self_corrected": initial_failed and final_correct,
            "retry_count": state["retry_count"], "llm_error": state["llm_error"],
            "retry_latencies_seconds": [a["correction_seconds"] + a["execution_seconds"] for a in attempts[1:]],
            "attempts": attempts, "model_calls": state.get("model_calls")}


def summarize(records: list[dict]) -> dict:
    count = len(records)
    failed = sum(r["initial_execution_failed"] for r in records)
    latencies = [t for r in records for t in r["retry_latencies_seconds"]]
    return {"queries": count, "initial_execution_failures": failed,
            "first_try_accuracy": sum(r["first_try_correct"] for r in records) / count if count else None,
            "final_accuracy": sum(r["final_correct"] for r in records) / count if count else None,
            "self_correction_success_rate": sum(r["self_corrected"] for r in records) / failed if failed else None,
            "execution_recovery_rate": sum(r["execution_recovered"] for r in records) / failed if failed else None,
            "average_retry_latency_seconds": sum(latencies) / len(latencies) if latencies else None,
            "completed_retry_attempts": len(latencies)}


def evaluate_case(case: dict, database: Database, graph) -> dict:
    expected = database.execute(case["sql"])
    state = graph.invoke(initial_state(case["question"], database.schema()),
                         config={"recursion_limit": 20})
    return score_case(case, state, expected)
