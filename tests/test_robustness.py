"""Verify bank contracts and scoring separation without calling Groq."""
import json
import sys
from collections import Counter

import pytest
from langchain_core.messages import AIMessage

from scripts import benchmark_robustness as runner
from src.agent.graph import build_graph
from src.config import ROOT

BANK = json.loads(runner.BANK_PATH.read_text(encoding="utf-8"))
CASES = BANK["cases"]


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.messages = []

    def invoke(self, messages):
        self.messages.append(messages)
        return AIMessage(content=next(self.replies))


def test_bank_contract_and_family_separation():
    assert len(CASES) == 60
    assert len({case["id"] for case in CASES}) == len(CASES)
    original = json.loads((ROOT / "tests/test_dataset.json").read_text(encoding="utf-8"))
    reference = {case["id"]: case for case in original}
    sql = runner.select_cases(CASES)
    assert Counter(case["category"] for case in sql) == {
        "precise": 12, "conversational": 12, "noisy": 12}
    for case in CASES:
        assert case["question"].strip()
        assert case["review_criteria"]
        if case["scoring"] == "sql_execution":
            gold = reference[case["family_id"]]
            assert case["sql"] == gold["sql"]
            assert case["ordered"] == gold["ordered"]
            assert case["expected_behavior"] == "answer"
        else:
            assert case["sql"] is None
            assert case["ordered"] is None
    for family in {case["family_id"] for case in CASES}:
        assert len({case["split"] for case in CASES if case["family_id"] == family}) == 1


def test_filters():
    assert len(runner.select_cases(CASES, mode="all")) == 60
    assert len(runner.select_cases(CASES, mode="behavior")) == 24
    assert len(runner.select_cases(CASES, category="noisy")) == 12
    assert len(runner.select_cases(CASES, family="top_customers")) == 3
    assert len(runner.select_cases(CASES, limit=2)) == 2
    assert not runner.select_cases(CASES, category="unknown")


@pytest.mark.parametrize("case", runner.select_cases(CASES), ids=lambda case: case["id"])
def test_sql_bank_uses_existing_execution_scorer(database, case):
    record = runner.run_case(case, database, build_graph(database, ScriptedModel([case["sql"], "Answer"])), database.schema())
    assert record["first_try_correct"]
    assert record["final_correct"]
    assert "review" not in record
    assert record["expected_result"] == record["execution_result"]


def test_executable_sql_is_not_automatic_behavior_pass(database):
    case = runner.select_cases(CASES, mode="behavior")[0]
    model = ScriptedModel(["SELECT 42", "The answer is 42."])
    record = runner.run_case(case, database, build_graph(database, model), database.schema())
    assert record["review"]["verdict"] is None
    assert "final_correct" not in record
    assert record["final_answer"] == "The answer is 42."
    assert record["execution_result"]["rows"] == [[42]]
    # Metadata such as expected behavior must not be fed to the model as a hint.
    payload = json.loads(model.messages[0][1].content)
    assert set(payload) == {"question", "schema"}
    summary = runner.summarize_bank([record])
    assert summary["sql_summary"]["queries"] == 0
    assert summary["sql_summary"]["final_accuracy"] is None
    assert summary["behavior_pending_review"] == 1


def test_mixed_summary_keeps_denominators_separate(database):
    sql_case = CASES[0]
    behavior_case = runner.select_cases(CASES, mode="behavior")[0]
    sql = runner.run_case(sql_case, database, build_graph(database, ScriptedModel([sql_case["sql"], "Answer"])), database.schema())
    behavior = runner.run_case(behavior_case, database, build_graph(database, ScriptedModel(["SELECT 42", "Answer"])), database.schema())
    summary = runner.summarize_bank([sql, behavior])
    assert summary["completed_cases"] == 2
    assert summary["sql_summary"]["queries"] == 1
    assert summary["sql_summary"]["final_accuracy"] == 1
    assert summary["sql_by_category"]["precise"]["queries"] == 1
    assert summary["behavior_cases"] == 1


def test_list_needs_no_api_or_database(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["benchmark_robustness", "--mode", "all", "--list"])
    monkeypatch.setattr(runner, "configure_console", lambda: None)
    def unexpected():
        raise AssertionError("Listing must not load live configuration")
    monkeypatch.setattr(runner.Settings, "load", unexpected)
    runner.main()
    assert "Selected 60 cases; no API calls made." in capsys.readouterr().out
