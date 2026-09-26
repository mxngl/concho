"""QTO loading: read CSV exports and merge/deduplicate them by ElementId."""

import csv
import io
import os
import re


def _read_local(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _fix_bom(fieldnames):
    """Strip UTF-8 BOM artefacts from column names."""
    return [f.replace("ï»¿", "").replace("﻿", "") for f in fieldnames]


def parse_qty_str(val: str) -> float:
    """Parse quantity strings like '6590 SF', '136\\' - 0\\"', '42.75 CF'."""
    if not val or not val.strip():
        return 0.0
    ft_in = re.match(r"(-?\d+)'\s*-\s*(\d+(?:\.\d+)?)\s*\"", val.strip())
    if ft_in:
        return float(ft_in.group(1)) + float(ft_in.group(2)) / 12
    m = re.search(r"(-?\d[\d,]*\.?\d*)", val.replace(",", ""))
    return float(m.group(1)) if m else 0.0


def load_csv_text(text: str) -> list[dict]:
    """Parse CSV text into a list of dicts with BOM-cleaned column names."""
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    fixed = _fix_bom(fields)
    rows = []
    for row in reader:
        rows.append({fixed[i]: row.get(fields[i], "") for i in range(len(fields))})
    return rows


def load_csv_file(path: str) -> list[dict]:
    """Read a local CSV file and parse it with :func:`load_csv_text`."""
    return load_csv_text(_read_local(path))


def source_label(path: str) -> str:
    """Provenance label for a file: cwd-relative with forward slashes, never absolute.

    Files outside the working directory are reported by file name only, so no
    local user paths end up in the results JSON.
    """
    try:
        rel = os.path.relpath(os.path.abspath(path))
    except ValueError:  # different drive on Windows
        rel = os.path.basename(path)
    if rel.startswith(".."):
        rel = os.path.basename(path)
    return rel.replace(os.sep, "/")


def load_inputs(arch_path: str, struct_path: str, cost_path: str):
    """Read the two QTO exports and the cost DB from explicit local paths.

    Returns ``(arch_rows, struct_rows, cost_rows, source_label)``.
    """
    parts = [
        f"arch={source_label(arch_path)}",
        f"struct={source_label(struct_path)}",
        f"cost={source_label(cost_path)}",
    ]
    source = "Custom files — " + ", ".join(parts)
    print(f"Loaded data from custom paths: {', '.join(parts)}")
    return (
        load_csv_file(arch_path),
        load_csv_file(struct_path),
        load_csv_file(cost_path),
        source,
    )


def merge_takeoffs(arch: list[dict], struct: list[dict]) -> list[dict]:
    """
    Merge architectural and structural takeoffs by ElementId (no duplicates).
    Structural rows override architectural where ElementId matches.
    """
    combined: dict[str, dict] = {}
    for row in arch:
        combined[row["ElementId"]] = row
    for row in struct:
        combined[row["ElementId"]] = row  # struct wins on overlap
    return list(combined.values())
