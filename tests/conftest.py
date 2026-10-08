"""Shared test helpers: location of the Island 2026 reference fixtures (P2.1).

The fixtures are the files of AutoTVD, AutoSTV and IPD_Challenge at their reference state,
fetched from the private repo ``mxngl/concho-fixtures`` by ``python scripts/fetch_fixtures.py``
(same layout as the original repos). They contain course and RSMeans-derived data and are
never committed; tests that need them are skipped when they are missing.

Fixture root: ``$CONCHO_FIXTURES_DIR`` if set, else ``.fixtures/`` in the repo root if it
exists. ``$AUTOTVD_DIR`` still overrides the AutoTVD checkout (backwards compatible with the
P1.3 equivalence test), ``$IPD_CHALLENGE_DIR`` the IPD_Challenge checkout (P1.7). With
``CONCHO_REQUIRE_FIXTURES=1`` (CI job ``reference``) a missing
fixture fails the test instead of skipping it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ENV_VAR = "CONCHO_FIXTURES_DIR"
REQUIRE_ENV_VAR = "CONCHO_REQUIRE_FIXTURES"
DEFAULT_FIXTURES_DIR = REPO_ROOT / ".fixtures"


def fixtures_root() -> Path | None:
    """Return the fixture root, or None if it does not exist."""
    value = os.environ.get(FIXTURES_ENV_VAR)
    root = Path(value).resolve() if value else DEFAULT_FIXTURES_DIR
    return root if root.is_dir() else None


def reference_repo(name: str, override_env: str | None = None) -> Path | None:
    """Return the checkout of reference repo ``name`` (e.g. ``"AutoTVD"``), or None.

    ``override_env`` names an env var that, when set, points directly at the checkout.
    Paths are absolute: tests run engines as subprocesses in temporary folders.
    """
    if override_env and os.environ.get(override_env):
        path = Path(os.environ[override_env]).resolve()
        return path if path.is_dir() else None
    root = fixtures_root()
    if root is None or not (root / name).is_dir():
        return None
    return root / name


def _require(name: str, override_env: str | None = None) -> Path:
    path = reference_repo(name, override_env)
    if path is None:
        hint = f"${override_env} or " if override_env else ""
        reason = (
            f"reference fixture {name} not found (set {hint}${FIXTURES_ENV_VAR}, "
            "or run python scripts/fetch_fixtures.py)"
        )
        if os.environ.get(REQUIRE_ENV_VAR):
            pytest.fail(reason)
        pytest.skip(reason)
    return path


@pytest.fixture(scope="session")
def autotvd_dir() -> Path:
    return _require("AutoTVD", override_env="AUTOTVD_DIR")


@pytest.fixture(scope="session")
def autostv_dir() -> Path:
    return _require("AutoSTV")


@pytest.fixture(scope="session")
def ipd_challenge_dir() -> Path:
    return _require("IPD_Challenge", override_env="IPD_CHALLENGE_DIR")
