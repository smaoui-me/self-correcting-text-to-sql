"""Interactive demo: python main.py or python main.py --question '...'"""
import argparse
import logging

from src.agent.graph import build_graph
from src.agent.state import initial_state
from src.config import Settings, configure_console, create_llm
from src.database import Database


def main() -> int:
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    try:
        settings = Settings.load()
        database = Database(settings.database_path)
        graph = build_graph(database, create_llm(settings))
        schema = database.schema()
        while True:
            question = args.question if args.question is not None else input("\nAsk about Chinook (quit to exit): ")
            if question.strip().lower() in {"quit", "exit"}:
                return 0
            if not question.strip():
                if args.question is not None:
                    raise ValueError("Question must not be empty")
                continue
            for event in graph.stream(initial_state(question, schema),
                                      config={"recursion_limit": 20}, stream_mode="updates"):
                for node, update in event.items():
                    print(f"[{node}]")
                    # Nodes that write no state can stream a None update.
                    # Keep consuming events so graceful_failure still runs.
                    if update is None:
                        continue
                    if "generated_sql" in update:
                        print(update["generated_sql"])
                    if update.get("error_message"):
                        print(update["error_message"].strip().splitlines()[-1])
                    if update.get("final_answer"):
                        print(update["final_answer"])
            if args.question is not None:
                return 0
    except (KeyboardInterrupt, EOFError):
        return 0
    except (ValueError, OSError) as exc:
        print(f"Setup error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
