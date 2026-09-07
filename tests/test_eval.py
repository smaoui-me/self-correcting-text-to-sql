"""These tests validate scoring and routing, not Groq model accuracy."""
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.agent.graph import build_graph
from src.agent.state import initial_state
from src.evaluation import evaluate_case, results_equal, score_case, summarize

CASES = json.loads(Path(__file__).with_name("test_dataset.json").read_text(encoding="utf-8"))

# Independently calculated answers on the small fixture anchor the golden SQL.
EXPECTED = {
    "top_customers": [[1, "Ana", "A", 8.0], [2, "Bob", "B", 2.0]],
    "country_revenue": [["USA", 2, 8.0], ["Canada", 1, 2.0]],
    "genre_revenue": [[1, "Rock", 3, 6.0], [2, "Jazz", 2, 4.0]],
    "artist_catalog": [[1, "Alpha", 1, 2], [2, "Beta", 1, 1]],
    "support_sales": [[1, "Sam", "Rep", 3, 10.0]],
    "monthly_revenue": [["2024-01", 1, 6.0], ["2024-02", 2, 4.0]],
    "above_average_customers": [[1, 8.0]],
    "unsold_by_genre": [[1, "Rock", 1]],
    "playlist_duration": [[1, "Mix", 2, 3.0], [2, "Empty", 0, 0.0]],
    "rock_customers": [[1, "a@example.test"]],
    "albums_with_ten_tracks": [],
    "top_tracks": [[1, "One", "Alpha", 3], [2, "Two", "Alpha", 2]],
}


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.messages = []

    def invoke(self, messages):
        self.messages.append(messages)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return AIMessage(content=reply)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_golden_sql_on_known_fixture(database, case):
    assert database.execute(case["sql"])["rows"] == EXPECTED[case["id"]]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("failures", [0, 1, 2])
def test_evaluation_paths(database, case, failures):
    model = ScriptedModel(["SELECT MissingColumn FROM Customer"] * failures + [case["sql"], "Answer"])
    record = evaluate_case(case, database, build_graph(database, model))
    assert record["first_try_correct"] == (failures == 0)
    assert record["final_correct"]
    assert record["self_corrected"] == (failures > 0)
    assert len(record["retry_latencies_seconds"]) == failures
    assert all(t >= 0 for t in record["retry_latencies_seconds"])


def test_exhaustion_and_raw_error_feedback(database):
    model = ScriptedModel(["SELECT Missing FROM Customer"] * 3)
    state = build_graph(database, model).invoke(initial_state("List customers", database.schema()))
    assert state["retry_count"] == 3
    assert len(state["attempts"]) == 3
    assert state["execution_result"] is None
    assert "3 attempts" in state["final_answer"]
    assert "Traceback" in state["error_message"]
    repair_payload = json.loads(model.messages[1][1].content)
    assert "no such column: Missing" in repair_payload["error"]
    assert repair_payload["failed_sql"] == "SELECT Missing FROM Customer"


def test_wrong_but_executable_is_not_corrected(database):
    model = ScriptedModel(["SELECT 42", "A misleading answer"])
    record = evaluate_case(CASES[0], database, build_graph(database, model))
    assert not record["final_correct"]
    assert not record["initial_execution_failed"]
    assert len(record["attempts"]) == 1


def test_execution_recovery_does_not_imply_correctness(database):
    model = ScriptedModel(["SELECT Missing FROM Customer", "SELECT 42", "Answer"])
    record = evaluate_case(CASES[0], database, build_graph(database, model))
    summary = summarize([record])
    assert summary["execution_recovery_rate"] == 1
    assert summary["self_correction_success_rate"] == 0


@pytest.mark.parametrize("replies, attempts", [([RuntimeError("secret")], 0),
    (["SELECT Missing FROM Customer", RuntimeError("secret")], 1)])
def test_provider_failure_terminates(database, replies, attempts):
    state = build_graph(database, ScriptedModel(replies)).invoke(initial_state("Question", database.schema()))
    assert len(state["attempts"]) == attempts
    assert state["llm_error"] == "RuntimeError"
    assert "secret" not in state["final_answer"]


