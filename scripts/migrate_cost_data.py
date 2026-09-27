"""Convert an old AutoTVD ``cost_data.csv`` into the ``cost_db.csv`` format (P3.4).

The TVD engine reads only ``cost_db.csv``; the old format (German/US number formats, fixed
quantity column, rules hardcoded in the engine) is supported here and nowhere else.

    python scripts/migrate_cost_data.py OLD_cost_data.csv NEW_cost_db.csv [--config FILE]

What it does, row by row (same order as the old engine's rule priority, so the TVD results
stay identical):

- ``Total O&P`` → ``unit_cost`` as a plain decimal (``$6.184,22`` → ``6184.22``);
- ``Fixed Quantity`` set → ``fixed`` with that quantity (e.g. the Island GC and contingency
  lump sums: unit cost × 1, exact old amounts);
- ``C1030`` → ``count_codes:D2010`` (old ``TOILET_ACS``);
- clusters outside A-C without a fixed quantity → ``fixed`` without quantity (0);
- old ``QUANTITY_MIRRORS`` codes → ``mirror:<AC>``;
- everything else → ``takeoff``; sub-codes of the old ``AC_KEYWORD_SPLIT`` get their
  ``split_keywords``;
- ``qty_label`` keeps the old wording where the engine's generic label differs
  (``Toilet elements (D2010)``, ``Fixed only (none set)``);
- the legacy cluster spelling ``Special Contruction`` becomes ``Special Construction``.

Codes are kept as they are, including the Island D5030/D5090 mislabels (D5030 used for fire
protection, D5090 for HVAC); they are listed as warnings. The converted file is validated;
exit code 1 on conversion or validation errors.

The Island ``cost_data.csv`` is RSMeans-derived: never commit it or a converted copy. Tests
convert the fetched fixture (``.fixtures/``) into a temporary folder.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engines.common.config import CourseCluster, validate_config_file  # noqa: E402
from engines.tvd.clusters import course_cluster, display_name  # noqa: E402
from engines.tvd.cost_db import (  # noqa: E402
    COLUMNS,
    OPTIONAL_COLUMNS,
    CostDb,
    validate_cost_db_file,
)
from engines.tvd.loading import load_csv_file  # noqa: E402

# ── Old AutoTVD engine rules (tvd_analysis.py @ island-2026-final) ────────────────────────
# Only used to convert old files; the engine reads these rules from the cost DB.

# Clusters whose lines used takeoff quantities (without a fixed quantity).
TAKEOFF_CLUSTERS = frozenset({CourseCluster.A, CourseCluster.B, CourseCluster.C})
# Finish quantity mirrors: cost AC → source takeoff AC (area).
QUANTITY_MIRRORS = {"B3010": "B1020", "C3010": "C1010", "C3020": "B1010"}
# Keyword split: real AC → [(keywords, sub AC)], empty keywords = fallback.
AC_KEYWORD_SPLIT = {
    "B2010": [
        (["storefront", "curtain wall", "curtain", "glazing"], "B2010.CW"),
        ([], "B2010.PW"),
    ],
}
# C1030 toilet partitions = number of elements with these ACs (all categories).
TOILET_PARTITION_AC = "C1030"
TOILET_ACS = ("D2010",)

# Old engine labels that differ from the new generic ones → qty_label.
LABEL_TOILET = f"Toilet elements ({', '.join(sorted(TOILET_ACS))})"
LABEL_NO_FIXED = "Fixed only (none set)"
AREA_UNITS = {"SF", "GSF"}

SOURCE_NOTE = "migrated from AutoTVD cost_data.csv"
OLD_DESC, OLD_UNIT = "Description             ", "Unit             "  # 13 trailing spaces


def parse_cost(val: str) -> tuple[float | None, str]:
    """Old ``Total O&P`` → (value, plain decimal text); ('', None) if blank or unparsable.

    EU: period = thousands separator, comma = decimal (``"6.251,07"`` → 6251.07);
    US: comma = thousands separator, period = decimal (``"1,000.00"`` → 1000.00); the
    format is detected by which separator appears last (as in AutoTVD).
    """
    if not val or not val.strip():
        return None, ""
    v = val.strip().replace("$", "").replace(" ", "")
    if "," in v and "." in v:
        if v.rfind(",") > v.rfind("."):   # EU: comma is the decimal separator
            v = v.replace(".", "").replace(",", ".")
        else:                              # US: period is the decimal separator
            v = v.replace(",", "")
    elif "," in v:                         # EU with no thousands sep: "25,00"
        v = v.replace(",", ".")
    try:
        return float(v), v
    except ValueError:
        return None, ""


@dataclass
class Migration:
    rows: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _split_keywords(ac: str) -> str:
    for rules in AC_KEYWORD_SPLIT.values():
        for keywords, sub in rules:
            if sub == ac:
                return "|".join(keywords) if keywords else "*"
    return ""


def convert_rows(old_rows: list[dict[str, str]]) -> Migration:
    """Convert parsed old rows (AutoTVD column names) to cost_db.csv rows."""
    out = Migration()
    for i, row in enumerate(old_rows):
        n = i + 2  # CSV row number (header = 1)
        ac = row.get("Assembly Code", "").strip()
        if not ac:
            continue
        label = row.get("Cluster Name", "").strip()
        cluster = display_name(label)
        if cluster != label:
            out.warnings.append(f"row {n} ({ac}): cluster '{label}' written as '{cluster}'.")
        cost_raw = row.get("Total O&P", "")
        cost, cost_text = parse_cost(cost_raw)
        if cost is None and cost_raw.strip():
            out.errors.append(f"row {n} ({ac}): Total O&P '{cost_raw}' is not a number.")
        fq_raw = row.get("Fixed Quantity", "").strip()
        unit = row.get(OLD_UNIT, "").strip()

        qty_label, value, keywords = "", "", _split_keywords(ac)
        if fq_raw:
            try:
                float(fq_raw)
            except ValueError:
                out.errors.append(f"row {n} ({ac}): Fixed Quantity '{fq_raw}' is not a number.")
            rule, value = "fixed", fq_raw
        elif ac == TOILET_PARTITION_AC:
            rule, qty_label = f"count_codes:{','.join(TOILET_ACS)}", LABEL_TOILET
        elif course_cluster(cluster) not in TAKEOFF_CLUSTERS:
            rule, qty_label = "fixed", LABEL_NO_FIXED
        elif ac in QUANTITY_MIRRORS:
            rule = f"mirror:{QUANTITY_MIRRORS[ac]}"
            if unit.upper() not in AREA_UNITS:
                out.warnings.append(
                    f"row {n} ({ac}): the old engine mirrored the area of "
                    f"{QUANTITY_MIRRORS[ac]} for unit '{unit}'; mirror now uses the unit "
                    "(results may differ)."
                )
        else:
            rule = "takeoff"

        out.rows.append({
            "cluster": cluster,
            "assembly_code": ac,
            "group": row.get("Assembly Group Name", "").strip(),
            "description": row.get(OLD_DESC, "").strip(),
            "unit": unit,
            "unit_cost": cost_text,
            "quantity_rule": rule,
            "quantity_value": value,
            "qty_reliability": "",
            "cost_reliability": "",
            "source": SOURCE_NOTE,
            "split_keywords": keywords,
            "qty_label": qty_label,
        })
    return out


def write_cost_db(path: Path | str, rows: list[dict[str, str]]) -> None:
    columns = [*COLUMNS, *OPTIONAL_COLUMNS]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def migrate(
    old_path: Path | str, new_path: Path | str, *, custom_clusters: list[str] | None = None
) -> tuple[Migration, CostDb | None]:
    """Convert ``old_path`` to ``new_path`` and validate the result.

    Returns the conversion result and the validation of the new file (None if the
    conversion failed and nothing was written).
    """
    migration = convert_rows(load_csv_file(str(old_path)))
    if migration.errors:
        return migration, None
    write_cost_db(new_path, migration.rows)
    return migration, validate_cost_db_file(new_path, custom_clusters=custom_clusters)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old", help="old AutoTVD cost_data.csv")
    parser.add_argument("new", help="cost_db.csv to write")
    parser.add_argument("--config", metavar="FILE",
                        help="project_config: its tvd.custom_clusters are allowed clusters")
    args = parser.parse_args(argv)

    custom = None
    if args.config:
        report = validate_config_file(args.config)
        if not report.ok:
            print(f"error: invalid project_config {args.config}", file=sys.stderr)
            return 1
        custom = [c.name for c in report.config.tvd.custom_clusters]

    migration, db = migrate(args.old, args.new, custom_clusters=custom)
    for msg in migration.errors:
        print(f"error: {msg}")
    for msg in migration.warnings:
        print(f"migration warning: {msg}")
    if db is None:
        print(f"FAILED: {args.old} not converted ({len(migration.errors)} errors).")
        return 1
    print(f"Converted {len(migration.rows)} rows: {args.old} -> {args.new}")

    if db.mislabels:
        print(f"\nMislabelled codes (kept as they are, {len(db.mislabels)}):")
        for m in db.mislabels:
            print(f"  row {m['row']}: {m['assembly_code']} '{m['description']}': "
                  f"{m['assembly_code']} is {m['code_title']} ({m['code_group']}); the "
                  f"description points to {m['suggested_group']} {m['suggested_title']}")

    print(f"\nValidation of {args.new}:")
    for msg in db.errors:
        print(f"error: {msg}")
    for msg in db.warnings:
        print(f"warning: {msg}")
    print(f"{len(db.errors)} errors, {len(db.warnings)} warnings.")
    return 0 if db.ok else 1


if __name__ == "__main__":
    sys.exit(main())
