"""Render existing benchmark JSON as Markdown without model or network calls."""
import argparse
import json
from collections import Counter
from pathlib import Path

from src.config import configure_console
from src.evaluation import summarize


def percentage(value):
    return "N/A" if value is None else f"{100 * value:.1f}%"


def render_report(report):
    records = report["cases"]
    sql = [r for r in records if r.get("scoring", "sql_execution") == "sql_execution"]
    behavior = [r for r in records if r.get("scoring") == "manual_behavior"]
    metrics = summarize(sql)  # Recompute rather than trust a stale saved summary.
    meta = report.get("metadata", {})
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
    latency = metrics["average_retry_latency_seconds"]
    lines.append(f"| Average completed retry latency | {'N/A' if latency is None else f'{latency:.3f} s'} |")
    lines += ["", "### By wording category", "", "| Category | N | First try | Final |",
              "| --- | ---: | ---: | ---: |"]
    for category in sorted({r.get("category", "original") for r in sql}):
        group = summarize([r for r in sql if r.get("category", "original") == category])
        lines.append(f"| {category} | {group['queries']} | {percentage(group['first_try_accuracy'])} | {percentage(group['final_accuracy'])} |")
    if behavior:
        lines += ["", "## Behavioral review", "",
                  "Counts are taken from human review fields; responses are not automatically judged.", "",
                  "| Category | Pass | Partial | Fail | Provider error | Pending |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for category in sorted({r["category"] for r in behavior}):
            counts = Counter(r.get("review", {}).get("verdict") or "pending"
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
