"""INVENTED data for the data-API tests (P5.3/P5.4): a team repo with ``results/`` and
``exports/`` in the format the pipeline writes (docs/pipeline.md). No Island data, no RSMeans,
no course data: every name and number here is made up."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ARCH_HEADER = ("ElementId,Category,Family,Type,Level,Mark,Assembly Code,Assembly Description,"
               "Length,Width,Height,Area,Volume,Material,Comments,Part Source Id,Original Category")
MEP_HEADER = "ElementId,Category,Family,Type,Level,Size,Length,Material,Weight,Assembly Code"

# id 8 carries the DNC marker; id 12 is the host of Part 11; id 5 is also in the structural
# export (Floors: structural owns them); id 9 is also in the MEP export (MEP owns plumbing).
ARCH = [
    "1,Walls,Basic Wall,Partition,L1,,C1010,Partitions,40,0.5,10,400,200,Gypsum,,,",
    "2,Walls,Basic Wall,Partition,L2,,C1010,Partitions,20,0.5,10,200,100,Gypsum,,,",
    "3,Walls,Basic Wall,Facade,L1,,B2010,Exterior Walls,30,1,10,300,300,Brick,,,",
    "4,Roofs,Basic Roof,Flat,L3,,B3010,Roofing,,,,1000,500,Membrane,,,",
    "5,Floors,Floor,Slab,L1,,B1010,Floor Construction,,,,900,450,Concrete,,,",
    "6,Furniture,Chair,Std,L1,,,,,,,10,1,Wood,,,",
    "7,Doors,Door,Single,L1,,,,,,,21,,Wood,,,",
    "8,Walls,Basic Wall,Partition,L1,,C1010,Partitions,10,0.5,10,100,50,Gypsum,DNC,,",
    "9,Plumbing Fixtures,Toilet,Std,L1,,D2010,Plumbing Fixtures,,,,,,Ceramic,,,",
    "12,Floors,Floor,Slab with Parts,L2,,B1010,Floor Construction,,,,500,250,Concrete,,,",
]
STRUCT = [
    "5,Floors,Floor,Slab,L1,,B1010,Floor Construction,,,,900,450,Concrete,,,",
    "10,Structural Columns,Column,Rect,L1,,B1010,Floor Construction,12,,,,24,Concrete,,,",
    "11,Parts,,,L2,,B1010,Floor Construction,,,,500,250,Concrete,,12,Floors",
]
MEP = [
    "9,Plumbing Fixtures,Toilet,Std,L1,,,Ceramic,,D2010",
    "13,Pipes,Pipe,Copper,L1,1\",20' - 0\",Copper,12,D2000",
]
# Counted rows after the D15 rule: arch+struct = 11 (TVD view), all three exports = 12.
TVD_TOTAL_ELEMENTS = 11
ELEMENT_ROWS = 12
LINE_ITEMS = {
    "Substructure": [
        {"ac": "A1010", "group": "Foundations", "desc": "Pad footing", "unit": "CF",
         "unit_cost": 20.0, "qty": 100.0, "qty_src": "Volume (CF)", "total": 2000.0,
         "notes": ""},
    ],
    "Shell": [
        {"ac": "B1010", "group": "Floors", "desc": "Slab", "unit": "SF", "unit_cost": 15.0,
         "qty": 1400.0, "qty_src": "Area (SF)", "total": 21000.0, "notes": ""},
        {"ac": "B2010", "group": "Exterior Walls", "desc": "Facade", "unit": "SF",
         "unit_cost": 40.0, "qty": 300.0, "qty_src": "Area (SF)", "total": 12000.0,
         "notes": ""},
        {"ac": "B3010", "group": "Roofing", "desc": "Flat roof", "unit": "SF",
         "unit_cost": 30.0, "qty": 1000.0, "qty_src": "Area (SF)", "total": 30000.0,
         "notes": ""},
    ],
    "Interiors": [
        {"ac": "C1010", "group": "Partitions", "desc": "Partition", "unit": "SF",
         "unit_cost": 10.0, "qty": 600.0, "qty_src": "Area (SF)", "total": 6000.0,
         "notes": ""},
    ],
    "General Conditions": [
        {"ac": "H4000", "group": "GC", "desc": "Site overhead", "unit": "LS",
         "unit_cost": 1000.0, "qty": 1.0, "qty_src": "Fixed", "total": 1000.0, "notes": ""},
        {"ac": "H5000", "group": "Contingency", "desc": "Contingency 10 %", "unit": "%",
         "unit_cost": 720.0, "qty": 10.0, "qty_src": "10 % of subtotal", "total": 7200.0,
         "notes": ""},
    ],
}
GRAND_TOTAL = 79200.0  # 2000 + 21000 + 12000 + 30000 + 6000 + 1000 + 7200
TARGET = 80000.0


def tvd_payload(*, line_items=None, total_elements=TVD_TOTAL_ELEMENTS) -> dict:
    items = copy.deepcopy(line_items or LINE_ITEMS)
    clusters = []
    for name, lines in items.items():
        est = sum(line["total"] for line in lines)
        clusters.append({"cluster": name, "estimate": est, "target": est * 1.1,
                         "delta": est - est * 1.1, "delta_pct": -9.09,
                         "per_sf": round(est / 2000, 2)})
    total = sum(c["estimate"] for c in clusters)
    return {
        "meta": {"generated_at": "2027-01-17T09:30:00", "date": "2027-01-17",
                 "label": "Run", "project_name": "Demo Hall", "team_name": "Demo Team",
                 "data_source": "exports", "gross_sf": 2000, "total_elements": total_elements,
                 "duplicates_removed": 3, "unmapped_count": 1, "dnc_count": 1},
        "financials": {"grand_total": total, "tvd_target": TARGET, "delta": total - TARGET,
                       "delta_pct": round((total - TARGET) / TARGET * 100, 2),
                       "cost_per_sf": round(total / 2000, 2),
                       "status": "under_target" if total < TARGET else "over_target"},
        "cluster_targets": {c["cluster"]: c["target"] for c in clusters},
        "cluster_summary": clusters,
        "cost_db_validation": {"status": "warnings", "rows": 7, "error_count": 0,
                               "warning_count": 1, "warnings": ["x"],
                               "unpriced": [{"row": 9, "cluster": "Shell",
                                             "assembly_code": "B1020"}],
                               "not_rated": {"qty_reliability": 2, "cost_reliability": 3}},
        "quantity_parse_warnings": {"parser": "tolerant", "total": 0, "columns": {}},
        "line_items": items,
    }


def _vec(carbon, energy=0.0, water=0.0, ozone=0.0) -> dict:
    return {"carbon": carbon, "energy": energy, "water": water, "ozone": ozone}


def stv_item(assembly, material, amount, per_unit, *, custom=False, proxy=0.0,
             estimated=0.0) -> dict:
    total = amount * per_unit
    return {"assembly": assembly, "material_type": material, "amount": amount,
            "unit_multiplier": 1.0, "embodied_total": _vec(total, total * 10, total * 3, 1e-6),
            "materials": _vec(total * 0.7), "transport": _vec(total * 0.1),
            "construction": _vec(total * 0.2), "estimated": estimated > 0,
            "estimated_amount": estimated, "custom_material": custom,
            "custom_material_source": "invented EPD" if custom else None,
            "proxy": proxy > 0, "proxy_amount": proxy, "origin": "input"}


STV_ITEMS = [
    stv_item("Floor", "Concrete (sf)", 1400.0, 5.0),
    stv_item("Floor", "Timber (sf)", 100.0, 2.0),
    stv_item("Exterior Wall", "Brick (sf)", 300.0, 8.0),
    stv_item("Roof", "Membrane (sf)", 1000.0, 1.5, proxy=1000.0),
    stv_item("Columns", "Bio Column (kg)", 500.0, 0.4, custom=True),
]


def stv_payload(items=None, *, use_phase_modeled=False) -> dict:
    items = copy.deepcopy(items if items is not None else STV_ITEMS)
    embodied = sum(i["embodied_total"]["carbon"] for i in items)
    use = 100000.0 if use_phase_modeled else 0.0
    target = 50000.0
    life = embodied + use
    return {
        "team": "Demo", "targets": _vec(target, 1e6, 1e6), "lifetime_years": 50,
        "metric_summary": {"carbon": {"target": target, "project": life,
                                      "percent_of_target": life / target},
                           "energy": {"target": 1e6, "project": life * 10,
                                      "percent_of_target": life * 10 / 1e6}},
        "breakdown": {
            "embodied_materials": _vec(embodied * 0.7), "embodied_transport": _vec(embodied * 0.1),
            "embodied_construction": _vec(embodied * 0.2), "use_electricity": _vec(use),
            "use_heating": _vec(0.0), "use_water": _vec(0.0),
            "embodied": _vec(embodied, embodied * 10), "use_phase": _vec(use),
            "life_cycle": _vec(life, life * 10)},
        "construction_items": items,
        "data_flags": {"custom_material": any(i["custom_material"] for i in items),
                       "proxy": any(i["proxy_amount"] > 0 for i in items)},
        "use_phase_status": {"modeled": use_phase_modeled, "source": "project_config",
                             "not_modeled_reason": None if use_phase_modeled else "not given"},
        "mapping_coverage": {"total": {"elements": {"total": 10, "mapped": 8,
                                                    "zero_quantity": 1, "unmapped": 1,
                                                    "mapped_pct": 80.0},
                                       "kgco2e": embodied, "estimated_kgco2e": 0.0,
                                       "estimated_kgco2e_pct": 0.0}},
        "dnc_rows": [],
    }


def write_exports(repo: Path) -> list[str]:
    exports = repo / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    files = {"Demo_ARCH_Architecture_TakeOff.csv": (ARCH_HEADER, ARCH),
             "Demo_STR_Structural_Schedule.csv": (ARCH_HEADER, STRUCT),
             "Demo_MEP_MEP_TakeOff.csv": (MEP_HEADER, MEP)}
    for name, (header, rows) in files.items():
        (exports / name).write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return [f"exports/{name}" for name in files]


def add_snapshot(repo: Path, sid: str, *, tvd=None, stv="default", label="Run",
                 exports=None, timestamp=None) -> dict:
    """Write results/<sid>/ and append the entry to results/index.json."""
    results = repo / "results"
    run = results / sid
    (run / "tvd").mkdir(parents=True, exist_ok=True)
    tvd = tvd if tvd is not None else tvd_payload()
    (run / "tvd" / "tvd_results.json").write_text(json.dumps(tvd), encoding="utf-8")
    stv = stv_payload() if stv == "default" else stv
    stv_path = None
    if stv is not None:
        (run / "stv").mkdir(exist_ok=True)
        (run / "stv" / "stv_results.json").write_text(json.dumps(stv), encoding="utf-8")
        stv_path = f"results/{sid}/stv/stv_results.json"
    entry = {
        "id": sid, "timestamp": timestamp or f"{sid[:4]}-{sid[4:6]}-{sid[6:8]}T09:30:00Z",
        "commit": "a" * 40, "label": label, "label_source": "default",
        "exports": exports if exports is not None else [
            f"exports/{n}" for n in ("Demo_ARCH_Architecture_TakeOff.csv",
                                     "Demo_STR_Structural_Schedule.csv",
                                     "Demo_MEP_MEP_TakeOff.csv")],
        "paths": {"tvd_results": f"results/{sid}/tvd/tvd_results.json", "tvd_dashboard": None,
                  "stv_results": stv_path},
        "tvd": {}, "stv": None if stv is None else {}, "stv_note": None if stv else "STV skipped",
    }
    index_path = results / "index.json"
    index = (json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file()
             else {"schema": 1, "snapshots": []})
    index["snapshots"].append(entry)
    index["latest"] = sid
    index_path.write_text(json.dumps(index), encoding="utf-8")
    return entry


def make_repo(root: Path, *, snapshots=("20270117T093000Z",)) -> Path:
    write_exports(root)
    for sid in snapshots:
        add_snapshot(root, sid)
    return root


def big_tvd(n_lines: int) -> dict:
    """A results JSON with many line items (cap tests)."""
    items = {"Shell": [{"ac": f"B{i:04d}", "group": "g", "desc": f"line {i}", "unit": "SF",
                        "unit_cost": 1.0, "qty": 10.0, "qty_src": "Area (SF)", "total": 10.0 + i,
                        "notes": ""} for i in range(n_lines)]}
    return tvd_payload(line_items=items)


def big_stv(n_items: int) -> dict:
    return stv_payload([stv_item(f"Assembly {i % 7}", f"Material {i} (sf)", 100.0 + i, 1.0 + i / 10)
                        for i in range(n_items)])
