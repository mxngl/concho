"""Generate the evaluation set of the Concho agent from the data API's database (roadmap P6.8).

``tests/agent_eval/questions.yaml`` holds only question *templates* and *expectations by
reference*: ``{fact: cost.grand_total}`` instead of a number. This script resolves every fact
against the SQLite database the data API serves (the same functions as the endpoints, so the
expected numbers are exactly what the tools return, and those are the engine results), picks
names from the data (a cluster, a level, a category) and writes ``eval_set.json``:

    python scripts/build_eval_set.py --repo path/to/team-repo      # ingests, then generates
    python scripts/build_eval_set.py --db path/to/concho.db

The output contains project numbers (derived from course / RSMeans-based data on the Island
fixtures), so it goes to ``tests/agent_eval/generated/`` which is git-ignored. Nothing typed in:
change the data, run the script again. A question whose fact cannot be computed from this
database (no STV result, one snapshot only, ...) is written with ``skip`` and a reason, never
dropped silently; tier-2 questions are written with ``skip: tier2``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engines.api import queries, schema  # noqa: E402
from engines.api.caps import ApiError  # noqa: E402
from engines.api.ingest import ingest_repo  # noqa: E402

QUESTIONS = REPO_ROOT / "tests" / "agent_eval" / "questions.yaml"
DEFAULT_OUT = REPO_ROOT / "tests" / "agent_eval" / "generated" / "eval_set.json"
RESERVED = {"fact", "ref", "label", "tol", "exact"}
WHAT_IF_STEPS = (10, 25, 50, 100)


class FactUnavailable(Exception):
    """The database cannot answer this fact (the question is skipped with this reason)."""


class Ctx:
    """The database, the snapshot under test and a cache for the query results."""

    def __init__(self, conn, snap) -> None:
        self.conn, self.snap, self._cache = conn, snap, {}

    def cached(self, key: str, build: Callable[[], Any]) -> Any:
        if key not in self._cache:
            try:
                self._cache[key] = build()
            except ApiError as exc:
                raise FactUnavailable(f"{exc.code}: {exc.hint}") from exc
        return self._cache[key]

    def sql(self, query: str, *args) -> list:
        return self.conn.execute(query, (self.snap["snapshot_id"], *args)).fetchall()


FACTS: dict[str, Callable[..., Any]] = {}


def fact(name: str):
    def register(fn):
        FACTS[name] = fn
        return fn
    return register


# ------------------------------------------------------------------ cost


def _cost(ctx: Ctx) -> dict:
    return ctx.cached("cost", lambda: queries.cost_summary(ctx.conn, ctx.snap))


def _cluster(ctx: Ctx, cluster: str) -> dict:
    for row in _cost(ctx)["rows"]:
        if row["cluster"].lower() == str(cluster).lower():
            return row
    raise FactUnavailable(f"cluster {cluster!r} not in the snapshot")


def _ac_groups(ctx: Ctx) -> list[str]:
    rows = ctx.sql("SELECT substr(upper(ac), 1, 3) AS g, SUM(total) AS t FROM tvd_line_items "
                   "WHERE snapshot_id=? AND ac <> '' GROUP BY g ORDER BY t DESC, g")
    return [r["g"] for r in rows]


@fact("cost.grand_total")
def _(ctx): return _cost(ctx)["grand_total"]


@fact("cost.target")
def _(ctx): return _cost(ctx)["target"]


@fact("cost.delta")
def _(ctx):
    delta = _cost(ctx)["delta"]
    if delta is None:
        raise FactUnavailable("no target")
    return abs(delta)


@fact("cost.status")
def _(ctx):
    status = _cost(ctx)["status"]
    if status not in ("over_target", "under_target"):
        raise FactUnavailable(f"grand total status is {status!r}")
    return status


@fact("cost.per_sf")
def _(ctx):
    value = _cost(ctx)["cost_per_sf"]
    if value is None:
        raise FactUnavailable("no gross area")
    return value


@fact("cost.cluster_names")
def _(ctx): return [r["cluster"] for r in _cost(ctx)["rows"]]


@fact("cost.top_cluster")
def _(ctx): return _cost(ctx)["rows"][0]["cluster"]


@fact("cost.cluster_estimate")
def _(ctx, cluster): return _cluster(ctx, cluster)["estimate"]


@fact("cost.cluster_target")
def _(ctx, cluster): return _cluster(ctx, cluster)["target"]


@fact("cost.cluster_status")
def _(ctx, cluster):
    status = _cluster(ctx, cluster)["status"]
    if status not in ("over_target", "under_target"):
        raise FactUnavailable(f"cluster status is {status!r}")
    return status


@fact("cost.top_ac")
def _(ctx):
    groups = _ac_groups(ctx)
    if not groups:
        raise FactUnavailable("no Assembly Codes in the line items")
    return groups[0]


@fact("cost.second_ac")
def _(ctx):
    groups = _ac_groups(ctx)
    if len(groups) < 2:
        raise FactUnavailable("fewer than two Assembly Code groups")
    return groups[1]


@fact("cost.ac_total")
def _(ctx, ac): return ctx.cached(f"ac:{ac}", lambda: queries.cost(
    ctx.conn, ctx.snap, None, ac))["matched_total"]


@fact("cost.many_line_items")
def _(ctx):
    n = ctx.sql("SELECT COUNT(*) FROM tvd_line_items WHERE snapshot_id=?")[0][0]
    return n > 50


@fact("cost.whatif")
def _(ctx, ac, pct):
    result = ctx.cached(f"wi:{ac}:{pct}", lambda: queries.cost_what_if(
        ctx.conn, ctx.snap, ac, float(pct)))
    return {"ac": ac, "pct": pct, "grand_total_after": result["grand_total_after"],
            "change": result["change"]["total"]}


@fact("cost.whatif_flip")
def _(ctx):
    """An Assembly Code group and a percent after which one cluster is over its own target
    (the case the agent once got wrong: the grand total's status is not the cluster's)."""
    best = None
    for ac in _ac_groups(ctx):
        for pct in WHAT_IF_STEPS:
            try:
                result = queries.cost_what_if(ctx.conn, ctx.snap, ac, float(pct))
            except ApiError:
                continue
            for row in result["rows"]:
                if row["status_after"] == "over_target":
                    flipped = row["status_before"] == "under_target"
                    cand = (not flipped, pct, ac)
                    if best is None or cand < best[0]:
                        best = (cand, ac, pct, row, result)
    if best is None:
        raise FactUnavailable("no what-if step puts a cluster over its target")
    _, ac, pct, row, result = best
    return {"ac": ac, "pct": pct, "cluster": row["cluster"], "cluster_after": row["after"],
            "cluster_target": row["target"], "cluster_delta": row["delta_to_target_after"],
            "grand_total_after": result["grand_total_after"],
            "grand_total_status": result["status_after"]}


# ------------------------------------------------------------------ carbon


def _carbon(ctx: Ctx) -> dict:
    return ctx.cached("carbon", lambda: queries.carbon_summary(ctx.conn, ctx.snap))


def _metric(ctx: Ctx, metric: str, key: str):
    entry = _carbon(ctx)["metrics"].get(metric)
    if not entry or entry.get(key) is None:
        raise FactUnavailable(f"no {metric}.{key} in the STV result")
    return entry[key]


@fact("carbon.life_cycle")
def _(ctx): return _metric(ctx, "carbon", "life_cycle")


@fact("carbon.target")
def _(ctx): return _metric(ctx, "carbon", "target")


@fact("carbon.percent_of_target")
def _(ctx): return round(_metric(ctx, "carbon", "percent_of_target") * 100, 2)


@fact("carbon.embodied")
def _(ctx): return _metric(ctx, "carbon", "embodied")


@fact("carbon.use_phase")
def _(ctx):
    if not _carbon(ctx)["use_phase_modeled"]:
        raise FactUnavailable("use phase not modeled in this snapshot")
    return _metric(ctx, "carbon", "use_phase")


@fact("carbon.energy")
def _(ctx): return _metric(ctx, "energy", "life_cycle")


@fact("carbon.water")
def _(ctx): return _metric(ctx, "water", "life_cycle")


@fact("carbon.top_assembly")
def _(ctx):
    rows = _carbon(ctx)["rows"]
    if not rows:
        raise FactUnavailable("no STV assemblies")
    return rows[0]["stv_assembly"]


@fact("carbon.second_assembly")
def _(ctx):
    rows = _carbon(ctx)["rows"]
    if len(rows) < 2:
        raise FactUnavailable("fewer than two STV assemblies")
    return rows[1]["stv_assembly"]


@fact("carbon.assembly_embodied")
def _(ctx, assembly): return ctx.cached(f"asm:{assembly}", lambda: queries.carbon(
    ctx.conn, ctx.snap, assembly, None))["matched_embodied_kgco2e"]


@fact("carbon.swap")
def _(ctx):
    """A material pair the API can swap (same unit, a factor in the project)."""
    _carbon(ctx)  # raises when the snapshot has no STV result
    materials = [r[0] for r in ctx.sql(
        "SELECT material_type FROM stv_items WHERE snapshot_id=? GROUP BY material_type "
        "ORDER BY SUM(carbon) DESC, material_type")]
    for source in materials[:6]:
        for dest in materials:
            if dest == source:
                continue
            try:
                result = queries.carbon_what_if(ctx.conn, ctx.snap, source, dest)
            except ApiError:
                continue
            if abs(result["change_kgco2e"]) > 1:
                return {"from": source, "to": dest, "change": abs(result["change_kgco2e"]),
                        "embodied_after": result["embodied_after"],
                        "life_cycle_after": result["life_cycle_after"]}
    raise FactUnavailable("no material pair with the same unit and a known factor")


# ------------------------------------------------------------------ quantities


def _require_elements(ctx: Ctx) -> None:
    if ctx.snap["elements_status"] != "loaded":
        raise FactUnavailable(f"elements {ctx.snap['elements_status']}: no quantities")


@fact("qty.total_elements")
def _(ctx):
    _require_elements(ctx)
    return queries.elements_count(ctx.conn, ctx.snap)["count"]


def _ranked(ctx: Ctx, column: str, measure: str, where: str = "", *args) -> list[str]:
    _require_elements(ctx)
    rows = ctx.sql(f"SELECT {column} AS name FROM quantity_summary WHERE snapshot_id=? "
                   f"AND {column} <> '' {where} GROUP BY {column} "
                   f"ORDER BY SUM({measure}) DESC, {column}", *args)
    return [r["name"] for r in rows]


@fact("qty.category")
def _(ctx, rank=0):
    names = _ranked(ctx, "category", "elements")
    if len(names) <= rank:
        raise FactUnavailable("not enough categories")
    return names[rank]


@fact("qty.area_category")
def _(ctx):
    names = _ranked(ctx, "category", "area_sf")
    if not names:
        raise FactUnavailable("no categories")
    return names[0]


@fact("qty.level")
def _(ctx, category, rank=0):
    names = _ranked(ctx, "level", "elements", "AND category = ?", category)
    if len(names) <= rank:
        raise FactUnavailable(f"{category!r} is on fewer than {rank + 1} levels")
    return names[rank]


@fact("qty.count")
def _(ctx, category=None, level=None):
    _require_elements(ctx)
    return queries.elements_count(ctx.conn, ctx.snap, category, level)["count"]


@fact("qty.area")
def _(ctx, category=None, level=None):
    _require_elements(ctx)
    area = queries.quantities(ctx.conn, ctx.snap, category, level)["totals"]["area_sf"]
    if not area:
        raise FactUnavailable("zero area")
    return area


@fact("qty.level_names")
def _(ctx):
    names = _ranked(ctx, "level", "elements")
    if not names:
        raise FactUnavailable("no levels")
    return names


@fact("qty.level_with_most_elements")
def _(ctx):
    _require_elements(ctx)
    names = _ranked(ctx, "level", "elements")
    if not names:
        raise FactUnavailable("no levels")
    return names[0]


# ------------------------------------------------------------------ quality and snapshots


@fact("quality.unmapped_elements")
def _(ctx):
    rows = ctx.sql("SELECT value FROM data_quality WHERE snapshot_id=? AND scope='tvd' "
                   "AND metric='unmapped_elements'")
    if not rows:
        raise FactUnavailable("no unmapped_elements metric")
    return rows[0]["value"]


@fact("snap.count")
def _(ctx): return ctx.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]


@fact("snap.has_two")
def _(ctx): return ctx.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] >= 2


@fact("snap.latest_label")
def _(ctx): return ctx.snap["label"]


# ------------------------------------------------------------------ resolving


def lookup(binds: dict[str, Any], path: str) -> Any:
    """``w.cluster`` -> ``binds["w"]["cluster"]``."""
    head, *rest = path.split(".")
    if head not in binds:
        raise FactUnavailable(f"unknown binding {head!r}")
    value = binds[head]
    for part in rest:
        value = value[part]
    return value


def resolve(spec: Any, ctx: Ctx, binds: dict[str, Any]) -> Any:
    """A literal, ``$name.path`` (a binding), ``{ref: name.path}`` or ``{fact: ..., args}``."""
    if isinstance(spec, str) and spec.startswith("$"):
        return lookup(binds, spec[1:])
    if isinstance(spec, dict) and "ref" in spec:
        return lookup(binds, spec["ref"])
    if isinstance(spec, dict) and "fact" in spec:
        name = spec["fact"]
        if name not in FACTS:
            raise KeyError(f"unknown fact {name!r}")
        args = {k: resolve(v, ctx, binds) for k, v in spec.items() if k not in RESERVED}
        return FACTS[name](ctx, **args)
    if isinstance(spec, list):
        return [resolve(x, ctx, binds) for x in spec]
    return spec


def resolve_number(spec: dict, ctx: Ctx, binds: dict[str, Any], default_tol: float) -> dict:
    value = float(resolve(spec, ctx, binds))
    exact = bool(spec.get("exact", False))
    label = spec.get("label") or spec.get("fact") or spec.get("ref")
    return {"value": value, "label": label, "exact": exact,
            "tol": 0.0 if exact else float(spec.get("tol", default_tol))}


def resolve_question(q: dict, ctx: Ctx, defaults: dict) -> dict:
    """The question as the runner needs it, or the same entry with ``skip``."""
    out: dict[str, Any] = {k: q[k] for k in ("id", "group", "tier", "lang", "note") if k in q}
    out.setdefault("tier", 1)
    out["category"] = q.get("category")
    if out["tier"] != 1:
        out["skip"] = f"tier{out['tier']}"
        out["ask"] = q["ask"]
        return out
    try:
        binds: dict[str, Any] = {}
        for requirement in q.get("requires", []):
            if not resolve(requirement, ctx, binds):
                raise FactUnavailable(f"requirement not met: {requirement.get('fact')}")
        for name, spec in (q.get("bind") or {}).items():
            binds[name] = resolve(spec, ctx, binds)
        expect_in = q.get("expect") or {}
        expect: dict[str, Any] = {}
        tol = float(defaults.get("number_tolerance", 0.005))
        if expect_in.get("numbers"):
            expect["numbers"] = [resolve_number(n, ctx, binds, tol) for n in expect_in["numbers"]]
        if "status" in expect_in:
            st = expect_in["status"]
            expect["status"] = {"value": resolve(st["value"], ctx, binds),
                                "subject": resolve(st.get("subject"), ctx, binds)}
        if "names_any" in expect_in:
            expect["names_any"] = [str(x) for x in resolve(expect_in["names_any"], ctx, binds)]
        if "names_all" in expect_in:
            expect["names_all"] = [str(x) for x in resolve(expect_in["names_all"], ctx, binds)]
        for flag in ("scenario_label", "no_tools", "asks_to_narrow", "category_required",
                     "needs_tools"):
            if expect_in.get(flag):
                expect[flag] = True
        if expect_in.get("tool_errors_allowed"):
            expect["tool_errors_allowed"] = list(expect_in["tool_errors_allowed"])
        out["ask"] = str(q["ask"]).format_map(binds)
        out["setup"] = [str(s).format_map(binds) for s in q.get("setup", [])]
        out["expect"] = expect
        if expect.get("numbers") or expect.get("status") or expect.get("names_any"):
            expect.setdefault("needs_tools", True)
    except (FactUnavailable, KeyError, IndexError) as exc:
        out["skip"] = f"data: {exc}"
        out["ask"] = str(q.get("ask", ""))
    return out


def build(conn, snapshot: str | None = None) -> dict:
    import yaml  # PyYAML (dev dependency)

    spec = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    snap = queries.resolve_snapshot(conn, snapshot)
    ctx = Ctx(conn, snap)
    defaults = spec.get("defaults") or {}
    questions = [resolve_question(q, ctx, defaults) for q in spec["questions"]]
    return {"version": spec.get("version", 1),
            "snapshot": queries.snap_ref(snap),
            "settings": defaults,
            "questions": questions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", type=Path, metavar="DIR",
                        help="team repo with results/: ingested into its .concho/concho.db first")
    source.add_argument("--db", type=Path, metavar="FILE", help="an existing concho.db")
    parser.add_argument("--snapshot", metavar="ID", help="default: the latest snapshot")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, metavar="FILE")
    args = parser.parse_args(argv)
    db = args.db
    if args.repo:
        db = Path(ingest_repo(args.repo)["db"])
    conn = schema.connect(str(db), readonly=True)
    try:
        result = build(conn, args.snapshot)
    finally:
        conn.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    questions = result["questions"]
    skipped = [q for q in questions if q.get("skip")]
    print(f"{len(questions) - len(skipped)} questions to run, {len(skipped)} skipped "
          f"(snapshot {result['snapshot']['id']}) -> {args.out}")
    for q in skipped:
        print(f"  skip {q['id']}: {q['skip']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
