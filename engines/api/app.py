"""P5.4: the data API (FastAPI). One app = one tenant = one team repo database.

Auth: ``Authorization: Bearer <token>``; the token comes from the environment
(``CONCHO_API_TOKEN``) or the caller, never from the repo. The app refuses to start without
one. Every answer goes through :func:`engines.api.caps.enforce`.

Errors are JSON ``{"error": code, "hint": ...}``: 401 (token), 404 (no such snapshot, cluster,
match, or no STV / element data), 422 (bad parameter). ``too_many_results`` is HTTP 200: it is
an answer the agent is meant to read and narrow down, not a failure of the call.
"""

import hmac
import os
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import queries, schema, sqlrunner
from .caps import MAX_ROWS, ApiError, enforce, too_many
from .caps import count_rows as _rows
from .caps import estimate_tokens as _tokens

TOKEN_ENV = "CONCHO_API_TOKEN"
SQL_ENV = "CONCHO_API_ENABLE_SQL"


class SqlRequest(BaseModel):
    query: str


def create_app(db_path: str | Path, token: str | None = None, *,
               enable_sql: bool | None = None) -> FastAPI:
    """The API for the database at ``db_path``.

    ``token`` defaults to ``$CONCHO_API_TOKEN``; ``enable_sql`` to ``$CONCHO_API_ENABLE_SQL``
    being ``1``/``true``. Raises ``ValueError`` without a token.
    """
    token = token if token is not None else os.environ.get(TOKEN_ENV)
    if not token:
        raise ValueError(f"set ${TOKEN_ENV} (or pass token): the API does not run without a "
                         "bearer token")
    if enable_sql is None:
        enable_sql = os.environ.get(SQL_ENV, "").lower() in ("1", "true", "yes")
    db_path = str(db_path)
    if not Path(db_path).is_file():
        raise ValueError(f"database {db_path} not found: run 'concho-api ingest' first")
    team = _team(db_path)

    app = FastAPI(title="Concho data API", version=str(schema.SCHEMA_VERSION),
                  description=f"Small, computed query results for the project of {team}. "
                              "Every response names its snapshot.")

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()]
        return JSONResponse({"error": "bad_parameter",
                             "hint": "check the query parameters: " + ", ".join(fields)},
                            status_code=422)

    def auth(authorization: str | None = Header(default=None)) -> None:
        scheme, _, given = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
                given.strip().encode(), token.encode()):
            raise ApiError(401, "unauthorized", "send 'Authorization: Bearer <token>'")

    def db() -> Iterator[sqlite3.Connection]:
        conn = schema.connect(db_path, readonly=True)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(db)]
    guarded = [Depends(auth)]

    def answer(build: Callable[[], dict[str, Any]]) -> JSONResponse:
        return JSONResponse(enforce(build()))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/cost/summary", dependencies=guarded)
    def cost_summary(conn: Conn, snapshot: str | None = None):
        return answer(lambda: queries.cost_summary(
            conn, queries.resolve_snapshot(conn, snapshot)))

    @app.get("/cost", dependencies=guarded)
    def cost(conn: Conn, cluster: str | None = None, ac: str | None = None,
             snapshot: str | None = None):
        return answer(lambda: queries.cost(
            conn, queries.resolve_snapshot(conn, snapshot), cluster, ac))

    @app.get("/cost/what_if", dependencies=guarded)
    def cost_what_if(conn: Conn, ac: str, change_pct: float, snapshot: str | None = None):
        return answer(lambda: queries.cost_what_if(
            conn, queries.resolve_snapshot(conn, snapshot), ac, change_pct))

    @app.get("/carbon/summary", dependencies=guarded)
    def carbon_summary(conn: Conn, snapshot: str | None = None):
        return answer(lambda: queries.carbon_summary(
            conn, queries.resolve_snapshot(conn, snapshot)))

    @app.get("/carbon", dependencies=guarded)
    def carbon(conn: Conn, stv_assembly: str | None = None, material: str | None = None,
               snapshot: str | None = None):
        return answer(lambda: queries.carbon(
            conn, queries.resolve_snapshot(conn, snapshot), stv_assembly, material))

    @app.get("/carbon/what_if", dependencies=guarded)
    def carbon_what_if(conn: Conn, material_from: str, material_to: str,
                       ac: str | None = None, stv_assembly: str | None = None,
                       snapshot: str | None = None):
        # STV items are keyed by STV assembly, not by Uniformat code: `ac` is accepted as an
        # alias of `stv_assembly` (docs/data-api.md).
        return answer(lambda: queries.carbon_what_if(
            conn, queries.resolve_snapshot(conn, snapshot), material_from, material_to,
            stv_assembly or ac))

    @app.get("/quantities", dependencies=guarded)
    def quantities(conn: Conn, category: str | None = None, level: str | None = None,
                   ac: str | None = None, snapshot: str | None = None):
        return answer(lambda: queries.quantities(
            conn, queries.resolve_snapshot(conn, snapshot), category, level, ac))

    @app.get("/elements/count", dependencies=guarded)
    def elements_count(conn: Conn, category: str | None = None, level: str | None = None,
                       ac: str | None = None, discipline: str | None = None,
                       snapshot: str | None = None):
        return answer(lambda: queries.elements_count(
            conn, queries.resolve_snapshot(conn, snapshot), category, level, ac, discipline))

    @app.get("/quality", dependencies=guarded)
    def quality(conn: Conn, snapshot: str | None = None):
        return answer(lambda: queries.quality(conn, queries.resolve_snapshot(conn, snapshot)))

    @app.get("/snapshots", dependencies=guarded)
    def snapshots(conn: Conn, limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = 20):
        return answer(lambda: queries.list_snapshots(conn, limit))

    @app.get("/compare", dependencies=guarded)
    def compare(conn: Conn, a: str, b: str):
        return answer(lambda: queries.compare(
            conn, queries.resolve_snapshot(conn, a), queries.resolve_snapshot(conn, b)))

    if enable_sql:
        @app.post("/sql", dependencies=guarded)
        def sql(conn: Conn, request: SqlRequest):
            def build() -> dict[str, Any]:
                result = sqlrunner.run_select(db_path, request.query)
                body = {"snapshot": queries.snap_ref(queries.resolve_snapshot(conn, None)),
                        "labels": ["sql: free query; the tables hold all snapshots, filter on "
                                   "snapshot_id"],
                        "columns": result["columns"], "rows": result["rows"]}
                if result["truncated"]:
                    return too_many(body, _rows(body), _tokens(body))
                return body
            return answer(build)

    return app


def _team(db_path: str) -> str:
    conn = schema.connect(db_path, readonly=True)
    try:
        row = conn.execute("SELECT team_name, project_name FROM snapshots "
                           "ORDER BY timestamp DESC LIMIT 1").fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"{db_path} is not a concho.db: {exc}") from exc
    finally:
        conn.close()
    return (row["team_name"] or row["project_name"] or "this team") if row else "this team"
