"""Fixtures of the agent tests: the real data API's OpenAPI schema (invented data)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

DATA_API_TESTS = Path(__file__).resolve().parents[1] / "data_api"


@pytest.fixture(scope="session")
def api_routes(tmp_path_factory):
    """``{path: {"all": {query params}, "required": {...}}}`` of every GET route of the app."""
    pytest.importorskip("fastapi")
    sys.path.insert(0, str(DATA_API_TESTS))
    try:
        import api_synthetic as syn
    finally:
        sys.path.remove(str(DATA_API_TESTS))
    from engines.api.app import create_app
    from engines.api.ingest import ingest_repo

    repo = syn.make_repo(tmp_path_factory.mktemp("agent_api") / "team")
    app = create_app(ingest_repo(repo)["db"], "agent-test-token", enable_sql=True)
    routes: dict[str, dict[str, set[str]]] = {}
    for path, methods in app.openapi()["paths"].items():
        op = methods.get("get") or methods.get("post")
        params = [p for p in op.get("parameters", []) if p["in"] == "query"]
        routes[path] = {"all": {p["name"] for p in params},
                        "required": {p["name"] for p in params if p.get("required")}}
    return routes
