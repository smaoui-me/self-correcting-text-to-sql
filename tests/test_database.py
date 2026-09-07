import sqlite3
import pytest
from src.agent.nodes import clean_sql
from src.database import Database


@pytest.mark.parametrize("sql", [
    "DELETE FROM Customer", "DROP TABLE Customer", "UPDATE Customer SET FirstName='X'",
    "INSERT INTO Artist VALUES (99, 'X')", "ATTACH DATABASE ':memory:' AS other",
    "PRAGMA query_only=OFF", "BEGIN", "SELECT 1; DELETE FROM Customer",
    "WITH x AS (SELECT 1) DELETE FROM Customer", "SELECT load_extension('x')",
])
def test_rejects_unsafe_statements(database, sql):
    with pytest.raises(sqlite3.Error):
        database.execute(sql)
    assert database.execute("SELECT COUNT(*) FROM Customer")["rows"] == [[3]]


def test_safe_cte_and_schema(database):
    assert database.execute("/* comment */ WITH x AS (SELECT 1 AS n) SELECT n FROM x")["rows"] == [[1]]
    assert "REFERENCES" in database.schema()


def test_result_limit_is_error_not_silent_truncation(database):
    with pytest.raises(sqlite3.OperationalError, match="exceeds"):
        Database(database.path, max_rows=1).execute("SELECT * FROM Customer")


def test_timeout(database):
    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        Database(database.path, timeout=0.001).execute(
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) SELECT SUM(x) FROM n")


def test_missing_database_does_not_create_file(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        Database(path)
    assert not path.exists()


@pytest.mark.parametrize("text", ["SELECT 1", "```sql\nSELECT 1\n```", "```\nSELECT 1\n```"])
def test_sql_fences(text):
    assert clean_sql(text) == "SELECT 1"
