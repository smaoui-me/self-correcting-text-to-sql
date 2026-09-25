"""Render existing benchmark JSON as Markdown without model or network calls."""
import argparse
import json
from collections import Counter
from pathlib import Path

from src.config import configure_console
from src.evaluation import summarize
from src.telemetry import summarize_calls, has_provider_error


def percentage(value):
    return "N/A" if value is None else f"{100 * value:.1f}%"


def render_report(report):
    records = report["cases"]
    sql = [r for r in records if r.get("scoring", "sql_execution") == "sql_execution"]
    behavior = [r for r in records if r.get("scoring") == "manual_behavior"]
    metrics = summarize(sql)  # Recompute rather than trust a stale saved summary.
    meta = report.get("metadata", {})
    provider_errors = Counter(r["llm_error"] for r in records if r.get("llm_error"))
    telemetry = summarize_calls(records)
    attempted_sql_cases = sum(bool(r.get("attempts")) for r in sql)
    selected = meta.get("selected_case_ids")
    coverage = f"{len(records)}/{len(selected)} selected cases" if selected is not None else f"{len(records)} cases; planned run size not recorded"
    lines = ["# Benchmark results", "", f"- Model: `{meta.get('model', 'not recorded')}`",
             f"- Recorded at: {meta.get('utc', 'not recorded')}", f"- Coverage: {coverage}",
             f"- Database SHA-256: `{meta.get('database_sha256', 'not recorded')}`",
             f"- Dataset SHA-256: `{meta.get('bank_sha256', meta.get('dataset_sha256', 'not recorded'))}`",
             "", "## SQL execution", "",
             "| Metric | Value |", "| --- | ---: |",
             f"| Scored questions | {len(sql)} |",
             f"| First-try accuracy | {percentage(metrics['first_try_accuracy'])} |",
             f"| Final accuracy | {percentage(metrics['final_accuracy'])} |",
             f"| Initial SQL failures | {metrics['initial_execution_failures']} |",
             f"| Correction success | {percentage(metrics['self_correction_success_rate'])} |",
             f"| Execution recovery | {percentage(metrics['execution_recovery_rate'])} |"]
    health = ["", "## Run health", "",
              f"- Cases with generation/repair provider errors: {sum(provider_errors.values())}/{len(records)}."]
    if all("attempts" in r for r in sql):
        health.append(f"- SQL cases reaching database execution: {attempted_sql_cases}/{len(sql)}.")
    for error, count in sorted(provider_errors.items()):
        health.append(f"- `{error}`: {count} cases.")
    if records and sum(provider_errors.values()) == len(records) and all(not r.get("attempts") for r in records):
        health += ["", "**Provider failure: no generated SQL was executed. This run does not measure model SQL quality.**",
                   "The accuracy values below retain provider failures in their denominators; they are end-to-end outcomes, not evidence of incorrect generated queries."]
    if "AuthenticationError" in provider_errors:
        health.append("- Check the Groq credential supplied to the running process/container before repeating the benchmark.")
    position = lines.index("## SQL execution")
    lines[position:position] = health + [""]
    latency = metrics["average_retry_latency_seconds"]
    lines.append(f"| Average completed retry latency | {'N/A' if latency is None else f'{latency:.3f} s'} |")
    lines += ["", "### By wording category", "", "| Category | N | First try | Final |",
              "| --- | ---: | ---: | ---: |"]
    for category in sorted({r.get("category", "original") for r in sql}):
        group = summarize([r for r in sql if r.get("category", "original") == category])
        lines.append(f"| {category} | {group['queries']} | {percentage(group['first_try_accuracy'])} | {percentage(group['final_accuracy'])} |")
    lines += ["", "## Model-call telemetry", "",
              f"- Cases with telemetry: {telemetry['cases_recorded']}/{len(records)}.",
              f"- Cases with any recorded provider error (including formatting): {telemetry['provider_error_cases']}.",
              f"- Stage telemetry not recorded: {telemetry['cases_not_recorded']} cases."]
    if telemetry["cases_not_recorded"]:
        lines.append("- Legacy records cannot establish formatting completion or total provider failures; their recorded errors are a lower bound.")
    if telemetry["by_stage"] is None:
        lines.append("- Formatting completion, stage durations, and token usage: not recorded.")
    else:
        lines += ["", "Only instrumented cases contribute below. Calls are logical invocations, including SDK retry time; individual HTTP attempts are not observed.", "",
                  "| Stage | Calls | Completed | Errors | Provider errors | Total seconds | Reported total tokens | Token coverage (calls) |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for stage, stats in telemetry["by_stage"].items():
            tokens = stats["tokens"]["total_tokens"]
            total = tokens["reported_total"] if tokens["reported_total"] is not None else "not recorded"
            lines.append(f"| {stage} | {stats['calls']} | {stats['successes']} | {stats['errors']} | {stats['provider_errors']} | {stats['duration_seconds']:.3f} | {total} | {tokens['reported_calls']}/{stats['calls']} |")
        formatting = telemetry["by_stage"]["format_response"]
        completion = formatting["successes"] / formatting["calls"] if formatting["calls"] else None
        lines += ["", f"Formatting completion (successful formatting calls / attempted formatting calls): {percentage(completion)}.",
                  "Empty-result responses skip the formatting call. Completion does not measure answer faithfulness. Token totals cover only calls with reported usage."]
    if behavior:
        lines += ["", "## Behavioral review", "",
                  "Human verdicts take precedence. Unreviewed cases with a recorded provider error are counted as provider errors; other cases remain pending. Responses are not automatically judged.", "",
                  "| Category | Pass | Partial | Fail | Provider error | Pending |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for category in sorted({r["category"] for r in behavior}):
            counts = Counter(r.get("review", {}).get("verdict") or ("provider_error" if has_provider_error(r) else "pending")
                             for r in behavior if r["category"] == category)
            unknown = set(counts) - {"pass", "partial", "fail", "provider_error", "pending"}
            if unknown:
                raise ValueError(f"Unknown review verdicts: {sorted(unknown)}")
            lines.append(f"| {category} | " + " | ".join(str(counts[k]) for k in
                         ("pass", "partial", "fail", "provider_error", "pending")) + " |")
    lines += ["", "## Interpretation", ""]
    if sql:
        wrong = sum(not r["final_correct"] for r in sql)
        lines.append(f"- {len(sql) - wrong}/{len(sql)} recorded SQL cases matched the reference result.")
        if metrics["initial_execution_failures"] == 0:
            lines.append("- No recorded case entered SQL correction. This run cannot estimate the benefit of self-correction.")
        else:
            lines.append("- Correction success is conditional on initial execution failure; it does not measure repair of executable but semantically wrong SQL.")
        if wrong:
            lines.append("- Inspect these incorrect cases in the JSON: " + ", ".join(f"`{r['id']}`" for r in sql if not r["final_correct"]) + ".")
    if selected is not None and len(records) != len(selected):
        lines.append("- This report is incomplete relative to its selected case list.")
    lines += ["- Matched paraphrases are correlated observations, not independent SQL tasks.",
              "- These development/diagnostic results do not establish performance on unseen schemas or held-out questions.",
              "- SQL result accuracy does not measure natural-language answer faithfulness.",
              "- Compare repeated runs and category counts before drawing conclusions from small percentage differences.", ""]
    return "\n".join(lines)


def main():
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.resolve() == args.report.resolve():
        parser.error("Output must differ from the source JSON")
    result = render_report(json.loads(args.report.read_text(encoding="utf-8-sig")))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
        print(f"Report: {args.output.resolve()}")
    else:
        print(result)


if __name__ == "__main__":
    main()
