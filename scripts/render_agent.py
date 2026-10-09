"""Render the Concho agent for one team (roadmap P6.3, P6.7): prompts + workflows to a build dir.

The committed workflows (``agent/workflows/*.json``) and prompts (``agent/prompts/*.md``) are
project-neutral. This script fills them for one team, at import time, and writes the result to
a build folder that ``scripts/import_workflows.sh`` imports into n8n:

- ``@@PROMPT:<name>@@`` in a workflow string is replaced by ``agent/prompts/<name>.md``;
  ``@@INCLUDE:<name>@@`` inside a prompt pulls in another prompt file (the shared rules).
- ``{{PROJECT_NAME}}``, ``{{LOCATION}}``, ``{{COMPLETION_DATE}}``, ``{{TEAM}}`` in a prompt come
  from the env (``CONCHO_PROJECT_NAME``, ``CONCHO_LOCATION``, ``CONCHO_COMPLETION_DATE``,
  ``CONCHO_TEAM``) or else from the ``project`` section of the team's ``project_config.json``.
- ``REPLACE_WITH_RANDOM_WEBHOOK_PATH`` is replaced by ``$CONCHO_WEBHOOK_PATH`` (a long random
  string, kept in ``.env``).

Models are not rendered: the workflow reads ``$CONCHO_MODEL_ROUTER`` / ``_SUBAGENT`` / ``_TTS``
at run time (default :data:`DEFAULT_MODEL`), so ``.env`` is the one place to change them.

    python scripts/render_agent.py --config path/to/project_config.json [--out agent/build]
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_env import load_env  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agent"
PROMPTS_DIR = AGENT_DIR / "prompts"
WORKFLOWS_DIR = AGENT_DIR / "workflows"
DEFAULT_OUT = AGENT_DIR / "build"

PLACEHOLDERS = ("PROJECT_NAME", "LOCATION", "COMPLETION_DATE", "TEAM")
# placeholder -> (env var, field of the "project" section of project_config.json)
SOURCES = {
    "PROJECT_NAME": ("CONCHO_PROJECT_NAME", "name"),
    "LOCATION": ("CONCHO_LOCATION", "location"),
    "COMPLETION_DATE": ("CONCHO_COMPLETION_DATE", "completion_date"),
    "TEAM": ("CONCHO_TEAM", "team_name"),
}
WEBHOOK_PLACEHOLDER = "REPLACE_WITH_RANDOM_WEBHOOK_PATH"
WEBHOOK_ENV = "CONCHO_WEBHOOK_PATH"
MIN_WEBHOOK_PATH = 24

DEFAULT_MODEL = "gpt-4o-mini"
# gpt-4o-mini itself cannot speak: the text-to-speech model of the same family is the default
# (reserved, no node uses it yet).
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
MODEL_ENV = {
    "router": "CONCHO_MODEL_ROUTER",
    "subagent": "CONCHO_MODEL_SUBAGENT",
    "tts": "CONCHO_MODEL_TTS",
}

_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
_PROMPT_MARKER = re.compile(r"@@PROMPT:([a-z_]+)@@")
_INCLUDE_MARKER = re.compile(r"@@INCLUDE:([a-z_]+)@@")
_MAX_VALUE = 200


class RenderError(Exception):
    """Something the operator has to fix (missing value, bad value, unknown prompt)."""


def model_settings(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Router, subagent and TTS model as the workflow will resolve them (env, else default)."""
    env = os.environ if env is None else env
    defaults = {"router": DEFAULT_MODEL, "subagent": DEFAULT_MODEL, "tts": DEFAULT_TTS_MODEL}
    return {role: (env.get(name) or "").strip() or defaults[role]
            for role, name in MODEL_ENV.items()}


def prompt_names(prompts_dir: Path = PROMPTS_DIR) -> list[str]:
    return sorted(p.stem for p in prompts_dir.glob("*.md"))


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR, _seen: tuple[str, ...] = ()) -> str:
    """The prompt text with ``@@INCLUDE:x@@`` resolved; placeholders are still in it."""
    path = prompts_dir / f"{name}.md"
    if name in _seen:
        raise RenderError(f"prompt include loop: {' -> '.join((*_seen, name))}")
    if not path.is_file():
        raise RenderError(f"prompt '{name}' not found ({path})")
    text = path.read_text(encoding="utf-8").strip()
    return _INCLUDE_MARKER.sub(
        lambda m: load_prompt(m.group(1), prompts_dir, (*_seen, name)), text)


