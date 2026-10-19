"""Paths for the eval tests: the scripts (build_eval_set, run_eval) and the invented data of
the data-API tests (no Island data here)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "scripts", ROOT / "tests" / "data_api"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
