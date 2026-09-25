import json
from types import SimpleNamespace

import httpx
import pytest
from groq import RateLimitError
from langchain_core.messages import AIMessage

from src.agent.graph import build_graph
from src.agent.state import initial_state
from src.evaluation import score_case
from src.telemetry import invoke_observed, summarize_calls, safe_headers
from scripts.report_results import render_report


def limited():
    response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"),
        headers={"Retry-After": "12", "x-ratelimit-remaining-tokens": "0",
                 "x-ratelimit-reset-tokens": "2m1.5s", "authorization": "secret"})
    return RateLimitError("secret error body", response=response, body={"secret": "private"})


class Model:
    def __init__(self, replies):
        self.replies = iter(replies)

    def invoke(self, messages):
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return AIMessage(content=reply) if isinstance(reply, str) else reply


@pytest.mark.parametrize("stage,replies", [
    ("generate_sql", [limited()]),
    ("self_correct", ["SELECT Missing", limited()]),
    ("format_response", ["SELECT 1", limited()]),
])
def test_stage_failures_recorded_without_changing_routing(database, stage, replies):
    state = build_graph(database, Model(replies)).invoke(initial_state("One", database.schema()))
    event = state["model_calls"][-1]
    assert event["stage"] == stage
    assert event["outcome"] == "error"
    assert event["error_type"] == "RateLimitError"
    assert event["status_code"] == 429
    assert event["rate_limit_headers"]["retry-after"] == "12"
    assert "secret" not in json.dumps(state["model_calls"])
    assert event["token_usage"]["total_tokens"] is None
    assert summarize_calls([state])["provider_error_cases"] == 1
    if stage == "format_response":
        assert state["llm_error"] is None
        assert state["execution_result"]["rows"] == [[1]]
        record = score_case({"id": "one", "ordered": True}, state, database.execute("SELECT 1"))
        assert record["final_correct"]
        text = render_report({"cases": [record]})
        assert "Final accuracy | 100.0%" in text
        assert "Formatting completion (successful formatting calls / attempted formatting calls): 0.0%" in text


def test_success_tokens_timing_and_absent_usage(monkeypatch):
    times = iter([10.0, 12.5])
    monkeypatch.setattr("src.telemetry.time.perf_counter", lambda: next(times))
    message = AIMessage(content="SELECT 1", usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13})
    content, event = invoke_observed(Model([message]), [], "generate_sql")
    assert content == "SELECT 1"
    assert event["duration_seconds"] == 2.5
    assert event["token_usage"]["total_tokens"] == 13
    assert event["error_type"] is None


def test_metadata_fallback_and_sanitization():
    message = SimpleNamespace(content="ok", response_metadata={"token_usage": {
        "prompt_tokens": 4, "completion_tokens": 0, "total_tokens": 4, "secret": "private"},
        "headers": {"retry-after": "secret", "set-cookie": "secret"}})
    _, event = invoke_observed(Model([message]), [], "format_response")
    assert event["token_usage"] == {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4}
    assert event["rate_limit_headers"] == {}
    assert safe_headers({"retry-after": "3\nsecret"}) == {}


def test_invalid_response_is_not_provider_failure():
    _, event = invoke_observed(Model([AIMessage(content="")]), [], "generate_sql")
    assert event["error_kind"] == "response_validation"
    assert summarize_calls([{"model_calls": [event]}])["provider_error_cases"] == 0


def test_empty_result_skips_format_and_histories_are_isolated(database):
    graph = build_graph(database, Model(["SELECT 1 WHERE 0", "SELECT 2", "Two"]))
    first = graph.invoke(initial_state("Empty", database.schema()))
    second = graph.invoke(initial_state("Two", database.schema()))
    assert [c["stage"] for c in first["model_calls"]] == ["generate_sql"]
    assert [c["stage"] for c in second["model_calls"]] == ["generate_sql", "format_response"]


def test_legacy_and_partial_coverage_do_not_invent_zeros():
    legacy = {"llm_error": None}
    assert summarize_calls([legacy])["by_stage"] is None
    _, event = invoke_observed(Model(["ok"]), [], "generate_sql")
    summary = summarize_calls([legacy, {"model_calls": [event]}])
    assert summary["cases_not_recorded"] == 1
    assert summary["by_stage"]["generate_sql"]["tokens"]["total_tokens"]["reported_total"] is None
    text = render_report({"cases": []})
    assert "stage durations, and token usage: not recorded" in text
