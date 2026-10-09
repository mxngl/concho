"""Tiny ``.env`` reader shared by the agent scripts (P6.6): ``render_agent.py``,
``agent_credentials.py`` and the eval. No shell expansion, so a value may contain spaces or ``$``.

Format (the subset ``docker compose`` reads): ``KEY=value``, optional single or double quotes
around the value, ``#`` starts a comment line, and `` #`` starts an inline comment after an
unquoted value. The process environment wins over the file.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        m = _LINE.match(raw)
        if not m:
            continue
        key, value = m.groups()
        quoted = re.match(r"""^(['"])(.*?)\1(?:\s+#.*)?$""", value)
        if quoted:
            value = quoted.group(2)
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        values[key] = value
    return values


def load_env(env_file: Path | None = None,
             base: Mapping[str, str] | None = None) -> dict[str, str]:
    """``env_file`` values overlaid by the process environment (``base``, default os.environ)."""
    values: dict[str, str] = {}
    if env_file is not None:
        values.update(parse_env_text(Path(env_file).read_text(encoding="utf-8")))
    values.update({k: v for k, v in (os.environ if base is None else base).items() if v != ""})
    return values
