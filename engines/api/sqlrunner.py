"""``POST /sql`` (P5.4, optional, behind a flag): one read-only SELECT with a row cap.

Defence in depth, because the caller is an LLM: the connection is opened read-only
(``mode=ro`` + ``PRAGMA query_only``), the statement must be a single SELECT/WITH, and an
authorizer allows nothing but reading (no PRAGMA, ATTACH, writes, extension loading). A
progress handler aborts queries that run longer than :data:`MAX_SECONDS`.
"""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from .caps import MAX_ROWS, ApiError

MAX_SECONDS = 2.0
_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
            sqlite3.SQLITE_RECURSIVE}


def _authorizer(action, arg1, arg2, dbname, source):  # noqa: ARG001
    return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY


def run_select(db_path: str, sql: str) -> dict[str, Any]:
    """Run ``sql``; return ``{columns, rows, row_count, truncated}`` with at most MAX_ROWS rows
    (one more is fetched to know whether there were more: then the caller answers
    ``too_many_results``)."""
    if not _START.match(sql) or ";" in sql.strip().rstrip(";"):
        raise ApiError(400, "not_a_select", "send one SELECT statement (no ';', no other verbs)")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.set_authorizer(_authorizer)
        deadline = time.monotonic() + MAX_SECONDS
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        try:
            cur = conn.execute(sql)
            fetched = cur.fetchmany(MAX_ROWS + 1)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc):
                raise ApiError(400, "query_too_slow",
                               f"the query ran longer than {MAX_SECONDS:.0f} s: filter it") from exc
            raise ApiError(400, "sql_error", str(exc)) from exc
        except sqlite3.DatabaseError as exc:
            raise ApiError(400, "sql_error", str(exc)) from exc
        columns = [d[0] for d in cur.description or []]
        return {"columns": columns, "truncated": len(fetched) > MAX_ROWS,
                "rows": [list(r) for r in fetched[:MAX_ROWS + 1]]}
    finally:
        conn.close()
