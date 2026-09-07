"""Exercise the CLI consumer with actual LangGraph stream events, offline."""
import sys

import pytest
from langchain_core.messages import AIMessage

import main as cli


@pytest.mark.parametrize("replies, expected", [
    ([RuntimeError("provider unavailable")], "The model request failed"),
    (["SELECT Missing FROM Customer", RuntimeError("provider unavailable")],
     "The model request failed"),
    (["SELECT 1", "The answer is 1."], "The answer is 1."),
])
def test_cli_stream_handles_provider_failure_and_success(monkeypatch, capsys, database, replies, expected):
    class ScriptedModel:
        def __init__(self):
            self.replies = iter(replies)

        def invoke(self, messages):
            reply = next(self.replies)
            if isinstance(reply, Exception):
                raise reply
            return AIMessage(content=reply)

    monkeypatch.setattr(sys, "argv", ["main.py", "--question", "Return one"])
    monkeypatch.setattr(cli, "configure_console", lambda: None)
    monkeypatch.setattr(cli.Settings, "load", lambda: cli.Settings(database.path))
    monkeypatch.setattr(cli, "create_llm", lambda settings: ScriptedModel())

    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "[execute_sql]" in output
    assert expected in output
