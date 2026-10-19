"""Question generator of the Concho evaluation (roadmap P6.8): templates + data -> cases.

``tests/agent_eval/questions.yaml`` holds question *templates*: the wording per language, which
data they point at (``{level_a}``, ``{category_a}``, ...) and which numbers the answer must
contain, as references (``ref: cost.grand_total``), never as typed values. This module fills
the slots from a data-API database and computes every expected number with the **same query
functions the API serves** (``engines.api.queries``), so the expected values are generated from
the fixture results and nothing from the data is copied into the repo.

    python scripts/eval_cases.py --repo path/to/team-repo            # print the cases
    python scripts/eval_cases.py --db concho.db --out cases.json     # write them (git-ignored)

A question whose slots or numbers cannot be resolved (e.g. no STV data in the snapshot) is
dropped and listed with the reason; ``scripts/run_eval.py`` does the same on the fly.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from itertools import permutations
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engines.api import queries  # noqa: E402
from engines.api.caps import ApiError  # noqa: E402

QUESTIONS_PATH = REPO_ROOT / "tests" / "agent_eval" / "questions.yaml"
LANGUAGES = ("en", "de", "es", "pl")
CATEGORIES = ("COST", "CARBON", "QUANTITY", "SCHEDULE", "GENERAL", "OTHER")
SLOT_RE = re.compile(r"\{([a-z_0-9]+)\}")


class CaseError(Exception):
    """A question template cannot be resolved against the data (reason in the message)."""


@dataclass
class Ctx:
    conn: sqlite3.Connection
    snap: sqlite3.Row


# --- references: expected numbers from the API's own query functions -------------------------

REFS: dict[str, tuple[Callable[..., Any], float, float]] = {}  # name -> (fn, rel_tol, abs_tol)


def ref(name: str, rel: float = 0.005, abs_: float = 0.0):
    def register(fn):
        REFS[name] = (fn, rel, abs_)
        return fn
    return register


def _qty(ctx: Ctx, key: str, category=None, level=None, ac=None):
    return queries.quantities(ctx.conn, ctx.snap, category or None, level or None,
                              ac or None)["totals"][key]


@ref("cost.grand_total")
def _(ctx):
    return queries.cost_summary(ctx.conn, ctx.snap)["grand_total"]


@ref("cost.target")
def _(ctx):
    return queries.cost_summary(ctx.conn, ctx.snap)["target"]


@ref("cost.delta")
def _(ctx):
    return queries.cost_summary(ctx.conn, ctx.snap)["delta"]


@ref("cost.per_sf", rel=0.005, abs_=0.01)
def _(ctx):
    return queries.cost_summary(ctx.conn, ctx.snap)["cost_per_sf"]


def _cluster_row(ctx, cluster):
    for row in queries.cost_summary(ctx.conn, ctx.snap)["rows"]:
        if row["cluster"].lower() == cluster.lower():
            return row
    raise CaseError(f"cluster {cluster!r} not in the cost summary")


@ref("cost.cluster_estimate")
def _(ctx, cluster):
    return _cluster_row(ctx, cluster)["estimate"]


@ref("cost.cluster_target")
def _(ctx, cluster):
    return _cluster_row(ctx, cluster)["target"]


@ref("cost.whatif_total_after")
def _(ctx, ac, pct):
    return queries.cost_what_if(ctx.conn, ctx.snap, ac, float(pct))["grand_total_after"]


@ref("cost.whatif_change")
def _(ctx, ac, pct):
    return queries.cost_what_if(ctx.conn, ctx.snap, ac, float(pct))["change"]["total"]


@ref("carbon.metric")
def _(ctx, metric, field):
    return queries.carbon_summary(ctx.conn, ctx.snap)["metrics"][metric][field]


@ref("carbon.assembly")
def _(ctx, stv_assembly):
    for row in queries.carbon_summary(ctx.conn, ctx.snap)["rows"]:
        if row["stv_assembly"].lower() == stv_assembly.lower():
            return row["embodied_kgco2e"]
    raise CaseError(f"STV assembly {stv_assembly!r} not in the carbon summary")


@ref("carbon.whatif_change")
def _(ctx, material_from, material_to):
    return queries.carbon_what_if(ctx.conn, ctx.snap, material_from, material_to)[
        "change_kgco2e"]


@ref("carbon.whatif_life_after")
def _(ctx, material_from, material_to):
    return queries.carbon_what_if(ctx.conn, ctx.snap, material_from, material_to)[
        "life_cycle_after"]


@ref("qty.elements", rel=0.0)
def _(ctx, category=None, level=None, ac=None):
    return _qty(ctx, "elements", category, level, ac)


@ref("qty.area_sf", abs_=0.5)
def _(ctx, category=None, level=None, ac=None):
    return _qty(ctx, "area_sf", category, level, ac)


@ref("qty.length_lf", abs_=0.5)
def _(ctx, category=None, level=None, ac=None):
    return _qty(ctx, "length_lf", category, level, ac)


@ref("qty.volume_cf", abs_=0.5)
def _(ctx, category=None, level=None, ac=None):
    return _qty(ctx, "volume_cf", category, level, ac)


@ref("count.elements", rel=0.0)
def _(ctx, category=None, level=None):
    return queries.elements_count(ctx.conn, ctx.snap, category or None, level or None)["count"]


@ref("snapshots.total", rel=0.0)
def _(ctx):
    return queries.list_snapshots(ctx.conn)["total"]


@ref("quality.unmapped_elements", rel=0.0)
def _(ctx):
    unmapped = queries.cost_summary(ctx.conn, ctx.snap)["unmapped_elements"]
    if unmapped is None:
        raise CaseError("no unmapped-elements metric in this snapshot")
    return unmapped["count"]


# --- slots: which level / category / cluster ... the questions are about --------------------


def _col(conn, sql, args=()):
    return [r[0] for r in conn.execute(sql, args)]


def pick_slots(ctx: Ctx) -> dict[str, str]:
    """Deterministic picks from the data (largest first), so reruns give the same questions."""
    conn, sid = ctx.conn, ctx.snap["snapshot_id"]
    slots: dict[str, str] = {}
    if ctx.snap["elements_status"] == "loaded":
        levels = _col(conn, "SELECT level FROM quantity_summary WHERE snapshot_id=? AND level<>'' "
                      "GROUP BY level ORDER BY SUM(elements) DESC, level LIMIT 2", (sid,))
        if len(levels) >= 2:
            slots["level_a"], slots["level_b"] = levels
            both = _col(conn, "SELECT category FROM quantity_summary WHERE snapshot_id=? "
                        "AND level IN (?, ?) AND category<>'' GROUP BY category "
                        "HAVING COUNT(DISTINCT level)=2 ORDER BY SUM(elements) DESC, category",
                        (sid, *levels))
            if both:
                slots["category_a"] = both[0]
                slots["category_b"] = both[1] if len(both) > 1 else both[0]
    clusters = _col(conn, "SELECT cluster FROM tvd_clusters WHERE snapshot_id=? "
                    "ORDER BY estimate DESC, cluster LIMIT 2", (sid,))
    if len(clusters) == 2:
        slots["cluster_a"], slots["cluster_b"] = clusters
    acs = _col(conn, "SELECT ac FROM tvd_line_items WHERE snapshot_id=? AND unit<>'%' AND ac<>'' "
               "GROUP BY ac ORDER BY SUM(total) DESC, ac LIMIT 1", (sid,))
    if acs:
        slots["ac_a"] = acs[0]
    if ctx.snap["stv_present"]:
        assemblies = _col(conn, "SELECT assembly FROM stv_items WHERE snapshot_id=? "
                          "GROUP BY assembly ORDER BY SUM(carbon) DESC, assembly LIMIT 2", (sid,))
        if len(assemblies) == 2:
            slots["assembly_a"], slots["assembly_b"] = assemblies
        materials = _col(conn, "SELECT material_type FROM stv_items WHERE snapshot_id=? "
                         "GROUP BY material_type ORDER BY SUM(carbon) DESC, material_type "
                         "LIMIT 8", (sid,))
        for src, dst in permutations(materials, 2):
            try:
                if queries.carbon_what_if(conn, ctx.snap, src, dst)["change_kgco2e"]:
                    slots["material_from"], slots["material_to"] = src, dst
                    break
            except ApiError:
                continue
    return slots


# --- cases -----------------------------------------------------------------------------------


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict[str, Any]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("questions"), list):
        raise CaseError(f"{path}: expected a mapping with a 'questions' list")
    return doc["questions"]


def _fill(value: Any, slots: dict[str, Any], used: set[str]) -> Any:
    if isinstance(value, str):
        def sub(m):
            if m.group(1) not in slots:
                raise CaseError(f"slot {{{m.group(1)}}} has no value in this data")
            used.add(m.group(1))
            return str(slots[m.group(1)])
        return SLOT_RE.sub(sub, value)
    if isinstance(value, dict):
        return {k: _fill(v, slots, used) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, slots, used) for v in value]
    return value


def _expect_number(ctx: Ctx, spec: dict[str, Any], slots, used) -> dict[str, Any]:
    name = spec["ref"]
    if name not in REFS:
        raise CaseError(f"unknown ref {name!r}")
    fn, rel, abs_ = REFS[name]
    args = _fill(spec.get("args", {}), slots, used)
    try:
        value = fn(ctx, **args)
    except ApiError as exc:
        raise CaseError(f"{name}({args}): {exc.code}") from exc
    except KeyError as exc:
        raise CaseError(f"{name}({args}): missing {exc}") from exc
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        raise CaseError(f"{name}({args}): no numeric value in this snapshot")
    if value == 0:
        raise CaseError(f"{name}({args}): expected value is 0 (not a useful check)")
    return {"ref": name, "args": args, "value": float(value),
            "rel_tol": spec.get("tol", rel), "abs_tol": abs_}


def build_case(ctx: Ctx, q: dict[str, Any], slots: dict[str, Any]) -> dict[str, Any]:
    """One resolved case, or CaseError."""
    params = dict(q.get("params", {}))
    all_slots = {**slots, **params}
    used: set[str] = set()
    expect = q.get("expect", {})
    case: dict[str, Any] = {
        "id": q["id"], "type": q["type"], "lang": q["lang"], "tier": q.get("tier", 1),
        "text": _fill(q["text"], all_slots, used),
        "after": _fill(q["after"], all_slots, used) if q.get("after") else None,
        "after_id": q.get("after_id"),
        "expect": {"category": expect.get("category"),
                   "language": expect.get("language", q["lang"]),
                   "max_tools": expect.get("max_tools"),
                   "numbers": [], "any_of": []},
    }
    if case["tier"] != 1:
        case["skip"] = q.get("skip", f"tier {case['tier']}: not built yet")
        return case
    for key in ("numbers", "any_of"):
        case["expect"][key] = [_expect_number(ctx, s, all_slots, used)
                               for s in expect.get(key, [])]
    # text the answer repeats from the question ("Level 2", "10%") must not count as numbers
    noise = {str(all_slots[k]) for k in used if not isinstance(all_slots[k], int | float)}
    noise |= {f"{params[k]}%" for k in params if k.startswith("pct")}
    case["noise"] = sorted(noise, key=len, reverse=True)
    return case


def build_cases(conn: sqlite3.Connection, questions: list[dict[str, Any]],
                snapshot: str | None = None
                ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """``(cases, dropped)``; ``dropped`` = ``[{"id", "reason"}]`` for unresolvable questions."""
    ctx = Ctx(conn, queries.resolve_snapshot(conn, snapshot))
    slots = pick_slots(ctx)
    cases, dropped, seen = [], [], set()
    for q in questions:
        if q["id"] in seen:
            raise CaseError(f"duplicate question id {q['id']!r}")
        seen.add(q["id"])
        try:
            cases.append(build_case(ctx, q, slots))
        except CaseError as exc:
            dropped.append({"id": q["id"], "reason": str(exc)})
    ids = {c["id"] for c in cases}
    for c in list(cases):  # a follow-up needs its first question
        if c["after_id"] and c["after_id"] not in ids:
            cases.remove(c)
            dropped.append({"id": c["id"], "reason": f"first question {c['after_id']} dropped"})
    return cases, dropped


def open_db(repo: Path | None, db: Path | None) -> sqlite3.Connection:
    from engines.api import schema
    from engines.api.ingest import IngestError, default_db_path, ingest_repo

    try:
        if db is None:
            if repo is None:
                raise CaseError("give --repo (team repo) or --db (database file)")
            db = default_db_path(repo)
            ingest_repo(repo, db)  # loads new snapshots only
        elif not Path(db).is_file():
            raise CaseError(f"{db} not found: run concho-api ingest first")
        return schema.connect(str(db), readonly=True)
    except IngestError as exc:
        raise CaseError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, help="team repo (ingested into its .concho db)")
    parser.add_argument("--db", type=Path, help="data-API database file")
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument("--snapshot", help="snapshot id (default: latest)")
    parser.add_argument("--out", type=Path, help="write the cases as JSON (contains project data)")
    args = parser.parse_args(argv)
    try:
        conn = open_db(args.repo, args.db)
        cases, dropped = build_cases(conn, load_questions(args.questions), args.snapshot)
    except (CaseError, ApiError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    payload = {"cases": cases, "dropped": dropped}
    if args.out:
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        print(f"wrote {len(cases)} cases to {args.out} ({len(dropped)} dropped)")
    else:
        for c in cases:
            nums = [f"{n['ref']}={n['value']:g}" for n in c["expect"]["numbers"]
                    + c["expect"]["any_of"]]
            print(f"{c['id']:<28} {c['lang']} {c['text'][:60]!r} {' '.join(nums)}"
                  f"{'  [SKIP: ' + c['skip'] + ']' if c.get('skip') else ''}")
        for d in dropped:
            print(f"dropped {d['id']}: {d['reason']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
