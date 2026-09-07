"""Run the labeled question bank; behavioral cases require human review."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from src.agent.graph import build_graph
from src.agent.state import initial_state
from src.config import ROOT, Settings, configure_console, create_llm
from src.database import Database
from src.evaluation import score_case, summarize

BANK_PATH = ROOT / "benchmarks/question_bank.json"


def select_cases(cases, mode="sql", category=None, family=None, limit=None):
    scoring = {"sql": "sql_execution", "behavior": "manual_behavior"}
    selected = [case for case in cases
                if (mode == "all" or case["scoring"] == scoring[mode])
                and (category is None or case["category"] == category)
                and (family is None or case["family_id"] == family)]
    return selected if limit is None else selected[:limit]


def run_case(case, database, graph, schema):
    # Reference answers stay outside graph state and model prompts.
    expected = database.execute(case["sql"]) if case["scoring"] == "sql_execution" else None
    start = time.perf_counter()
    state = graph.invoke(initial_state(case["question"], schema), config={"recursion_limit": 20})
    elapsed = time.perf_counter() - start
    record = {key: case[key] for key in (
        "id", "family_id", "split", "category", "clarity", "wording", "question",
        "expected_behavior", "scoring", "review_criteria", "notes")}
    record.update({"elapsed_seconds": elapsed, "generated_sql": state["generated_sql"],
                   "final_answer": state["final_answer"], "execution_result": state["execution_result"],
                   "llm_error": state["llm_error"], "attempts": state["attempts"]})
    if expected is not None:
        record.update(score_case(case, state, expected))
        record["expected_result"] = expected
    else:
        # A generic failure is not a clarification, and executable SQL is not
        # evidence that an ambiguous or unsupported request was handled well.
        record["review"] = {"verdict": None, "reviewer": None, "reason": None}
    return record


def summarize_bank(records):
    sql = [record for record in records if record["scoring"] == "sql_execution"]
    behavior = [record for record in records if record["scoring"] == "manual_behavior"]
    return {
        "completed_cases": len(records),
        "sql_summary": summarize(sql),
        "sql_by_category": {category: summarize([r for r in sql if r["category"] == category])
                            for category in sorted({r["category"] for r in sql})},
        "sql_by_family": {family: summarize([r for r in sql if r["family_id"] == family])
                          for family in sorted({r["family_id"] for r in sql})},
        "behavior_cases": len(behavior),
        "behavior_pending_review": sum(r["review"]["verdict"] is None for r in behavior),
        "provider_error_cases": sum(r["llm_error"] is not None for r in records),
    }


def main():
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["sql", "behavior", "all"], default="sql")
    parser.add_argument("--category", help="Filter by category label in the question bank")
    parser.add_argument("--family", help="Run matched variants of one SQL intent")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--list", action="store_true", help="List selected cases without model calls")
    parser.add_argument("--output", type=Path, default=Path("benchmark-results-robustness.json"))
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    bank = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    cases = select_cases(bank["cases"], args.mode, args.category, args.family, args.limit)
    if not cases:
        parser.error("No cases matched; check --mode, --category, and --family")
    if args.list:
        for case in cases:
            print(f"{case['id']} [{case['scoring']}]: {case['question']}")
        print(f"Selected {len(cases)} cases; no API calls made.")
        return
    if args.output.exists():
        parser.error("Output already exists; choose another --output to preserve previous runs")
    settings = Settings.load()
    database = Database(settings.database_path)
    graph = build_graph(database, create_llm(settings))
    schema = database.schema()
    metadata = {
        "utc": datetime.now(timezone.utc).isoformat(), "model": settings.model,
        "temperature": 0, "python": platform.python_version(),
        "bank_version": bank["version"],
        "bank_sha256": hashlib.sha256(BANK_PATH.read_bytes()).hexdigest(),
        "database_sha256": hashlib.sha256(database.path.read_bytes()).hexdigest(),
        "selected_case_ids": [case["id"] for case in cases],
        "packages": {name: importlib.metadata.version(name) for name in
                     ("langgraph", "langchain-core", "langchain-groq")},
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted((ROOT / "src").rglob("*.py"))},
    }
    records = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        record = run_case(case, database, graph, schema)
        records.append(record)
        status = f"correct={record['final_correct']}" if case["scoring"] == "sql_execution" else "manual review required"
        print(f"{case['id']}: {status}")
        report = {"metadata": metadata, "summary": summarize_bank(records), "cases": records}
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(args.output)
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