def check_value(placeholder: str, value: str) -> str:
    value = value.strip()
    if not value:
        raise RenderError(f"{placeholder} is empty")
    if len(value) > _MAX_VALUE or "\n" in value or "{{" in value or "}}" in value or "@@" in value:
        raise RenderError(f"{placeholder}: a single line of at most {_MAX_VALUE} characters "
                          "without '{{', '}}' or '@@' is expected")
    return value


def resolve_values(config_path: Path | None = None,
                   env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Placeholder values: env first, else the ``project`` section of ``config_path``."""
    env = os.environ if env is None else env
    project: dict[str, Any] = {}
    if config_path is not None:
        try:
            data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RenderError(f"cannot read config {config_path}: {exc}") from exc
        project = data.get("project") or {}
    values, missing = {}, []
    for placeholder, (env_name, field) in SOURCES.items():
        raw = (env.get(env_name) or "").strip() or str(project.get(field) or "").strip()
        if not raw:
            missing.append(f"{placeholder} (${env_name} or project.{field} in the config)")
        else:
            values[placeholder] = check_value(placeholder, raw)
    if missing:
        raise RenderError("missing values: " + "; ".join(missing))
    return values


def render_prompt(name: str, values: Mapping[str, str], prompts_dir: Path = PROMPTS_DIR) -> str:
    text = load_prompt(name, prompts_dir)
    unknown = sorted(set(_PLACEHOLDER.findall(text)) - set(PLACEHOLDERS))
    if unknown:
        raise RenderError(f"prompt '{name}' uses unknown placeholders: {', '.join(unknown)}")
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


def check_webhook_path(path: str) -> str:
    path = path.strip()
    if len(path) < MIN_WEBHOOK_PATH or not re.fullmatch(r"[A-Za-z0-9_-]+", path):
        raise RenderError(f"${WEBHOOK_ENV} must be a random string of at least "
                          f"{MIN_WEBHOOK_PATH} letters, digits, '-' or '_' (it is the secret part "
                          "of the webhook URL)")
    return path


def _walk(node: Any, fn) -> Any:
    if isinstance(node, str):
        return fn(node)
    if isinstance(node, list):
        return [_walk(x, fn) for x in node]
    if isinstance(node, dict):
        return {k: _walk(v, fn) for k, v in node.items()}
    return node


def render_workflow(workflow: dict[str, Any], values: Mapping[str, str],
                    webhook_path: str | None = None,
                    prompts_dir: Path = PROMPTS_DIR) -> dict[str, Any]:
    """A copy of ``workflow`` with prompt markers expanded and the webhook path set."""
    cache: dict[str, str] = {}

    def prompt(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in cache:
            cache[name] = render_prompt(name, values, prompts_dir)
        return cache[name]

    def fill(s: str) -> str:
        s = _PROMPT_MARKER.sub(prompt, s)
        if WEBHOOK_PLACEHOLDER in s:
            if webhook_path is None:
                raise RenderError(f"set ${WEBHOOK_ENV} (the webhook path) to render this workflow")
            s = s.replace(WEBHOOK_PLACEHOLDER, check_webhook_path(webhook_path))
        return s

    return _walk(copy.deepcopy(workflow), fill)


def render_all(out_dir: Path, config_path: Path | None = None,
               env: Mapping[str, str] | None = None, workflows_dir: Path = WORKFLOWS_DIR,
               prompts_dir: Path = PROMPTS_DIR) -> list[Path]:
    """Render every ``*.json`` directly in ``workflows_dir`` (not ``legacy/``) into ``out_dir``."""
    env = os.environ if env is None else env
    values = resolve_values(config_path, env)
    webhook = env.get(WEBHOOK_ENV)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for path in sorted(workflows_dir.glob("*.json")):
        workflow = json.loads(path.read_text(encoding="utf-8"))
        rendered = render_workflow(workflow, values, webhook, prompts_dir)
        target = out_dir / path.name
        target.write_text(json.dumps(rendered, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, metavar="FILE",
                        help="the team's project_config.json (values may also come from env)")
    parser.add_argument("--env-file", type=Path, metavar="FILE",
                        help="read CONCHO_* values from this .env file (the process "
                             "environment wins)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, metavar="DIR",
                        help=f"output folder (default {DEFAULT_OUT.relative_to(REPO_ROOT)})")
    args = parser.parse_args(argv)
    try:
        env = load_env(args.env_file) if args.env_file else os.environ
        written = render_all(args.out, args.config, env)
    except (RenderError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(f"wrote {path}")
    models = model_settings(env)
    print("models (from env, default {}): router={router} subagent={subagent} tts={tts}"
          .format(DEFAULT_MODEL, **models))
    return 0


if __name__ == "__main__":
    sys.exit(main())
