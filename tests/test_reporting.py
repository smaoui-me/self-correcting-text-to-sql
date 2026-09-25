"""Reports recompute observations without conflating behavior and SQL accuracy."""
import pytest
from scripts.report_results import render_report


def sql_record():
    return {"id": "example", "scoring": "sql_execution", "category": "precise",
            "initial_execution_failed": False, "first_try_correct": True,
            "final_correct": True, "self_corrected": False,
            "execution_recovered": False, "retry_latencies_seconds": []}


def test_report_recomputes_stale_summary_and_flags_incomplete_run():
    report = {"metadata": {"selected_case_ids": ["example", "missing"]},
              "summary": {"final_accuracy": 0}, "cases": [sql_record()]}
    text = render_report(report)
    assert "100.0%" in text
    assert "1/2 selected cases" in text
    assert "incomplete" in text
    assert "cannot estimate the benefit" in text
    assert "Correction success | N/A" in text


def test_behavior_reviews_do_not_increase_sql_accuracy_denominator():
    behavior = {"id": "ambiguous", "scoring": "manual_behavior",
                "category": "ambiguous_metric", "review": {"verdict": "fail"}}
    text = render_report({"cases": [sql_record(), behavior]})
    assert "Scored questions | 1" in text
    assert "ambiguous_metric | 0 | 0 | 1 | 0 | 0" in text


def test_report_rejects_invalid_review_label():
    with pytest.raises(ValueError, match="Unknown review"):
        render_report({"cases": [{"scoring": "manual_behavior", "category": "scope",
                                  "review": {"verdict": "probably"}}]})


def test_empty_report_does_not_invent_accuracy():
    text = render_report({"cases": []})
    assert "Final accuracy | N/A" in text
    assert "100.0%" not in text


def test_authentication_failure_is_not_presented_as_sql_quality():
    record = sql_record()
    record.update(first_try_correct=False, final_correct=False,
                  llm_error="AuthenticationError", attempts=[])
    behavior = {"id": "ambiguous", "scoring": "manual_behavior",
                "category": "ambiguous_metric", "llm_error": "AuthenticationError",
                "attempts": [], "review": {"verdict": None}}
    text = render_report({"cases": [record, behavior]})
    assert "does not measure model SQL quality" in text
    assert "AuthenticationError`: 2 cases" in text
    assert "SQL cases reaching database execution: 0/1" in text
    assert "ambiguous_metric | 0 | 0 | 0 | 1 | 0" in text
    assert "Final accuracy | 0.0%" in text
