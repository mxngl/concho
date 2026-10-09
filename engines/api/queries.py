"""The parameterized queries behind the endpoints (P5.4). Plain functions on a read-only
sqlite3 connection, so they are testable without FastAPI.

Every function returns a JSON-ready dict that starts with the ``snapshot`` it comes from. They
fetch at most ``MAX_ROWS + 1`` rows, so an over-cap question stays cheap; :func:`caps.enforce`
(called by the app) turns an oversized answer into ``too_many_results``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .caps import MAX_ROWS, ApiError

UNITS = {"carbon": "kgCO2e", "energy": "MJ", "water": "kg", "ozone": "kg CFC-11e"}
CUSTOM_LABEL = ("custom_material: includes results based on custom materials (team EPD "
                "values, not course data)")
PROXY_LABEL = ("proxy: includes quantities mapped with proxy rules (a catalog entry standing "
               "in for a material the catalog lacks)")
WHAT_IF_LABEL = ("what_if: a computed scenario on the snapshot's results, not a model "
                 "result")
_LIMIT = MAX_ROWS + 1


def _r(value: Any, digits: int = 2) -> Any:
    return None if value is None else round(float(value), digits)


# --------------------------------------------------------------------------- snapshots


def resolve_snapshot(conn: sqlite3.Connection, snapshot: str | None) -> sqlite3.Row:
    """The snapshot row for ``snapshot`` (an id) or the latest one."""
    if snapshot:
        row = conn.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot,)).fetchone()
        if row is None:
            valid = [r[0] for r in conn.execute(
                "SELECT snapshot_id FROM snapshots ORDER BY timestamp DESC LIMIT 5")]
            raise ApiError(404, "unknown_snapshot",
                           "use GET /snapshots for the available snapshot ids",
                           snapshot=snapshot, latest_ids=valid)
        return row
    meta = conn.execute("SELECT value FROM meta WHERE key='latest'").fetchone()
    row = None
    if meta:
        row = conn.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (meta[0],)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 1").fetchone()
    if row is None:
        raise ApiError(404, "no_snapshots",
                       "the database is empty: run the pipeline and 'concho-api ingest'")
    return row


def snap_ref(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["snapshot_id"], "timestamp": row["timestamp"], "label": row["label"],
            "commit": (row["commit_sha"] or "")[:10] or None}


def _body(snap: sqlite3.Row, labels: list[str] | None = None, **data: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"snapshot": snap_ref(snap)}
    if labels:
        out["labels"] = labels
    out.update(data)
    return out


def normalize_ac(ac: str) -> str:
    """Prefix to match: upper case; the course's 4-digit form of a level-2 code
    (``B2000``, ``F1000``) means the whole group (``B20``, ``F10``), as in the STV mapping."""
    code = ac.strip().upper()
    group = re.fullmatch(r"([A-Z]\d{2})00", code)
    return group.group(1) if group else code


def _where_ac(column: str, ac: str, where: list[str], args: list) -> None:
    prefix = normalize_ac(ac)
    where.append(f"substr(upper({column}), 1, {len(prefix)}) = ?")
    args.append(prefix)


def list_snapshots(conn: sqlite3.Connection, limit: int = 20) -> dict[str, Any]:
    limit = max(1, min(int(limit), MAX_ROWS))
    total = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    if total == 0:
        raise ApiError(404, "no_snapshots", "the database is empty")
    rows = conn.execute(
        "SELECT snapshot_id, timestamp, label, tvd_grand_total, tvd_status, stv_present, "
        "stv_carbon_life_cycle, elements_status FROM snapshots "
        "ORDER BY timestamp DESC, snapshot_id DESC LIMIT ?", (limit,)).fetchall()
    latest = resolve_snapshot(conn, None)
    return _body(latest, total=total, shown=len(rows), rows=[{
        "id": r["snapshot_id"], "timestamp": r["timestamp"], "label": r["label"],
        "tvd_grand_total": _r(r["tvd_grand_total"]), "tvd_status": r["tvd_status"],
        "stv_kgco2e": _r(r["stv_carbon_life_cycle"]), "stv": bool(r["stv_present"]),
        "elements": r["elements_status"]} for r in rows])


# --------------------------------------------------------------------------- cost


def cost_summary(conn: sqlite3.Connection, snap: sqlite3.Row) -> dict[str, Any]:
    sid = snap["snapshot_id"]
    total, target = snap["tvd_grand_total"], snap["tvd_target"]
    clusters = conn.execute(
        "SELECT cluster, estimate, target, delta, delta_pct, per_sf, share_of_total "
        "FROM tvd_clusters WHERE snapshot_id=? ORDER BY estimate DESC LIMIT ?",
        (sid, _LIMIT)).fetchall()
    quality = {r["metric"]: r for r in conn.execute(
        "SELECT * FROM data_quality WHERE snapshot_id=? AND scope='tvd'", (sid,))}
    unmapped = quality.get("unmapped_elements")
    return _body(
        snap, currency="USD", grand_total=_r(total), target=_r(target),
        delta=_r(total - target) if total is not None and target is not None else None,
        delta_pct=_r((total - target) / target * 100) if target else None,
        status=snap["tvd_status"], cost_per_sf=_r(total / snap["gross_sf"])
        if snap["gross_sf"] else None, gross_sf=snap["gross_sf"],
        unmapped_elements=None if unmapped is None else {
            "count": unmapped["value"], "pct": unmapped["pct"],
            "note": "elements without an Assembly Code are not priced"},
        rows=[{"cluster": c["cluster"], "estimate": _r(c["estimate"]),
               "target": _r(c["target"]), "delta": _r(c["delta"]),
               "delta_pct": c["delta_pct"], "share_of_total": c["share_of_total"]}
              for c in clusters])


def _cluster_rows(conn, sid: str, cluster: str | None, ac: str | None, limit: int = _LIMIT):
    where, args = ["snapshot_id = ?"], [sid]
    if cluster:
        where.append("lower(cluster) = lower(?)")
        args.append(cluster.strip())
    if ac:
        _where_ac("ac", ac, where, args)
    cond = " AND ".join(where)
    rows = conn.execute(
        f"SELECT line_no, cluster, ac, grp, description, unit, unit_cost, qty, qty_src, total, "
        f"notes FROM tvd_line_items WHERE {cond} ORDER BY total DESC, line_no LIMIT ?",
        (*args, limit)).fetchall()
    agg = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(total), 0) FROM tvd_line_items "
                       f"WHERE {cond}", args).fetchone()
    return rows, agg[0], agg[1]


def _check_cluster(conn, sid: str, cluster: str | None) -> None:
    if not cluster:
        return
    names = [r[0] for r in conn.execute(
        "SELECT cluster FROM tvd_clusters WHERE snapshot_id=? ORDER BY cluster", (sid,))]
    if cluster.strip().lower() not in {n.lower() for n in names}:
        raise ApiError(404, "unknown_cluster", "use one of the clusters of this snapshot",
                       cluster=cluster, clusters=names[:MAX_ROWS])


def cost(conn: sqlite3.Connection, snap: sqlite3.Row, cluster: str | None = None,
         ac: str | None = None) -> dict[str, Any]:
    sid = snap["snapshot_id"]
    _check_cluster(conn, sid, cluster)
    rows, n, total = _cluster_rows(conn, sid, cluster, ac)
    if n == 0:
        raise ApiError(404, "no_match", "check the Assembly Code or use GET /cost/summary",
                       ac=ac, cluster=cluster)
    return _body(snap, currency="USD", filters={"cluster": cluster, "ac": ac},
                 matched_lines=n, matched_total=_r(total), rows=[{
                     "cluster": r["cluster"], "ac": r["ac"], "group": r["grp"],
                     "desc": r["description"], "unit": r["unit"], "unit_cost": r["unit_cost"],
                     "qty": r["qty"], "qty_src": r["qty_src"], "total": _r(r["total"]),
                     "notes": r["notes"]} for r in rows])


def cost_what_if(conn: sqlite3.Connection, snap: sqlite3.Row, ac: str,
                 change_pct: float) -> dict[str, Any]:
    """Scenario: the line items of Assembly Code ``ac`` (prefix) cost ``change_pct`` % more.

    Lines in unit ``%`` (``pct_of_subtotal``: contingency, overhead) that the code does not
    select are rescaled with the subtotal; fixed lump sums outside the code stay as they are.
    """
    if not -100 <= change_pct <= 1000:
        raise ApiError(422, "bad_change_pct", "change_pct is a percent between -100 and 1000")
    sid = snap["snapshot_id"]
    lines = conn.execute(
        "SELECT cluster, ac, unit, total FROM tvd_line_items WHERE snapshot_id=?",
        (sid,)).fetchall()
    prefix = normalize_ac(ac)
    matched = [r["ac"].upper().startswith(prefix) for r in lines]
    if not any(matched):
        raise ApiError(404, "no_match", "no line item has this Assembly Code; see GET /cost",
                       ac=ac)
    factor = 1 + change_pct / 100.0
    before = [r["total"] for r in lines]
    after = [t * factor if m else t for t, m in zip(before, matched, strict=True)]

    def sub(totals: list[float]) -> float:
        return sum(t for t, r in zip(totals, lines, strict=True) if r["unit"] != "%")

    sub_before, sub_after = sub(before), sub(after)
    indirect = 0.0
    if sub_before:
        for i, r in enumerate(lines):
            if r["unit"] == "%" and not matched[i]:
                after[i] = before[i] * sub_after / sub_before
                indirect += after[i] - before[i]
    total_before = snap["tvd_grand_total"]
    delta = sum(after) - sum(before)
    total_after, target = total_before + delta, snap["tvd_target"]
    per: dict[str, list[float]] = {}
    for r, b, a in zip(lines, before, after, strict=True):
        v = per.setdefault(r["cluster"], [0.0, 0.0])
        v[0] += b
        v[1] += a
    targets = {r["cluster"]: r["target"] for r in conn.execute(
        "SELECT cluster, target FROM tvd_clusters WHERE snapshot_id=?", (sid,))}
    changed = [{"cluster": c, "before": _r(b), "after": _r(a), "change": _r(a - b),
                "target": _r(targets.get(c)),
                "delta_to_target_after": _r(a - targets[c]) if c in targets else None}
               for c, (b, a) in per.items() if abs(a - b) > 0.005]
    direct = sum(a - b for a, b, m in zip(after, before, matched, strict=True) if m)
    return _body(
        snap, [WHAT_IF_LABEL], currency="USD",
        scenario={"ac": ac, "change_pct": change_pct, "matched_lines": sum(matched),
                  "matched_total_before": _r(sum(b for b, m in zip(before, matched, strict=True)
                                                 if m))},
        change={"direct": _r(direct), "indirect_percent_lines": _r(indirect),
                "total": _r(delta)},
        grand_total_before=_r(total_before), grand_total_after=_r(total_after),
        target=_r(target),
        delta_to_target_before=_r(total_before - target) if target is not None else None,
        delta_to_target_after=_r(total_after - target) if target is not None else None,
        status_after=None if target is None else (
            "under_target" if total_after < target else
            "over_target" if total_after > target else "on_target"),
        notes=["every matched line scales by change_pct (cost = quantity x unit cost, so a "
               "quantity change of that size)",
               "percent-of-subtotal lines (contingency, overhead) are rescaled with the "
               "subtotal; fixed lump sums outside the code are unchanged"],
        rows=changed)


# --------------------------------------------------------------------------- carbon


def _require_stv(snap: sqlite3.Row) -> None:
    if not snap["stv_present"]:
        raise ApiError(404, "no_stv", snap["stv_note"] or "this snapshot has no STV result",
                       snapshot=snap_ref(snap))


def _flags(snap: sqlite3.Row) -> list[str]:
    labels = []
    if snap["stv_custom_material"]:
        labels.append(CUSTOM_LABEL)
    if snap["stv_proxy"]:
        labels.append(PROXY_LABEL)
    return labels


def carbon_summary(conn: sqlite3.Connection, snap: sqlite3.Row) -> dict[str, Any]:
    _require_stv(snap)
    sid = snap["snapshot_id"]
    metrics = {r["metric"]: r for r in conn.execute(
        "SELECT * FROM stv_summary WHERE snapshot_id=?", (sid,))}
    carbon = metrics.get("carbon")
    assemblies = conn.execute(
        "SELECT assembly, SUM(carbon) AS carbon, MAX(custom_material) AS custom, "
        "MAX(proxy_amount > 0) AS proxy FROM stv_items WHERE snapshot_id=? "
        "GROUP BY assembly ORDER BY carbon DESC LIMIT ?", (sid, _LIMIT)).fetchall()
    quality = {r["metric"]: r for r in conn.execute(
        "SELECT * FROM data_quality WHERE snapshot_id=? AND scope='stv'", (sid,))}
    mapped = quality.get("mapped_elements")
    return _body(
        snap, _flags(snap), units=UNITS,
        metrics={m: {"target": _r(r["target"]), "life_cycle": _r(r["project"]),
                     "percent_of_target": _r(r["percent_of_target"], 4),
                     "embodied": _r(r["embodied"]), "use_phase": _r(r["use_phase"])}
                 for m, r in metrics.items()},
        carbon_breakdown=None if carbon is None else {
            "embodied_materials": _r(carbon["embodied_materials"]),
            "embodied_transport": _r(carbon["embodied_transport"]),
            "embodied_construction": _r(carbon["embodied_construction"]),
            "use_electricity": _r(carbon["use_electricity"]),
            "use_heating": _r(carbon["use_heating"]), "use_water": _r(carbon["use_water"])},
        use_phase_modeled=bool(snap["stv_use_phase_modeled"]),
        warnings=([] if snap["stv_use_phase_modeled"] else
                  ["use phase not modeled: life cycle = embodied only"]),
        mapping=None if mapped is None else {"mapped_pct": mapped["pct"]},
        rows=[{"stv_assembly": a["assembly"], "embodied_kgco2e": _r(a["carbon"]),
               "custom_material": bool(a["custom"]), "proxy": bool(a["proxy"])}
              for a in assemblies])


def _item_row(r: sqlite3.Row) -> dict[str, Any]:
    out = {"stv_assembly": r["assembly"], "material": r["material_type"], "unit": r["unit"],
           "amount": _r(r["amount"], 3), "kgco2e": _r(r["carbon"]), "mj": _r(r["energy"]),
           "water_kg": _r(r["water"]), "custom_material": bool(r["custom_material"]),
           "proxy": r["proxy_amount"] > 0, "estimated": r["estimated_amount"] > 0}
    if r["custom_material"]:
        out["custom_material_source"] = r["custom_material_source"]
    if r["origin"] and r["origin"] != "input":
        out["origin"] = r["origin"]
    return out


def carbon(conn: sqlite3.Connection, snap: sqlite3.Row, stv_assembly: str | None = None,
           material: str | None = None) -> dict[str, Any]:
    _require_stv(snap)
    sid = snap["snapshot_id"]
    where, args = ["snapshot_id = ?"], [sid]
    if stv_assembly:
        where.append("lower(assembly) = lower(?)")
        args.append(stv_assembly.strip())
    if material:
        where.append("instr(lower(material_type), lower(?)) > 0")
        args.append(material.strip())
    cond = " AND ".join(where)
    n, total = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(carbon), 0) FROM stv_items "
                            f"WHERE {cond}", args).fetchone()
    if n == 0:
        names = [r[0] for r in conn.execute(
            "SELECT DISTINCT assembly FROM stv_items WHERE snapshot_id=? ORDER BY assembly "
            "LIMIT ?", (sid, MAX_ROWS))]
        raise ApiError(404, "no_match", "check stv_assembly / material; use GET /carbon/summary",
                       stv_assembly=stv_assembly, material=material, assemblies=names)
    rows = conn.execute(f"SELECT * FROM stv_items WHERE {cond} ORDER BY carbon DESC LIMIT ?",
                        (*args, _LIMIT)).fetchall()
    labels = []
    if any(r["custom_material"] for r in rows):
        labels.append(CUSTOM_LABEL)
    if any(r["proxy_amount"] > 0 for r in rows):
        labels.append(PROXY_LABEL)
    return _body(snap, labels, units=UNITS,
                 filters={"stv_assembly": stv_assembly, "material": material},
                 matched_items=n, matched_embodied_kgco2e=_r(total),
                 rows=[_item_row(r) for r in rows])


def carbon_what_if(conn: sqlite3.Connection, snap: sqlite3.Row, material_from: str,
                   material_to: str, stv_assembly: str | None = None) -> dict[str, Any]:
    """Scenario: all of ``material_from`` is ``material_to`` instead (same quantity).

    The per-unit factor of ``material_to`` is read from the same snapshot (embodied kgCO2e per
    unit of an item that uses it): the API has no LCA catalog (course data). So ``material_to``
    must already occur in the project, with the same unit.
    """
    _require_stv(snap)
    sid = snap["snapshot_id"]
    where, args = ["snapshot_id = ?", "lower(material_type) = lower(?)"], [sid,
                                                                          material_from.strip()]
    if stv_assembly:
        where.append("lower(assembly) = lower(?)")
        args.append(stv_assembly.strip())
    src = conn.execute(f"SELECT * FROM stv_items WHERE {' AND '.join(where)} ORDER BY item_no",
                       args).fetchall()
    if not src:
        have = [r[0] for r in conn.execute(
            "SELECT DISTINCT material_type FROM stv_items WHERE snapshot_id=? "
            "AND instr(lower(material_type), lower(?)) > 0 LIMIT 20", (sid, material_from))]
        raise ApiError(404, "no_match", "material_from must be a material_type of this project "
                       "(exact name, see GET /carbon)", material_from=material_from,
                       similar=have)
    dest = conn.execute(
        "SELECT * FROM stv_items WHERE snapshot_id=? AND lower(material_type)=lower(?) "
        "AND carbon_per_unit IS NOT NULL", (sid, material_to.strip())).fetchall()
    if not dest:
        raise ApiError(404, "unknown_material_factor",
                       "the API has no LCA catalog: material_to must already be used in this "
                       "project (GET /carbon); add it to the model or mapping first",
                       material_to=material_to)
    out_rows, before, after = [], 0.0, 0.0
    for s in src:
        same = [d for d in dest if d["assembly"] == s["assembly"]] or dest
        factors = {round(d["carbon_per_unit"], 9) for d in same}
        if len(factors) > 1:
            raise ApiError(409, "ambiguous_factor", "material_to has several per-unit factors "
                           "in this project; pass stv_assembly to pick one",
                           material_to=material_to,
                           assemblies=sorted({d["assembly"] for d in same}))
        d = same[0]
        if (s["unit"] or "") != (d["unit"] or ""):
            raise ApiError(422, "unit_mismatch", "material_from and material_to must have the "
                           "same unit", material_from_unit=s["unit"], material_to_unit=d["unit"])
        new = s["amount"] * d["carbon_per_unit"]
        before += s["carbon"]
        after += new
        out_rows.append({"stv_assembly": s["assembly"], "unit": s["unit"],
                         "amount": _r(s["amount"], 3), "kgco2e_before": _r(s["carbon"]),
                         "kgco2e_after": _r(new), "change": _r(new - s["carbon"]),
                         "custom_material": bool(s["custom_material"] or d["custom_material"]),
                         "proxy": s["proxy_amount"] > 0 or d["proxy_amount"] > 0})
    life, target = snap["stv_carbon_life_cycle"], snap["stv_carbon_target"]
    labels = [WHAT_IF_LABEL, "the factor of material_to is the per-unit factor it has in this "
              "project's results (embodied, incl. transport and construction)"]
    if any(r["custom_material"] for r in out_rows):
        labels.append(CUSTOM_LABEL)
    if any(r["proxy"] for r in out_rows):
        labels.append(PROXY_LABEL)
    return _body(
        snap, labels, units=UNITS,
        scenario={"material_from": material_from, "material_to": material_to,
                  "stv_assembly": stv_assembly},
        change_kgco2e=_r(after - before), embodied_before=_r(before), embodied_after=_r(after),
        life_cycle_before=_r(life), life_cycle_after=_r(life + after - before),
        target=_r(target),
        percent_of_target_before=_r(life / target, 4) if target else None,
        percent_of_target_after=_r((life + after - before) / target, 4) if target else None,
        rows=out_rows)


# --------------------------------------------------------------------------- quantities


def _require_elements(snap: sqlite3.Row) -> None:
    if snap["elements_status"] != "loaded":
        raise ApiError(404, "elements_unavailable",
                       snap["elements_note"] or "no element data for this snapshot",
                       elements_status=snap["elements_status"], snapshot=snap_ref(snap))


def _qty_filters(category, level, ac) -> tuple[list[str], list]:
    where, args = [], []
    if category:
        where.append("lower(category) = lower(?)")
        args.append(category.strip())
    if level:
        where.append("lower(level) = lower(?)")
        args.append(level.strip())
    if ac:
        _where_ac("ac", ac, where, args)
    return where, args


def quantities(conn: sqlite3.Connection, snap: sqlite3.Row, category: str | None = None,
               level: str | None = None, ac: str | None = None) -> dict[str, Any]:
    _require_elements(snap)
    sid = snap["snapshot_id"]
    where, args = _qty_filters(category, level, ac)
    cond = " AND ".join(["snapshot_id = ?", *where])
    args = [sid, *args]
    n, elements, area, length, volume = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(elements),0), COALESCE(SUM(area_sf),0), "
        f"COALESCE(SUM(length_lf),0), COALESCE(SUM(volume_cf),0) FROM quantity_summary "
        f"WHERE {cond}", args).fetchone()
    if n == 0:
        levels = [r[0] for r in conn.execute(
            "SELECT DISTINCT level FROM quantity_summary WHERE snapshot_id=? ORDER BY level "
            "LIMIT 20", (sid,))]
        cats = [r[0] for r in conn.execute(
            "SELECT category FROM quantity_summary WHERE snapshot_id=? GROUP BY category "
            "ORDER BY SUM(elements) DESC LIMIT 20", (sid,))]
        raise ApiError(404, "no_match", "check category / level / ac", levels=levels,
                       categories=cats)
    rows = conn.execute(
        f"SELECT category, level, ac, elements, area_sf, length_lf, volume_cf FROM "
        f"quantity_summary WHERE {cond} ORDER BY area_sf DESC, elements DESC, category, level, "
        f"ac LIMIT ?", (*args, _LIMIT)).fetchall()
    return _body(
        snap, units={"area": "SF", "length": "LF", "volume": "CF"},
        filters={"category": category, "level": level, "ac": ac},
        notes=["deduplicated element rows (D15), rows with the DNC marker left out; quantities "
               "as exported (not the TVD pricing quantities per cost line)"],
        matched_groups=n,
        totals={"elements": int(elements), "area_sf": _r(area), "length_lf": _r(length),
                "volume_cf": _r(volume)},
        rows=[{"category": r["category"], "level": r["level"] or None, "ac": r["ac"] or None,
               "elements": r["elements"], "area_sf": _r(r["area_sf"]),
               "length_lf": _r(r["length_lf"]), "volume_cf": _r(r["volume_cf"])}
              for r in rows])


def elements_count(conn: sqlite3.Connection, snap: sqlite3.Row, category: str | None = None,
                   level: str | None = None, ac: str | None = None,
                   discipline: str | None = None) -> dict[str, Any]:
    _require_elements(snap)
    sid = snap["snapshot_id"]
    where, args = ["snapshot_id = ?"], [sid]
    if category:
        where.append("lower(category) = lower(?)")
        args.append(category.strip())
    if level:
        where.append("lower(level) = lower(?)")
        args.append(level.strip())
    if ac:
        _where_ac("assembly_code", ac, where, args)
    if discipline:
        where.append("discipline = ?")
        args.append(discipline.strip().lower())
    cond = " AND ".join(where)
    count, dnc = conn.execute(
        f"SELECT COALESCE(SUM(dnc = 0), 0), COALESCE(SUM(dnc), 0) FROM elements WHERE {cond}",
        args).fetchone()
    by_disc = conn.execute(
        f"SELECT discipline, COUNT(*) AS n FROM elements WHERE {cond} AND dnc = 0 "
        f"GROUP BY discipline ORDER BY discipline", args).fetchall()
    return _body(snap, filters={"category": category, "level": level, "ac": ac,
                                "discipline": discipline},
                 count=int(count), excluded_dnc=int(dnc),
                 notes=["deduplicated element rows (D15), DNC rows not counted"],
                 rows=[{"discipline": r["discipline"], "count": r["n"]} for r in by_disc])


# --------------------------------------------------------------------------- quality


def quality(conn: sqlite3.Connection, snap: sqlite3.Row) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT scope, metric, value, total, pct, detail FROM data_quality "
        "WHERE snapshot_id=? ORDER BY scope, metric LIMIT ?", (snap["snapshot_id"], _LIMIT)
    ).fetchall()
    return _body(snap, elements_status=snap["elements_status"],
                 elements_note=snap["elements_note"], rows=[{
                     "scope": r["scope"], "metric": r["metric"], "value": r["value"],
                     "total": r["total"], "pct": r["pct"],
                     "detail": json.loads(r["detail"]) if r["detail"] else None} for r in rows])


# --------------------------------------------------------------------------- compare


def compare(conn: sqlite3.Connection, a: sqlite3.Row, b: sqlite3.Row) -> dict[str, Any]:
    """``b`` against ``a`` (change = b - a). The body names both snapshots."""
    def clusters(sid):
        return {r["cluster"]: r["estimate"] for r in conn.execute(
            "SELECT cluster, estimate FROM tvd_clusters WHERE snapshot_id=?", (sid,))}

    ca, cb = clusters(a["snapshot_id"]), clusters(b["snapshot_id"])

    def diff(x, y):
        return None if x is None or y is None else _r(y - x)

    def pct(x, y):
        return None if not x or y is None else _r((y - x) / x * 100)

    def count(snap):
        if snap["elements_status"] != "loaded":
            return None
        return conn.execute("SELECT COUNT(*) FROM elements WHERE snapshot_id=? AND dnc=0",
                            (snap["snapshot_id"],)).fetchone()[0]

    ea, eb = count(a), count(b)
    labels = []
    if not (a["stv_present"] and b["stv_present"]):
        labels.append("carbon: at least one of the snapshots has no STV result")
    labels += [lab for lab in _flags(b) if b["stv_present"]]
    return {
        "snapshot": snap_ref(b), "compared": {"a": snap_ref(a), "b": snap_ref(b)},
        **({"labels": labels} if labels else {}),
        "cost": {"grand_total_a": _r(a["tvd_grand_total"]),
                 "grand_total_b": _r(b["tvd_grand_total"]),
                 "change": diff(a["tvd_grand_total"], b["tvd_grand_total"]),
                 "change_pct": pct(a["tvd_grand_total"], b["tvd_grand_total"]),
                 "target_a": _r(a["tvd_target"]), "target_b": _r(b["tvd_target"])},
        "carbon": {"unit": "kgCO2e", "life_cycle_a": _r(a["stv_carbon_life_cycle"]),
                   "life_cycle_b": _r(b["stv_carbon_life_cycle"]),
                   "change": diff(a["stv_carbon_life_cycle"], b["stv_carbon_life_cycle"]),
                   "change_pct": pct(a["stv_carbon_life_cycle"], b["stv_carbon_life_cycle"])},
        "elements": {"count_a": ea, "count_b": eb,
                     "change": None if ea is None or eb is None else eb - ea},
        "rows": [{"cluster": c, "estimate_a": _r(ca.get(c)), "estimate_b": _r(cb.get(c)),
                  "change": diff(ca.get(c), cb.get(c)), "change_pct": pct(ca.get(c), cb.get(c))}
                 for c in sorted(set(ca) | set(cb), key=lambda c: -(cb.get(c) or ca.get(c) or 0))],
    }