def test_formatter_failure_preserves_results(database):
    state = build_graph(database, ScriptedModel(["SELECT 7", RuntimeError()])).invoke(initial_state("Seven", database.schema()))
    assert state["execution_result"]["rows"] == [[7]]
    assert "formatting is unavailable" in state["final_answer"]


def test_empty_result_is_success(database):
    state = build_graph(database, ScriptedModel(["SELECT * FROM Customer WHERE 0"])).invoke(initial_state("Nobody", database.schema()))
    assert state["retry_count"] == 0
    assert state["error_message"] is None
    assert state["final_answer"] == "No matching rows were found."


def test_streamed_cycle_clears_error(database):
    model = ScriptedModel(["SELECT Missing FROM Customer", "SELECT 1", "One"])
    events = list(build_graph(database, model).stream(initial_state("One", database.schema()), stream_mode="updates"))
    assert [next(iter(event)) for event in events] == ["generate_sql", "execute_sql", "self_correct", "execute_sql", "format_response"]
    assert events[3]["execute_sql"]["error_message"] is None


def result(rows, columns=None):
    return {"columns": columns or ["value"], "rows": rows}


def test_comparator_semantics():
    assert results_equal(result([[1], [2]]), result([[2], [1]]), ordered=False)
    assert not results_equal(result([[1], [2]]), result([[2], [1]]), ordered=True)
    assert not results_equal(result([[1], [1]]), result([[1], [2]]), ordered=False)
    assert results_equal(result([[0.1 + 0.2], [None]]), result([[0.3], [None]]), ordered=True)
    assert not results_equal(result([[None]]), result([[0]]), ordered=False)
    assert not results_equal(result([["1"]]), result([[1]]), ordered=False)
    assert not results_equal(result([], ["a", "b"]), result([], ["a"]), ordered=True)
    assert not results_equal(None, result([]), ordered=False)


def test_metric_denominators_and_latency(database):
    records = []
    for replies in ([CASES[0]["sql"], "Answer"],
                    ["SELECT Missing", CASES[0]["sql"], "Answer"],
                    ["SELECT Missing"] * 3):
        state = build_graph(database, ScriptedModel(replies)).invoke(initial_state("Q", database.schema()))
        for attempt in state["attempts"][1:]:
            attempt["execution_seconds"] = 1.0
            attempt["correction_seconds"] = 2.0
        records.append(score_case(CASES[0], state, database.execute(CASES[0]["sql"])))
    summary = summarize(records)
    assert summary["first_try_accuracy"] == 1 / 3
    assert summary["final_accuracy"] == 2 / 3
    assert summary["self_correction_success_rate"] == 1 / 2
    assert summary["average_retry_latency_seconds"] == 3.0
    assert summarize([])["first_try_accuracy"] is None
    assert summarize(records[:1])["self_correction_success_rate"] is None


def test_unordered_matching_reassigns_tolerance_pairs():
    # First actual row matches either expected row; second matches only the first.
    assert results_equal(result([[0.0000009], [0.0]]),
                         result([[0.0], [0.0000018]]), ordered=False)


def test_unordered_duplicate_bag_at_result_limit():
    assert results_equal(result([[1]] * 1000), result([[1]] * 1000), ordered=False)


@pytest.mark.parametrize("count, included", [(9, False), (10, True), (11, True)])
def test_having_boundary(database, count, included):
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(database.path)) as connection:
        connection.executemany("INSERT INTO Track VALUES (?, ?, 2, 1, 60000)",
                               [(100 + i, f"Extra {i}") for i in range(count - 1)])
        connection.commit()
    case = next(case for case in CASES if case["id"] == "albums_with_ten_tracks")
    rows = database.execute(case["sql"])["rows"]
    assert rows == ([[2, "Second", count]] if included else [])


def test_real_chinook_golden_queries():
    from src.config import ROOT
    from src.database import Database
    path = ROOT / "chinook.db"
    if not path.exists():
        pytest.skip("Run scripts/setup_db.py to also validate the real Chinook release")
    database = Database(path)
    for case in CASES:
        first = database.execute(case["sql"])
        assert first["rows"], case["id"]
        assert results_equal(first, database.execute(case["sql"]), case["ordered"])
