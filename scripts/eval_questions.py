"""Question generator of the Concho eval (roadmap P6.8).

``tests/agent_eval/questions.yaml`` holds question *templates* and *recipes*, never numbers.
This module resolves them against the results of one snapshot:

- ``entities`` (names such as the biggest cluster, a level, a material) come from SQL on the
  data API's SQLite database and fill the ``{placeholders}`` of the question texts;
- ``facts`` (the expected numbers) are SQL on the same database, or, for the what-if and compare
  scenarios, the data API's own query functions (``engines.api.queries``), so the expected
  value is computed from the fixture results by the same code the agent's tools run on;
- a question whose entities or facts cannot be resolved (no STV result in the snapshot, no
  second snapshot, a level that does not exist ...) is ``unavailable`` with the reason and is
  not scored; ``tier2`` questions (schedule) are ``skipped``.

Nothing course- or RSMeans-derived is stored in the repo: the database is built locally from
the team repo (``concho-api ingest``) and the resolved questions are written to a git-ignored
file for review (``run_eval.py --generate-only``).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engines.api import queries
from engines.api.caps import ApiError
from engines.api.schema import connect

REPO_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_FILE = REPO_ROOT / "tests" / "agent_eval" / "questions.yaml"
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
LANGUAGES = {"en", "de", "es", "pl"}
CATEGORIES = {"COST", "CARBON", "QUANTITY", "SCHEDULE", "GENERAL", "OTHER"}


class QuestionFileError(Exception):
    """The questions file is malformed (a bug in the file, not in the data)."""


class Unavailable(Exception):
    """A question cannot be built from this snapshot (reason in the message)."""


def load_questions(path: Path = QUESTIONS_FILE) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate(data)
    return data


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def validate(data: Mapping[str, Any]) -> None:
    """Structural checks of the file (raises :class:`QuestionFileError`)."""
    entities, facts = data.get("entities") or {}, data.get("facts") or {}
    questions = data.get("questions") or []
    ids = [q.get("id") for q in questions]
    if len(set(ids)) != len(ids) or not all(ids):
        raise QuestionFileError("question ids must be present and unique")
    for name, ent in entities.items():
        if "sql" not in ent:
            raise QuestionFileError(f"entity {name}: 'sql' is required")
        unknown = (placeholders_in_sql(ent["sql"]) - {"sid"}) - set(entities)
        if unknown:
            raise QuestionFileError(f"entity {name}: unknown parameter(s) {sorted(unknown)}")
    for name, fact in facts.items():
        if ("sql" in fact) == ("api" in fact):
            raise QuestionFileError(f"fact {name}: exactly one of 'sql' or 'api'")
        if fact.get("kind", "amount") not in ("amount", "count"):
            raise QuestionFileError(f"fact {name}: kind must be amount or count")
        text = fact["sql"] if "sql" in fact else repr(fact["api"])
        unknown = (placeholders_in_sql(text) - {"sid"}) - set(entities)
        unknown |= {p for p in placeholders(text) if p not in entities}
        if unknown:
            raise QuestionFileError(f"fact {name}: unknown entity {sorted(unknown)}")
        if "api" in fact and fact["api"].get("fn") not in API_FUNCTIONS:
            raise QuestionFileError(f"fact {name}: api.fn must be one of {sorted(API_FUNCTIONS)}")
    for q in questions:
        qid = q["id"]
        if q.get("lang") not in LANGUAGES:
            raise QuestionFileError(f"{qid}: lang must be one of {sorted(LANGUAGES)}")
        if not q.get("text") or not q.get("group"):
            raise QuestionFileError(f"{qid}: text and group are required")
        if q.get("category") not in CATEGORIES:
            raise QuestionFileError(f"{qid}: category must be one of {sorted(CATEGORIES)}")
        if q.get("tools") not in (None, "none", "some"):
            raise QuestionFileError(f"{qid}: tools must be none or some")
        refs = placeholders(q["text"]) | {t for s in q.get("expect_text", [])
                                          for t in placeholders(s)}
        if refs - set(entities):
            raise QuestionFileError(f"{qid}: unknown placeholder(s) {sorted(refs - set(entities))}")
        for exp in q.get("expect", []):
            if exp not in facts:
                raise QuestionFileError(f"{qid}: unknown fact {exp!r}")
        if q.get("tier", 1) == 1 and not q.get("expect") and not q.get("expect_text") \
                and q.get("tools") != "none":
            raise QuestionFileError(f"{qid}: a tier-1 question needs an expectation")
        if q.get("after") and q["after"] not in ids:
            raise QuestionFileError(f"{qid}: 'after' names an unknown question")


def placeholders_in_sql(sql: str) -> set[str]:
    return set(re.findall(r"(?<![:\w]):([a-z][a-z0-9_]*)", sql))


# --------------------------------------------------------------------------- resolving


def _pick(data: Any, path: str) -> Any:
    for part in path.split("."):
        data = data[int(part)] if isinstance(data, list) else data[part]
    return data


API_FUNCTIONS = {"cost_what_if", "carbon_what_if", "compare"}


@dataclass
class Resolver:
    """Resolves entities and facts against one snapshot of ``conn``."""

    conn: sqlite3.Connection
    snapshot_id: str
    data: Mapping[str, Any]
    _entities: dict[str, Any] = field(default_factory=dict)
    _facts: dict[str, Any] = field(default_factory=dict)

    # -- SQL / API plumbing
    def _params(self) -> dict[str, Any]:
        return {"sid": self.snapshot_id, **self._entities}

    def _run_sql(self, sql: str, row: int = 0) -> Any:
        try:
            rows = self.conn.execute(sql, self._params()).fetchall()
        except sqlite3.Error as exc:
            raise QuestionFileError(f"SQL failed: {exc}: {sql}") from exc
        if len(rows) <= row or rows[row][0] is None:
            raise Unavailable("no data")
        return rows[row][0]

    def _snapshot(self, snapshot_id: str) -> sqlite3.Row:
        return queries.resolve_snapshot(self.conn, snapshot_id)

    def _previous_snapshot_id(self) -> str:
        cur = self.conn.execute("SELECT timestamp FROM snapshots WHERE snapshot_id=?",
                                (self.snapshot_id,)).fetchone()
        prev = self.conn.execute(
            "SELECT snapshot_id FROM snapshots WHERE timestamp < ? "
            "ORDER BY timestamp DESC LIMIT 1", (cur[0],)).fetchone() if cur else None
        if prev is None:
            raise Unavailable("needs a second, older snapshot")
        return prev[0]

    def _call_api(self, spec: Mapping[str, Any]) -> Any:
        fn, args = spec["fn"], {
            k: (self.fill(v) if isinstance(v, str) else v)
            for k, v in (spec.get("args") or {}).items()}
        snap = self._snapshot(self.snapshot_id)
        try:
            if fn == "cost_what_if":
                body = queries.cost_what_if(self.conn, snap, str(args["ac"]),
                                            float(args["change_pct"]))
            elif fn == "carbon_what_if":
                body = queries.carbon_what_if(self.conn, snap, args["material_from"],
                                              args["material_to"])
            else:
                body = queries.compare(self.conn, self._snapshot(self._previous_snapshot_id()),
                                       snap)
        except ApiError as exc:
            raise Unavailable(f"{fn}: {exc.code}") from exc
        try:
            value = _pick(body, spec["pick"])
        except (KeyError, IndexError, TypeError) as exc:
            raise Unavailable(f"{fn}: no {spec['pick']}") from exc
        if value is None:
            raise Unavailable(f"{fn}: {spec['pick']} is empty")
        return value

    # -- public
    def fill(self, text: str) -> str:
        return _PLACEHOLDER.sub(lambda m: str(self.entity(m.group(1))), text)

    def entity(self, name: str) -> Any:
        if name not in self._entities:
            spec = self.data["entities"][name]
            try:
                for ref in placeholders_in_sql(spec["sql"]) - {"sid"}:
                    self.entity(ref)
                self._entities[name] = self._run_sql(spec["sql"], int(spec.get("row", 0)))
            except Unavailable as exc:
                raise Unavailable(f"entity {name}: {exc}") from exc
        return self._entities[name]

    def fact(self, name: str) -> float:
        if name not in self._facts:
            spec = self.data["facts"][name]
            try:
                for ref in placeholders_in_sql(spec.get("sql", "")) - {"sid"}:
                    self.entity(ref)
                if "sql" in spec:
                    value = self._run_sql(spec["sql"])
                else:
                    value = self._call_api(spec["api"])
            except Unavailable as exc:
                raise Unavailable(f"fact {name}: {exc}") from exc
            value = float(value)
            if value == 0:  # "0" cannot be told from an answer that just names a zero somewhere
                raise Unavailable(f"fact {name}: expected value is 0")
            self._facts[name] = abs(value) if spec.get("abs") else value
        return self._facts[name]


@dataclass
class ResolvedQuestion:
    id: str
    group: str
    lang: str
    category: str
    status: str                       # ready | unavailable | skipped
    reason: str = ""
    text: str = ""
    conv: str = ""
    after: str | None = None
    tier: int = 1
    tools: str | None = None
    expect_numbers: list[dict[str, Any]] = field(default_factory=list)
    expect_text: list[str] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)

    def asdict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def resolve_questions(data: Mapping[str, Any], conn: sqlite3.Connection,
                      snapshot_id: str | None = None) -> list[ResolvedQuestion]:
    """All questions of ``data`` resolved against ``snapshot_id`` (default: the latest)."""
    snap = queries.resolve_snapshot(conn, snapshot_id)
    resolver = Resolver(conn, snap["snapshot_id"], data)
    by_id = {q["id"]: q for q in data["questions"]}
    out: list[ResolvedQuestion] = []
    for q in data["questions"]:
        rq = ResolvedQuestion(
            id=q["id"], group=q["group"], lang=q["lang"], category=q["category"],
            status="ready", text=q["text"], after=q.get("after"), tier=int(q.get("tier", 1)),
            tools=q.get("tools"),
            conv=_conversation(q, by_id))
        if rq.tier != 1:
            rq.status, rq.reason = "skipped", f"tier {rq.tier}: not implemented in this version"
            out.append(rq)
            continue
        try:
            rq.text = resolver.fill(q["text"])
            rq.ignore = [str(resolver.entity(n)) for n in sorted(placeholders(q["text"]))]
            rq.expect_text = [resolver.fill(t) for t in q.get("expect_text", [])]
            for name in q.get("expect", []):
                spec = data["facts"][name]
                rq.expect_numbers.append({"fact": name, "value": resolver.fact(name),
                                          "kind": spec.get("kind", "amount")})
            if rq.expect_numbers and rq.tools is None:
                rq.tools = "some"  # a number must come from a tool, not from the chat history
        except Unavailable as exc:
            rq.status, rq.reason = "unavailable", str(exc)
        out.append(rq)
    # a follow-up needs the question before it
    state = {r.id: r for r in out}
    for r in out:
        if r.status == "ready" and r.after and state[r.after].status != "ready":
            r.status, r.reason = "unavailable", f"depends on {r.after} ({state[r.after].status})"
    return out


def _conversation(q: Mapping[str, Any], by_id: Mapping[str, Any]) -> str:
    """Questions linked by ``after`` share one conversation (user + channel, so the memory
    sees the earlier messages); every other question has a conversation of its own."""
    root = q
    while root.get("after"):
        root = by_id[root["after"]]
    return root["id"]


def open_database(db: Path) -> sqlite3.Connection:
    return connect(str(db), readonly=True)
