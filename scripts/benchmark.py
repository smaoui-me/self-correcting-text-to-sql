"""Opt-in Groq benchmark: python -m scripts.benchmark."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from src.agent.graph import build_graph
from src.config import ROOT, Settings, configure_console, create_llm
from src.database import Database
from src.evaluation import evaluate_case, summarize
from src.telemetry import summarize_calls


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    args = parser.parse_args()
    settings = Settings.load()
    database = Database(settings.database_path)
    graph = build_graph(database, create_llm(settings))
    dataset_path = ROOT / "tests/test_dataset.json"
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    records = []
    metadata = {"utc": datetime.now(timezone.utc).isoformat(), "model": settings.model,
                "python": platform.python_version(), "temperature": 0,
                "database_sha256": hashlib.sha256(database.path.read_bytes()).hexdigest(),
                "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                "packages": {name: importlib.metadata.version(name) for name in
                             ("langgraph", "langchain-core", "langchain-groq")}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        record = evaluate_case(case, database, graph)
        records.append(record)
        print(f"{case['id']}: first={record['first_try_correct']} final={record['final_correct']} failures={record['retry_count']}")
        # Save after each question so an interrupted run still has usable records.
        report = {"metadata": {**metadata, "telemetry_version": 1}, "summary": summarize(records),
                  "model_telemetry": summarize_calls(records), "cases": records}
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
