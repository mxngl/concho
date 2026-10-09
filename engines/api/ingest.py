"""P5.3: load the pipeline results of a team repo into SQLite (``concho.db``).

Input: ``<repo>/results/index.json`` (P5.5) and, per snapshot, the files named in its
``paths`` (``tvd_results.json``, ``stv_results.json``) plus the export CSVs listed in its
``exports``. Output: one row set per snapshot in every table of :mod:`engines.api.schema`.

What is *not* done here: nothing of the TVD or STV logic is recomputed. Totals, clusters,
line items, STV items and the STV summary are copied from the results JSON. The only new
aggregation is over the **element rows**, which the results do not contain: the export rows
go through the shared D15 rule (:func:`engines.common.dedup.deduplicate`, Parts over their
host, one row per ElementId) and are summed per category x level x Assembly Code with the
tolerant quantity parser (:mod:`engines.common.quantities`).

Exports are team files that change over time (``exports/`` holds the latest only). Elements are
therefore attached to a snapshot only when they reproduce it: the TVD run counted
``meta.total_elements`` rows after the same rule, so the exports must give the same number.
Otherwise the snapshot gets ``elements_status = 'stale'`` and no element rows; run the ingest
right after the pipeline (``concho-api ingest`` as a workflow step).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engines.common.dedup import (
    ARCHITECTURE,
    MEP,
    STRUCTURAL,
    Export,
    deduplicate,
    effective_category,
    is_part,
)
from engines.common.quantities import AREA, LENGTH, VOLUME, parse_quantity
from engines.tvd.loading import load_csv_file
from engines.tvd.quantities import DNC_MARKER
from engines.tvd.rules import EXCLUDE_CATEGORIES

from . import SCHEMA_VERSION, schema, summaries

RESULTS_DIR = "results"
INDEX_NAME = "index.json"
DB_DIR = ".concho"  # git-ignored in the team repo template (a build artifact, not a result)
DB_NAME = "concho.db"

# Revit add-in export names (docs/model-requirements.md), as in scripts/run_pipeline.py.
EXPORT_SUFFIXES = (
    (ARCHITECTURE, "_architecture_takeoff.csv"),
    (STRUCTURAL, "_structural_schedule.csv"),
    (MEP, "_mep_takeoff.csv"),
)
DNC_FIELDS = ("Family", "Type", "Mark", "Comments")
_UNIT_RE = re.compile(r"\(([^()]*)\)\s*$")


class IngestError(Exception):
    """A problem that stops the ingest; the message is shown as is."""


def default_db_path(repo: Path) -> Path:
    return repo / DB_DIR / DB_NAME


def load_index(repo: Path) -> dict:
    path = repo / RESULTS_DIR / INDEX_NAME
    if not path.is_file():
        raise IngestError(f"{path} not found: run the pipeline first "
                          "(docs/pipeline.md) or point --repo at a team repo with results/.")
    index = json.loads(path.read_text(encoding="utf-8"))
    index.setdefault("snapshots", [])
    return index


def _read_json(repo: Path, rel: str | None) -> dict | None:
    if not rel:
        return None
    path = repo / rel
    if not path.is_file():
        raise IngestError(f"{rel} is listed in results/{INDEX_NAME} but missing.")
    return json.loads(path.read_text(encoding="utf-8"))


def discipline_of(name: str) -> str | None:
    lower = name.lower()
    for discipline, suffix in EXPORT_SUFFIXES:
        if lower.endswith(suffix):
            return discipline
    return None


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


# --------------------------------------------------------------------------- elements


def _is_dnc(row: dict) -> bool:
    marker = DNC_MARKER.upper()
    return any(marker in (row.get(f) or "").upper() for f in DNC_FIELDS)


def load_exports(repo: Path, rels: list[str]) -> list[Export]:
    """The export CSVs of a snapshot (architecture, structural, MEP; other files ignored)."""
    order = {d: i for i, (d, _) in enumerate(EXPORT_SUFFIXES)}
    found = []
    for rel in rels:
        discipline = discipline_of(rel)
        path = repo / rel
        if discipline is None or not path.is_file():
            continue
        found.append((order[discipline], rel, discipline, load_csv_file(str(path))))
    found.sort(key=lambda x: x[0])  # stable: the first export of a discipline stays first
    return [Export(rel, discipline, rows) for _, rel, discipline, rows in found]


def _tvd_view_count(exports: list[Export]) -> int:
    """Rows TVD counts: architecture + structural exports, joined per discipline, deduplicated."""
    sub = [e for e in exports if e.discipline in (ARCHITECTURE, STRUCTURAL)]
    return sum(len(rows) for rows in deduplicate(sub).kept)


def element_rows(snapshot_id: str, exports: list[Export]) -> tuple[list[tuple], dict]:
    """Deduplicated element rows (D15) as table rows, and a dedup report."""
    result = deduplicate(exports)
    rows = []
    for export, kept in zip(result.exports, result.kept, strict=True):
        for row in kept:
            issues = 0
            values = []
            for column, kind in (("Area", AREA), ("Length", LENGTH), ("Volume", VOLUME)):
                parsed = parse_quantity(row.get(column), kind)
                # metric_converted values are counted; every other issue reads as 0
                issues += parsed.issue not in (None, "metric_converted")
                values.append(parsed.value)
            area, length, volume = values
            category = effective_category(row)
            rows.append((
                snapshot_id, (row.get("ElementId") or "").strip(), export.label,
                export.discipline, category, (row.get("Family") or "").strip(),
                (row.get("Type") or "").strip(), (row.get("Level") or "").strip(),
                (row.get("Mark") or "").strip(), (row.get("Assembly Code") or "").strip(),
                (row.get("Material") or "").strip(), int(is_part(row)), int(_is_dnc(row)),
                area, length, volume, issues,
            ))
    report = {"rows_in": sum(len(e.rows) for e in exports), "rows_kept": len(rows),
              "dropped": len(result.dropped), "by_reason": result.counts()}
    return rows, report


# --------------------------------------------------------------------------- quality


def _pct(part: float, total: float) -> float | None:
    return None if not total else round(100.0 * part / total, 2)


def _quality(sid: str, tvd: dict, stv: dict | None, el_rows: list[tuple] | None,
             dedup_report: dict | None) -> list[tuple]:
    out: list[tuple] = []

    def add(scope, metric, value=None, total=None, detail=None, pct=True):
        out.append((sid, scope, metric, _num(value), _num(total),
                    _pct(value, total) if pct and value is not None and total else None,
                    None if detail is None else json.dumps(detail, separators=(",", ":"))))

    meta = tvd.get("meta", {})
    counted = (meta.get("total_elements") or 0) - (meta.get("dnc_count") or 0)
    add("tvd", "unmapped_elements", meta.get("unmapped_count", 0), counted,
        {"note": "elements without an Assembly Code, excluded categories not counted; the "
                 "denominator is total_elements minus DNC rows"})
    add("tvd", "dnc_elements", meta.get("dnc_count", 0), meta.get("total_elements"))
    add("tvd", "duplicates_removed", meta.get("duplicates_removed", 0),
        (meta.get("total_elements") or 0) + (meta.get("duplicates_removed") or 0))
    cdb = tvd.get("cost_db_validation") or {}
    lines = sum(len(v) for v in tvd.get("line_items", {}).values())
    add("tvd", "unpriced_line_items", len(cdb.get("unpriced", [])), lines,
        {"rows": [f"{u.get('cluster')}/{u.get('assembly_code')}"
                  for u in cdb.get("unpriced", [])[:20]]})
    add("tvd", "not_rated_reliability", sum((cdb.get("not_rated") or {}).values()), None,
        cdb.get("not_rated"), pct=False)
    qpw = tvd.get("quantity_parse_warnings") or {}
    add("tvd", "quantity_parse_issues", qpw.get("total", 0), None,
        {"parser": qpw.get("parser"),
         "columns": {c: v.get("by_issue") for c, v in (qpw.get("columns") or {}).items()}},
        pct=False)
    tc = tvd.get("target_consistency") or {}
    if tc:
        add("tvd", "target_consistency", None, None, {"status": tc.get("status")})

    if stv is None:
        add("stv", "present", 0, None, pct=False)
    else:
        cov = (stv.get("mapping_coverage") or {}).get("total") or {}
        counts = cov.get("elements") or {}
        if counts:
            total = counts.get("total")
            add("stv", "unmapped_elements", counts.get("unmapped", 0), total)
            add("stv", "zero_quantity_elements", counts.get("zero_quantity", 0), total)
            add("stv", "mapped_elements", counts.get("mapped", 0), total)
            add("stv", "estimated_kgco2e", cov.get("estimated_kgco2e"), cov.get("kgco2e"))
        flags = stv.get("data_flags") or {}
        add("stv", "custom_material", int(bool(flags.get("custom_material"))), None,
            {"share_of_embodied": (flags.get("custom_materials") or {}).get("share_of_embodied")},
            pct=False)
        add("stv", "proxy", int(bool(flags.get("proxy"))), None,
            {"share_of_embodied": (flags.get("proxies") or {}).get("share_of_embodied")},
            pct=False)
        status = stv.get("use_phase_status") or {}
        add("stv", "use_phase_modeled", int(bool(status.get("modeled"))), None,
            {"reason": status.get("not_modeled_reason")}, pct=False)
        add("stv", "dnc_rows_counted", len(stv.get("dnc_rows") or []), None, pct=False)

    if el_rows is not None:
        # columns of the elements row tuple: see element_rows()
        live = [r for r in el_rows if not r[12]]
        add("elements", "rows", len(el_rows), None, dedup_report, pct=False)
        for label, picker in (("missing_level", lambda r: not r[7]),
                              ("missing_material", lambda r: not r[10]),
                              ("no_quantity", lambda r: not (r[13] or r[14] or r[15])),
                              ("quantity_unreadable", lambda r: r[16] > 0)):
            hits = [r for r in live if picker(r)]
            top = Counter(r[4] for r in hits).most_common(5)
            add("elements", label, len(hits), len(live), {"top_categories": dict(top)})
        tvd_rows = [r for r in live if r[3] in (ARCHITECTURE, STRUCTURAL)
                    and r[4] not in EXCLUDE_CATEGORIES]
        no_ac = [r for r in tvd_rows if not r[9]]
        add("elements", "missing_assembly_code", len(no_ac), len(tvd_rows),
            {"top_categories": dict(Counter(r[4] for r in no_ac).most_common(5)),
             "scope": "architecture + structural, no DNC rows, no excluded categories"})
    return out


# --------------------------------------------------------------------------- tables


def _quantity_summary(sid: str, el_rows: list[tuple]) -> list[tuple]:
    acc: dict[tuple, list[float]] = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
    for r in el_rows:
        if r[12]:  # DNC
            continue
        a = acc[(r[4], r[7], r[9])]
        a[0] += 1
        a[1] += r[13]
        a[2] += r[14]
        a[3] += r[15]
    return [(sid, cat, level, ac, int(n), round(area, 4), round(length, 4), round(vol, 4))
            for (cat, level, ac), (n, area, length, vol) in sorted(acc.items())]


def _insert(conn: sqlite3.Connection, table: str, rows: list[tuple]) -> None:
    if rows:
        marks = ",".join("?" * len(rows[0]))
        conn.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)


def _tvd_tables(sid: str, tvd: dict) -> tuple[list[tuple], list[tuple]]:
    lines, line_no = [], 0
    for cluster, items in tvd.get("line_items", {}).items():
        for it in items:
            line_no += 1
            lines.append((sid, line_no, cluster, it.get("ac") or "", it.get("group"),
                          it.get("desc"), it.get("unit"), _num(it.get("unit_cost")),
                          _num(it.get("qty")), it.get("qty_src"), float(it.get("total") or 0),
                          it.get("notes") if isinstance(it.get("notes"), str)
                          else json.dumps(it.get("notes"))))
    per_cluster = Counter(row[2] for row in lines)
    grand = float((tvd.get("financials") or {}).get("grand_total") or 0)
    clusters = [(sid, c["cluster"], c["estimate"], c["target"], c["delta"], c.get("delta_pct"),
                 c.get("per_sf"), None if not grand else round(c["estimate"] / grand, 6),
                 per_cluster.get(c["cluster"], 0))
                for c in tvd.get("cluster_summary", [])]
    return lines, clusters


def _unit(material_type: str) -> str | None:
    m = _UNIT_RE.search(material_type)
    return m.group(1).strip().lower() if m else None


def _stv_tables(sid: str, stv: dict) -> tuple[list[tuple], list[tuple]]:
    items = []
    for n, it in enumerate(stv.get("construction_items", []), 1):
        emb, amount = it.get("embodied_total") or {}, float(it.get("amount") or 0)
        carbon = float(emb.get("carbon") or 0)
        items.append((
            sid, n, it["assembly"], it["material_type"], _unit(it["material_type"]), amount,
            carbon, float(emb.get("energy") or 0), float(emb.get("water") or 0),
            float(emb.get("ozone") or 0),
            float((it.get("materials") or {}).get("carbon") or 0),
            float((it.get("transport") or {}).get("carbon") or 0),
            float((it.get("construction") or {}).get("carbon") or 0),
            carbon / amount if amount else None,
            float(it.get("estimated_amount") or 0), float(it.get("proxy_amount") or 0),
            int(bool(it.get("custom_material"))), it.get("custom_material_source"),
            it.get("origin"),
        ))
    bd = stv.get("breakdown") or {}
    summary = []
    for metric, vals in (stv.get("metric_summary") or {}).items():
        def part(name, metric=metric):
            return _num((bd.get(name) or {}).get(metric))
        summary.append((
            sid, metric, _num(vals.get("target")), _num(vals.get("project")),
            _num(vals.get("percent_of_target")), part("embodied"), part("embodied_materials"),
            part("embodied_transport"), part("embodied_construction"), part("use_phase"),
            part("use_electricity"), part("use_heating"), part("use_water"),
        ))
    return items, summary


def ingest_snapshot(conn: sqlite3.Connection, repo: Path, entry: dict, *,
                    force: bool = False) -> str:
    """Load one ``results/index.json`` entry. Returns ``'ingested'`` or ``'exists'``."""
    sid = entry["id"]
    if conn.execute("SELECT 1 FROM snapshots WHERE snapshot_id=?", (sid,)).fetchone():
        if not force:
            return "exists"
        delete_snapshot(conn, sid)
    paths = entry.get("paths") or {}
    tvd = _read_json(repo, paths.get("tvd_results"))
    if tvd is None:
        raise IngestError(f"snapshot {sid}: no tvd_results in results/{INDEX_NAME}.")
    stv = _read_json(repo, paths.get("stv_results"))
    meta = tvd.get("meta", {})

    exports = load_exports(repo, entry.get("exports") or [])
    el_rows: list[tuple] | None = None
    dedup_report = None
    if not exports:
        status, note = "no_exports", "no export files found in the repo"
    else:
        counted, expected = _tvd_view_count(exports), meta.get("total_elements")
        if expected is not None and counted != expected:
            status = "stale"
            note = (f"the exports in the repo give {counted} counted architecture + "
                    f"structural rows, the TVD run counted {expected}: the exports changed "
                    "after this snapshot, so no element data is attached to it")
        else:
            status, note = "loaded", None
            el_rows, dedup_report = element_rows(sid, exports)

    lines, clusters = _tvd_tables(sid, tvd)
    items, stv_summary = _stv_tables(sid, stv) if stv else ([], [])
    quality = _quality(sid, tvd, stv, el_rows, dedup_report)
    if status != "loaded":
        quality.append((sid, "elements", "status", None, None, None,
                        json.dumps({"status": status, "note": note})))
    qsum = _quantity_summary(sid, el_rows) if el_rows is not None else []

    fin, flags = tvd.get("financials", {}), (stv or {}).get("data_flags") or {}
    carbon = ((stv or {}).get("metric_summary") or {}).get("carbon") or {}
    embodied = ((stv or {}).get("breakdown") or {}).get("embodied") or {}
    use = (stv or {}).get("use_phase_status") or {}
    summary = summaries.build(sid, entry, tvd, stv, clusters, items, qsum, quality, status)
    summary_json = json.dumps(summary, separators=(",", ":"), ensure_ascii=False)

    _insert(conn, "snapshots", [(
        sid, entry.get("timestamp") or "", entry.get("commit"), entry.get("label"),
        entry.get("label_source"), meta.get("project_name") or "", meta.get("team_name") or "",
        _num(meta.get("gross_sf")), _num(fin.get("grand_total")), _num(fin.get("tvd_target")),
        fin.get("status"), int(stv is not None), entry.get("stv_note"),
        _num(carbon.get("project")), _num(carbon.get("target")), _num(embodied.get("carbon")),
        None if stv is None else int(bool(use.get("modeled"))),
        None if stv is None else int(bool(flags.get("custom_material"))),
        None if stv is None else int(bool(flags.get("proxy"))),
        status, note, summary_json, datetime.now(UTC).isoformat(timespec="seconds"),
    )])
    if el_rows:
        _insert(conn, "elements", [r for r in el_rows])
    _insert(conn, "quantity_summary", qsum)
    _insert(conn, "tvd_line_items", lines)
    _insert(conn, "tvd_clusters", clusters)
    _insert(conn, "stv_items", items)
    _insert(conn, "stv_summary", stv_summary)
    _insert(conn, "data_quality", quality)
    return "ingested"


def delete_snapshot(conn: sqlite3.Connection, sid: str) -> None:
    for table in schema.TABLES:
        if table != "meta":
            conn.execute(f"DELETE FROM {table} WHERE snapshot_id=?", (sid,))


def ingest_repo(repo: Path, db_path: Path | None = None, *, snapshot: str | None = None,
                force: bool = False) -> dict:
    """Ingest the snapshots of ``repo`` that are not in the database yet (all of them, or only
    ``snapshot``). Returns ``{db, schema_version, ingested, existing, latest}``."""
    repo = Path(repo)
    index = load_index(repo)
    db_path = Path(db_path) if db_path else default_db_path(repo)
    entries = index["snapshots"]
    if snapshot is not None:
        entries = [e for e in entries if e["id"] == snapshot]
        if not entries:
            raise IngestError(f"snapshot {snapshot!r} is not in results/{INDEX_NAME}.")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = schema.connect(str(db_path))
    try:
        schema.create(conn)
        done, existing = [], []
        for entry in entries:
            outcome = ingest_snapshot(conn, repo, entry, force=force)
            (done if outcome == "ingested" else existing).append(entry["id"])
        latest = index.get("latest") or (index["snapshots"][-1]["id"]
                                         if index["snapshots"] else None)
        if latest:
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('latest', ?)", (latest,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"db": str(db_path), "schema_version": SCHEMA_VERSION, "ingested": done,
            "existing": existing, "latest": latest}
