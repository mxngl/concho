"""QTO loading: read CSV exports and merge/deduplicate them (P3.9 rule, D15)."""

import csv
import io
import os
import re

from engines.common.dedup import ARCHITECTURE, STRUCTURAL, DedupResult, Export, deduplicate


def _read_local(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _fix_bom(fieldnames):
    """Strip UTF-8 BOM artefacts from column names."""
    return [f.replace("ï»¿", "").replace("﻿", "") for f in fieldnames]


def parse_qty_str(val: str) -> float:
    """AutoTVD's quantity parser, kept as the **legacy** mode (``--legacy-length-parsing``).

    Parses '6590 SF', '136\\' - 0\\"', '42.75 CF', but reads '9\\' - 7 3/4"' as 9 ft (the
    fraction is not matched, so it falls back to the first number). The engine default is
    :func:`engines.common.quantities.parse_quantity` (P3.11).
    """
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


def merge_takeoffs(
    arch: list[dict], struct: list[dict], *, arch_label: str = "arch", struct_label: str = "struct"
) -> DedupResult:
    """Merge the architecture and structural takeoffs with the shared rule of P3.9 / D15
    (:mod:`engines.common.dedup`): Parts over their host, then one row per ElementId (with
    Assembly Code > export of the owning discipline). ``.kept_rows`` are the rows to count,
    ``.block()`` is the ``deduplication`` block of the results JSON.

    Before P3.9 the structural row always won; the AutoTVD reference exports have no
    ElementId in both files, so the Island results are unchanged (docs/engines/tvd.md).
    """
    return deduplicate([
        Export(arch_label, ARCHITECTURE, arch),
        Export(struct_label, STRUCTURAL, struct),
    ])
