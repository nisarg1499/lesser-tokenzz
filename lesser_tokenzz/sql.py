"""Read-only, time-bounded SQLite queries with explicit preview truncation."""

from pathlib import Path
import sqlite3
import time


def _authorize(action, first, second, database, source):
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }
    if action == sqlite3.SQLITE_FUNCTION and str(second).lower() in {
        "load_extension",
        "readfile",
        "writefile",
    }:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def run_sql(database: Path, sql: str, max_rows: int = 100) -> dict:
    """Return a bounded preview, never silently treat it as the whole result."""
    if type(max_rows) is not int or not 1 <= max_rows <= 1000:
        raise ValueError("max_rows must be between 1 and 1000")
    started = time.monotonic()
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.set_authorizer(_authorize)
        conn.set_progress_handler(lambda: int(time.monotonic() - started > 10), 1000)
        cursor = conn.execute(sql)
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchmany(max_rows + 1)
    if any(isinstance(value, bytes) for row in rows for value in row):
        raise ValueError("Binary output is unsupported; select other columns")
    clipped = []
    output = []
    for row_index, row in enumerate(rows[:max_rows]):
        cells = []
        for column_index, value in enumerate(row):
            if isinstance(value, str) and len(value) > 2000:
                clipped.append([row_index, column_index])
                value = value[:2000]
            cells.append(value)
        output.append(cells)
    return {
        "columns": columns,
        "rows": output,
        "truncated": len(rows) > max_rows,
        "clipped_cells": clipped,
        "elapsed_s": time.monotonic() - started,
    }
