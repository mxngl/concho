"""Shared loaders for the offline agent tests (workflow JSON, prompts, .env.example)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT = REPO_ROOT / "agent"
WORKFLOWS = AGENT / "workflows"
PROMPTS = AGENT / "prompts"
ENV_EXAMPLE = AGENT / ".env.example"


def load(name: str) -> dict[str, Any]:
    return json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))


def strings(node: Any):
    """Every string value (not key) in a JSON structure."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for x in node:
            yield from strings(x)
    elif isinstance(node, dict):
        for v in node.values():
            yield from strings(v)


def env_vars_in_example() -> set[str]:
    out = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z][A-Z0-9_]*)=", line)
        if m:
            out.add(m.group(1))
    return out


def by_name(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["name"]: n for n in workflow["nodes"]}


def edges(workflow: dict[str, Any]):
    """``(source, target, connection type, output index)`` for every connection."""
    for src, kinds in workflow["connections"].items():
        for kind, outputs in kinds.items():
            for out, targets in enumerate(outputs):
                for t in targets:
                    yield src, t["node"], kind, out
