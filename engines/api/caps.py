"""Hard response caps (P5.4): at most :data:`MAX_ROWS` rows and about :data:`MAX_TOKENS` tokens
per response. Over the cap the API returns ``{"error": "too_many_results", "hint": ...}``
instead of the data, so the agent narrows the question instead of flooding its context.

A "row" is an object (or list) inside any list of the response; the cap counts all of them.
Tokens are estimated from the JSON text with a deliberately pessimistic
:data:`CHARS_PER_TOKEN` (digits and short keys tokenize worse than prose), so the real token
count stays below the cap.
"""

from __future__ import annotations

import json
import math
from typing import Any

MAX_ROWS = 50
MAX_TOKENS = 8000
CHARS_PER_TOKEN = 3.0
HINT = "filter by level or category"


class ApiError(Exception):
    """An error answer: ``{"error": code, "hint": ..., **extra}`` with an HTTP status."""

    def __init__(self, status: int, code: str, hint: str, **extra: Any) -> None:
        super().__init__(f"{code}: {hint}")
        self.status, self.code, self.hint, self.extra = status, code, hint, extra

    def body(self) -> dict[str, Any]:
        return {"error": self.code, "hint": self.hint, **self.extra}


def count_rows(value: Any) -> int:
    """Objects and lists inside lists, anywhere in ``value``."""
    if isinstance(value, dict):
        return sum(count_rows(v) for v in value.values())
    if isinstance(value, list):
        return sum(1 + count_rows(v) if isinstance(v, (dict, list)) else 0 for v in value)
    return 0


def estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"),
                                                           ensure_ascii=False)
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def too_many(body: dict, rows: int, tokens: int) -> dict:
    """The over-the-cap answer; keeps the snapshot so the answer still names its source."""
    out: dict[str, Any] = {"error": "too_many_results", "hint": HINT}
    if "snapshot" in body:
        out["snapshot"] = body["snapshot"]
    out.update(at_least_rows=rows, max_rows=MAX_ROWS, estimated_tokens=tokens,
               max_tokens=MAX_TOKENS)
    return out


def enforce(body: dict) -> dict:
    """``body`` itself when within the caps, else the ``too_many_results`` answer."""
    rows, tokens = count_rows(body), estimate_tokens(body)
    if rows > MAX_ROWS or tokens > MAX_TOKENS:
        return too_many(body, rows, tokens)
    return body
