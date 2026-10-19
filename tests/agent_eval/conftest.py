"""Fixtures of the eval tests: a database built from the INVENTED data-API test repo."""

from __future__ import annotations

import eval_helpers  # noqa: F401  (puts scripts/ and tests/data_api on sys.path)
import pytest


@pytest.fixture(scope="session")
def eval_conn(tmp_path_factory):
    pytest.importorskip("fastapi")
    import api_synthetic as syn

    from engines.api import schema
    from engines.api.ingest import ingest_repo

    repo = syn.make_repo(tmp_path_factory.mktemp("eval_data") / "team")
    conn = schema.connect(str(ingest_repo(repo)["db"]), readonly=True)
    yield conn
    conn.close()
