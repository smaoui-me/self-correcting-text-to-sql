"""Safe observations of logical model calls, not individual SDK HTTP retries."""
import re
import time
from collections.abc import Mapping
from typing import TypedDict


class ModelCall(TypedDict):
    stage: str
    duration_seconds: float
    outcome: str
    error_type: str | None
    error_kind: str | None
    status_code: int | None
    token_usage: dict[str, int | None]
    rate_limit_headers: dict[str, str]


STAGES = ("generate_sql", "self_correct", "format_response")
COUNTERS = ("input_tokens", "output_tokens", "total_tokens")


def safe_headers(headers):
    """Allow only documented rate-limit fields with numeric/duration values."""
    if not isinstance(headers, Mapping):
        return {}
    patterns = {"retry-after": r"\d+(?:\.\d+)?"}
    for suffix in ("requests", "tokens"):
        for prefix in ("limit", "remaining"):
            patterns[f"x-ratelimit-{prefix}-{suffix}"] = r"\d+"
        patterns[f"x-ratelimit-reset-{suffix}"] = r"(?:\d+(?:\.\d+)?(?:ms|s|m|h|d))+"
    result = {}
    for name, value in headers.items():
        name = str(name).lower()
        value = str(value)
        if name in patterns and len(value) <= 64 and re.fullmatch(patterns[name], value):
            result[name] = value
    return result


def token_usage(response):
    usage = getattr(response, "usage_metadata", None)
    metadata = getattr(response, "response_metadata", {}) or {}
    if not isinstance(usage, Mapping):
        raw = metadata.get("token_usage", {}) if isinstance(metadata, Mapping) else {}
        raw = raw if isinstance(raw, Mapping) else {}
        usage = {"input_tokens": raw.get("prompt_tokens"),
                 "output_tokens": raw.get("completion_tokens"), "total_tokens": raw.get("total_tokens")}
    return {name: value if type(value := usage.get(name)) is int and value >= 0 else None
            for name in COUNTERS}


def invoke_observed(llm, messages, stage):
    start = time.perf_counter()
    event: ModelCall = {"stage": stage, "duration_seconds": 0.0, "outcome": "success",
        "error_type": None, "error_kind": None, "status_code": None,
        "token_usage": dict.fromkeys(COUNTERS), "rate_limit_headers": {}}
    response = None
    try:
        response = llm.invoke(messages)
    except Exception as exc:
        event.update(outcome="error", error_type=type(exc).__name__, error_kind="provider")
        status = getattr(exc, "status_code", None)
        event["status_code"] = status if type(status) is int else None
        event["rate_limit_headers"] = safe_headers(getattr(getattr(exc, "response", None), "headers", None))
    else:
        event["token_usage"] = token_usage(response)
        metadata = getattr(response, "response_metadata", {}) or {}
        if isinstance(metadata, Mapping):
            event["rate_limit_headers"] = safe_headers(metadata.get("headers"))
        if not isinstance(response.content, str) or not response.content.strip():
            event.update(outcome="error", error_type="ValueError", error_kind="response_validation")
    event["duration_seconds"] = time.perf_counter() - start
    return (response.content if event["outcome"] == "success" else None), event


def has_provider_error(record):
    if isinstance(record.get("model_calls"), list):
        return any(c["error_kind"] == "provider" for c in record["model_calls"])
    return bool(record.get("llm_error"))


def summarize_calls(records):
    observed = [r for r in records if isinstance(r.get("model_calls"), list)]
    calls = [c for r in observed for c in r["model_calls"]]
    stages = {}
    for stage in STAGES:
        group = [c for c in calls if c["stage"] == stage]
        stages[stage] = {"calls": len(group), "successes": sum(c["outcome"] == "success" for c in group),
            "errors": sum(c["outcome"] == "error" for c in group),
            "provider_errors": sum(c["error_kind"] == "provider" for c in group),
            "duration_seconds": sum(c["duration_seconds"] for c in group),
            "tokens": {key: {"reported_calls": sum(c["token_usage"][key] is not None for c in group),
                "reported_total": sum(c["token_usage"][key] for c in group if c["token_usage"][key] is not None)
                if any(c["token_usage"][key] is not None for c in group) else None} for key in COUNTERS}}
    return {"cases_recorded": len(observed), "cases_not_recorded": len(records) - len(observed),
            "by_stage": stages if observed else None,
            "provider_error_cases": sum(has_provider_error(r) for r in records)}
