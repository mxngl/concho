"""Shared loaders for the offline eval tests (scripts live in ``scripts/``, data is invented)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for extra in (REPO_ROOT / "scripts", REPO_ROOT / "tests" / "data_api"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
