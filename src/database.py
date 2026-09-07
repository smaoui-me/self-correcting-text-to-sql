"""SQLite execution boundary: read-only, single statement, bounded work/results."""
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, TypedDict


class QueryResult(TypedDict):
    columns: list[str]
    rows: list[list[Any]]


class Database:
    def __init__(self, path: Path, max_rows: int = 1000, timeout: float = 2.0):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"Database missing: {self.path}. Run python scripts/setup_db.py")
        if max_rows < 1 or timeout <= 0:
            raise ValueError("max_rows and timeout must be positive")
        self.max_rows = max_rows
        self.timeout = timeout

    def connect(self):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True,
                                     timeout=self.timeout)
        connection.execute("PRAGMA query_only=ON")
        return connection

    def schema(self) -> str:
        # DDL includes foreign keys, which are essential for choosing valid joins.
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return "\n\n".join(row[0] for row in rows if row[0])

    def execute(self, sql: str) -> QueryResult:
        if len(sql) > 20_000:
            raise sqlite3.OperationalError("SQL exceeds the 20000 character limit")
        # An allowlist at SQLite's authorizer boundary handles comments and CTEs;
        # keyword matching alone cannot securely classify arbitrary SQL.
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                   sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

        def authorize(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in {
                "load_extension", "writefile", "readfile"
            }:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

        deadline = time.perf_counter() + self.timeout
        with closing(self.connect()) as connection:
            connection.set_authorizer(authorize)
            connection.set_progress_handler(lambda: int(time.perf_counter() > deadline), 1000)
            cursor = connection.execute(sql)
            if cursor.description is None:
                raise sqlite3.OperationalError("A SELECT result is required")
            rows = cursor.fetchmany(self.max_rows + 1)
            if len(rows) > self.max_rows:
                raise sqlite3.OperationalError(
                    f"Result exceeds {self.max_rows} rows; aggregate or use an appropriate LIMIT"
                )
            return {"columns": [item[0] for item in cursor.description],
                    "rows": [list(row) for row in rows]}
