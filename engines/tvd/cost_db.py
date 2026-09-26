"""P3.4: cost DB format (``cost_db.csv``), loader and validator.

One row per cost line item. Columns (header names exact, order free):

``cluster, assembly_code, group, description, unit, unit_cost, quantity_rule,
quantity_value, qty_reliability, cost_reliability, source, split_keywords`` and the optional
``qty_label``. Numbers are plain decimals (``1670000.00``: no currency symbol, no thousands
separator, ``.`` as decimal point). Lines starting with ``#`` are comments; blank lines are
skipped. Format reference with examples: ``docs/engines/tvd.md``; JSON Schema of one row:
``docs/schema/cost_db.schema.json`` (from :class:`CostDbRow`).

``quantity_rule`` replaces the hardcoded AutoTVD rule tables (quantity mirrors, toilet codes,
keyword split, takeoff clusters):

- ``takeoff``: takeoff quantity of the row's code, by unit;
- ``fixed``: ``quantity_value`` (blank = 0);
- ``per_gsf``: ``project.gross_sf`` × ``quantity_value`` (blank = 1);
- ``pct_of_subtotal``: ``quantity_value`` % of the sum of all other lines (unit ``%``);
- ``mirror:<AC>``: the takeoff quantity of another code (or its ``fixed`` quantity);
- ``count_codes:<AC,...>``: number of takeoff elements with these codes, all categories.

``split_keywords`` on a sub-code row (``B2010.CW``) routes takeoff elements of the base code
(``B2010``) to that sub-code by keywords in Category + Family + Type (``|``-separated,
``*`` = everything not matched by another sub-code).

Usage::

    db = validate_cost_db_file("cost_db.csv", custom_clusters=["Equipment Rental"])
    db.errors, db.warnings        # messages with row numbers (header = row 1)
    db = load_cost_db("cost_db.csv")  # raises CostDbError on errors
"""

from __future__ import annotations

import csv
import difflib
import io
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from engines.common import uniformat
from engines.common.config import CLUSTER_NAMES, CourseCluster
from engines.tvd.clusters import LEGACY_CLUSTER_NAMES, course_cluster, display_name

SCHEMA_ID = "https://github.com/mxngl/concho/blob/main/docs/schema/cost_db.schema.json"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

COLUMNS: tuple[str, ...] = (
    "cluster", "assembly_code", "group", "description", "unit", "unit_cost",
    "quantity_rule", "quantity_value", "qty_reliability", "cost_reliability", "source",
    "split_keywords",
)
OPTIONAL_COLUMNS: tuple[str, ...] = ("qty_label",)

# Units the takeoff can measure: unit → (quantity field, divisor, label).
TAKEOFF_UNITS: dict[str, tuple[str, float, str]] = {
    "SF": ("area_sf", 1, "Area (SF)"),
    "GSF": ("area_sf", 1, "Area (SF)"),
    "MSF": ("area_sf", 1000, "Area/1000 (MSF)"),
    "LF": ("length_lf", 1, "Length (LF)"),
    "EA": ("count", 1, "Count (EA)"),
    "FLIGHT": ("count", 1, "Count (EA)"),
    "CY": ("volume_cf", 27, "Volume (CY)"),
    "CF": ("volume_cf", 1, "Volume (CF)"),
}
# Other known units (fixed / per_gsf quantities); "%" only for pct_of_subtotal.
OTHER_UNITS: tuple[str, ...] = (
    "SY", "STORY", "LS", "TON", "LB", "GAL", "HR", "DAY", "WEEK", "MONTH", "%",
)
KNOWN_UNITS: tuple[str, ...] = (*TAKEOFF_UNITS, *OTHER_UNITS)

PLAIN_DECIMAL = r"^[0-9]+(\.[0-9]+)?$"
_PLAIN_RE = re.compile(PLAIN_DECIMAL)
RULE_PATTERN = (
    r"^(takeoff|fixed|per_gsf|pct_of_subtotal|mirror:[A-Z][0-9]{4}(\.[A-Za-z0-9_-]+)?"
    r"|count_codes:[A-Z][0-9]{4}(\.[A-Za-z0-9_-]+)?(,[A-Z][0-9]{4}(\.[A-Za-z0-9_-]+)?)*)$"
)
FALLBACK_KEYWORD = "*"

# Description keywords that point to another D level-2 group (mislabel check, e.g. the
# Island D5030 "Fire Protection Systems" and D5090 "HVAC Systems").
DESCRIPTION_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("fire protection", "sprinkler", "standpipe"), "D40"),
    (("hvac", "heating", "ventilation", "air conditioning"), "D30"),
    (("plumbing",), "D20"),
    (("elevator", "escalator"), "D10"),
)


class Rule(StrEnum):
    TAKEOFF = "takeoff"
    FIXED = "fixed"
    PER_GSF = "per_gsf"
    PCT_OF_SUBTOTAL = "pct_of_subtotal"
    MIRROR = "mirror"
    COUNT_CODES = "count_codes"


class CostDbRow(BaseModel):
    """One cost line item (one row of ``cost_db.csv``). Team data, not course data."""

    model_config = ConfigDict(
        extra="forbid",
        title="cost_db.csv row",
        json_schema_extra={
            "$schema": SCHEMA_DIALECT,
            "$id": SCHEMA_ID,
            "x-csv-columns": [*COLUMNS, *OPTIONAL_COLUMNS],
            "x-csv-notes": (
                "One CSV row per line item. Empty cells = null / empty string. Numbers are "
                "plain decimals (pattern " + PLAIN_DECIMAL + "). Lines starting with '#' are "
                "comments. See docs/engines/tvd.md."
            ),
        },
    )

    cluster: str = Field(
        min_length=1,
        description="Course cluster letter or name (A-H, e.g. 'Shell') or a custom cluster "
                    "from tvd.custom_clusters.",
    )
    assembly_code: str = Field(
        pattern=uniformat.CODE_PATTERN,
        description="Uniformat code (engines/common/uniformat.csv, level 3, or the 4-digit "
                    "form of a level-2 code such as B2000), or a sub-code 'B2010.CW'.",
    )
    group: str = Field(default="", description="Group label (free text).")
    description: str = Field(
        default="",
        description="Line item description; required unless the row is a placeholder "
                    "(unit, unit_cost and description all empty).",
    )
    unit: str = Field(default="", description="Unit: " + ", ".join(KNOWN_UNITS) + ".")
    unit_cost: float | None = Field(
        default=None, ge=0, description="Cost per unit (plain decimal); empty = unpriced."
    )
    quantity_rule: str = Field(
        pattern=RULE_PATTERN,
        description="takeoff | fixed | per_gsf | pct_of_subtotal | mirror:<AC> | "
                    "count_codes:<AC,...>",
    )
    quantity_value: float | None = Field(
        default=None, ge=0,
        description="fixed: the quantity; per_gsf: factor per GSF (empty = 1); "
                    "pct_of_subtotal: percent (0-100]; empty for the other rules.",
    )
    qty_reliability: int | None = Field(
        default=None, ge=1, le=3,
        description="Quantity reliability 1 = low, 2 = medium, 3 = high; empty = not rated.",
    )
    cost_reliability: int | None = Field(
        default=None, ge=1, le=3,
        description="Unit cost reliability 1 = low, 2 = medium, 3 = high; empty = not rated.",
    )
    source: str = Field(default="", description="Where the unit cost comes from (free text).")
    split_keywords: str = Field(
        default="",
        description="Sub-code rows only: keywords ('|'-separated) that route takeoff "
                    "elements of the base code to this sub-code, or '*' for the rest.",
    )
    qty_label: str = Field(
        default="",
        description="Optional label for the quantity source (qty_src); empty = the "
                    "engine's generic label.",
    )

    _row: int = PrivateAttr(default=0)

    @property
    def row(self) -> int:
        """Row number in the file (header = row 1)."""
        return self._row

    @property
    def code(self) -> str:
        return self.assembly_code

    @property
    def rule(self) -> Rule:
        return Rule(self.quantity_rule.split(":", 1)[0])

    @property
    def rule_targets(self) -> tuple[str, ...]:
        """Codes named by ``mirror:``/``count_codes:`` (empty for the other rules)."""
        if ":" not in self.quantity_rule:
            return ()
        return tuple(c.strip() for c in self.quantity_rule.split(":", 1)[1].split(","))

    @property
    def keywords(self) -> list[str]:
        return _keywords(self.split_keywords)

    @property
    def is_fallback(self) -> bool:
        return self.split_keywords.strip() == FALLBACK_KEYWORD

    @property
    def is_placeholder(self) -> bool:
        return not self.unit and self.unit_cost is None and not self.description

    @property
    def display_cluster(self) -> str:
        return display_name(self.cluster)


def _keywords(spec: str) -> list[str]:
    return [k.strip().lower() for k in spec.split("|") if k.strip()]


def json_schema() -> dict[str, Any]:
    return CostDbRow.model_json_schema()


def json_schema_text() -> str:
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------


class CostDbError(ValueError):
    """Raised by :func:`load_cost_db` when the cost DB has errors."""

    def __init__(self, errors: list[str], source: str = "cost DB"):
        self.errors = errors
        super().__init__(f"invalid {source}:\n" + "\n".join(f"  - {e}" for e in errors))


@dataclass
class CostDb:
    """Parsed cost DB and its validation result (``lines`` only complete if ``ok``)."""

    lines: list[CostDbRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unpriced: list[dict] = field(default_factory=list)
    not_rated: dict[str, list[int]] = field(default_factory=dict)
    mislabels: list[dict] = field(default_factory=list)
    source: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors

    def validation_block(self) -> dict:
        """``cost_db_validation`` block of the results JSON."""
        return {
            "status": "ok" if not self.warnings else "warnings",
            "rows": len(self.lines),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "warnings": list(self.warnings),
            "unpriced": [dict(u) for u in self.unpriced],
            "not_rated": {col: len(rows) for col, rows in self.not_rated.items()},
        }


def _rows_text(rows: Iterable[int]) -> str:
    """[2, 3, 4, 7] → '2-4, 7'."""
    rows = sorted(set(rows))
    parts: list[str] = []
    start = prev = None
    for r in rows:
        if start is None:
            start = prev = r
        elif r == prev + 1:
            prev = r
        else:
            parts.append(f"{start}" if start == prev else f"{start}-{prev}")
            start = prev = r
    if start is not None:
        parts.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(parts)


def _rows_label(rows: list[int]) -> str:
    return f"row{'s' if len(set(rows)) > 1 else ''} {_rows_text(rows)}"


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _suggest_text(options: list[str]) -> str:
    return f" Did you mean {' / '.join(options)}?" if options else ""


def _parse_number(raw: str) -> tuple[float | None, str | None]:
    """Plain decimal → (value, None); blank → (None, None); else (None, error)."""
    v = raw.strip()
    if not v:
        return None, None
    if _PLAIN_RE.match(v):
        return float(v), None
    if v.startswith("-") and _PLAIN_RE.match(v[1:]):
        return None, f"'{v}' must not be negative."
    return None, (
        f"'{v}' is not a plain decimal: no currency symbol, no thousands separator, "
        "'.' as decimal point (e.g. 1670000.00)."
    )


class _Validator:
    def __init__(self, custom_clusters: Iterable[str] | None):
        self.custom = None if custom_clusters is None else {
            _norm(c): c for c in custom_clusters
        }
        self.db = CostDb()
        self._custom_rows: dict[str, list[int]] = {}

    # messages ---------------------------------------------------------------
    def err(self, row: int, code: str, col: str | None, msg: str) -> None:
        self.db.errors.append(self._fmt(row, code, col, msg))

    def warn(self, row: int, code: str, col: str | None, msg: str) -> None:
        self.db.warnings.append(self._fmt(row, code, col, msg))

    @staticmethod
    def _fmt(row: int, code: str, col: str | None, msg: str) -> str:
        where = f"row {row}" + (f" ({code})" if code else "")
        return f"{where}: {col}: {msg}" if col else f"{where}: {msg}"

    # header -----------------------------------------------------------------
    def check_header(self, header: list[str]) -> bool:
        names = [h.strip() for h in header]
        if {"Assembly Code", "Total O&P"} & set(names):
            self.db.errors.append(
                "header: this is the old AutoTVD cost_data.csv format; convert it with "
                "python scripts/migrate_cost_data.py OLD.csv NEW.csv."
            )
            return False
        ok = True
        missing = [c for c in COLUMNS if c not in names]
        if missing:
            self.db.errors.append(f"header: missing column(s): {', '.join(missing)}.")
            ok = False
        allowed = set(COLUMNS) | set(OPTIONAL_COLUMNS)
        for name in names:
            if name not in allowed:
                hint = _suggest_text(difflib.get_close_matches(name, sorted(allowed), n=1))
                self.db.errors.append(f"header: unknown column '{name}'.{hint}")
                ok = False
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            self.db.errors.append(f"header: duplicated column(s): {', '.join(dupes)}.")
            ok = False
        return ok

    # rows -------------------------------------------------------------------
    def check_row(self, row: int, rec: dict[str, str]) -> CostDbRow | None:
        n_err = len(self.db.errors)
        code = rec.get("assembly_code", "").strip()
        cluster = rec.get("cluster", "").strip()
        description = rec.get("description", "").strip()
        unit = rec.get("unit", "").strip()
        rule_raw = rec.get("quantity_rule", "").strip()

        # cluster + code
        cc = course_cluster(cluster) if cluster else None
        if not cluster:
            self.err(row, code, "cluster", "required.")
        elif cc is None:
            self._custom_cluster(row, code, cluster)
        elif _norm(cluster) in LEGACY_CLUSTER_NAMES:
            self.warn(row, code, "cluster",
                      f"legacy spelling '{cluster}', read as '{CLUSTER_NAMES[cc]}'.")
        if not code:
            self.err(row, code, "assembly_code", "required.")
        elif not uniformat.is_well_formed(code):
            self.err(row, code, "assembly_code",
                     f"'{code}' is not a code of the form A1010 or A1010.XX."
                     + _suggest_text(uniformat.suggest(code)))
        elif cc is not None:
            if uniformat.lookup(code) is None:
                self.err(row, code, "assembly_code",
                         f"'{uniformat.base_code(code)}' is not in the Uniformat reference "
                         "list (engines/common/uniformat.csv, uniformat_extensions.csv)."
                         + _suggest_text(uniformat.suggest(code)))
            elif uniformat.group_letter(code) != cc.value:
                self.err(row, code, "cluster",
                         f"'{cluster}' is cluster {cc.value}, but {code} belongs to group "
                         f"{uniformat.group_letter(code)} "
                         f"({CLUSTER_NAMES[CourseCluster(uniformat.group_letter(code))]}).")

        # placeholder / description / unit
        placeholder = not unit and not rec.get("unit_cost", "").strip() and not description
        if placeholder:
            self.warn(row, code, None,
                      "placeholder row (no description, unit or unit cost): priced 0.")
        else:
            if not description:
                self.err(row, code, "description", "required (unless the row is a "
                         "placeholder without unit and unit cost).")
            if not unit:
                self.err(row, code, "unit", "required. Known units: "
                         + ", ".join(KNOWN_UNITS) + ".")
            elif unit.upper() not in KNOWN_UNITS:
                hint = _suggest_text(difflib.get_close_matches(unit.upper(), KNOWN_UNITS, n=2))
                self.err(row, code, "unit", f"unknown unit '{unit}'.{hint} Known units: "
                         + ", ".join(KNOWN_UNITS) + ".")

        # numbers
        values: dict[str, Any] = {}
        for col in ("unit_cost", "quantity_value"):
            val, msg = _parse_number(rec.get(col, ""))
            if msg:
                self.err(row, code, col, msg)
            values[col] = val
        for col in ("qty_reliability", "cost_reliability"):
            raw = rec.get(col, "").strip()
            if not raw:
                self.db.not_rated.setdefault(col, []).append(row)
                values[col] = None
            elif raw in ("1", "2", "3"):
                values[col] = int(raw)
            else:
                self.err(row, code, col,
                         f"'{raw}' must be 1, 2 or 3 (low, medium, high), or empty.")
                values[col] = None

        # rule
        self._check_rule(row, code, rule_raw, unit, values, placeholder)

        # split keywords (syntax; consistency across rows in check_all)
        spec = rec.get("split_keywords", "").strip()
        if spec:
            if "." not in code:
                self.err(row, code, "split_keywords",
                         "only sub-code rows (e.g. B2010.CW) can have split keywords.")
            elif FALLBACK_KEYWORD in _keywords(spec) and spec != FALLBACK_KEYWORD:
                self.err(row, code, "split_keywords",
                         "'*' (everything else) cannot be combined with keywords.")

        qty_label = rec.get("qty_label", "").strip()
        if qty_label and rule_raw.split(":", 1)[0] in (Rule.TAKEOFF, Rule.MIRROR):
            self.warn(row, code, "qty_label",
                      f"'{qty_label}' replaces the outcome label of a {rule_raw} rule "
                      "(e.g. 'No takeoff match').")

        if len(self.db.errors) > n_err:
            return None
        try:
            line = CostDbRow(
                cluster=cluster, assembly_code=code, group=rec.get("group", "").strip(),
                description=description, unit=unit, unit_cost=values["unit_cost"],
                quantity_rule=rule_raw.replace(" ", ""), quantity_value=values["quantity_value"],
                qty_reliability=values["qty_reliability"],
                cost_reliability=values["cost_reliability"],
                source=rec.get("source", "").strip(), split_keywords=spec, qty_label=qty_label,
            )
        except ValidationError as exc:  # safety net; the checks above should catch it all
            for e in exc.errors(include_url=False):
                self.err(row, code, ".".join(map(str, e["loc"])), e["msg"])
            return None
        line._row = row
        return line

    def _custom_cluster(self, row: int, code: str, cluster: str) -> None:
        if self.custom is not None and _norm(cluster) not in self.custom:
            course = ", ".join(f"{c.value} {n}" for c, n in CLUSTER_NAMES.items())
            hint = _suggest_text(difflib.get_close_matches(
                cluster, [*CLUSTER_NAMES.values(), *self.custom.values()], n=1))
            self.err(row, code, "cluster",
                     f"unknown cluster '{cluster}': not a course cluster ({course}) and not "
                     f"in tvd.custom_clusters of the config.{hint}")
        else:
            self._custom_rows.setdefault(cluster, []).append(row)

    def _check_rule(self, row, code, rule_raw, unit, values, placeholder) -> None:
        col = "quantity_rule"
        if not rule_raw:
            self.err(row, code, col, "required: takeoff | fixed | per_gsf | "
                     "pct_of_subtotal | mirror:<AC> | count_codes:<AC,...>.")
            return
        kind, _, arg = rule_raw.partition(":")
        kind = kind.strip()
        try:
            rule = Rule(kind)
        except ValueError:
            hint = _suggest_text(difflib.get_close_matches(kind, [r.value for r in Rule], n=1))
            self.err(row, code, col, f"unknown rule '{rule_raw}'.{hint} Rules: takeoff, "
                     "fixed, per_gsf, pct_of_subtotal, mirror:<AC>, count_codes:<AC,...>.")
            return
        has_arg = rule in (Rule.MIRROR, Rule.COUNT_CODES)
        if has_arg and not arg.strip():
            self.err(row, code, col, f"'{kind}:' needs target code(s), e.g. "
                     f"{'mirror:C1010' if rule is Rule.MIRROR else 'count_codes:D2010'}.")
            return
        if not has_arg and ":" in rule_raw:
            self.err(row, code, col, f"'{kind}' takes no target ('{rule_raw}').")
            return
        targets = [t.strip() for t in arg.split(",")] if has_arg else []
        if rule is Rule.MIRROR and len(targets) != 1:
            self.err(row, code, col, "mirror takes exactly one code (mirror:<AC>).")
            return
        for t in targets:
            if not uniformat.is_well_formed(t):
                self.err(row, code, col, f"target '{t}' is not a code of the form A1010 or "
                         "A1010.XX." + _suggest_text(uniformat.suggest(t)))
        if rule is Rule.MIRROR and targets and targets[0] == code:
            self.err(row, code, col, "a row cannot mirror its own code.")
        if rule is Rule.COUNT_CODES and len(set(targets)) != len(targets):
            self.warn(row, code, col, "a code is listed twice (counted once).")

        qv = values["quantity_value"]
        takes_value = rule in (Rule.FIXED, Rule.PER_GSF, Rule.PCT_OF_SUBTOTAL)
        if not takes_value and qv is not None:
            self.err(row, code, "quantity_value", f"must be empty for rule {kind} (the "
                     "quantity comes from the takeoff).")
        u = unit.upper()
        if rule in (Rule.TAKEOFF, Rule.MIRROR) and u in KNOWN_UNITS and u not in TAKEOFF_UNITS:
            self.err(row, code, "unit", f"'{unit}' cannot be measured from the takeoff "
                     f"(rule {kind}); takeoff units: {', '.join(TAKEOFF_UNITS)}. Use fixed "
                     "or per_gsf.")
        if rule is Rule.FIXED and qv is None and not placeholder:
            self.warn(row, code, "quantity_value", "fixed without quantity: quantity 0.")
        if rule is Rule.PCT_OF_SUBTOTAL:
            if qv is None or not 0 < qv <= 100:
                self.err(row, code, "quantity_value",
                         "pct_of_subtotal needs a percent in (0, 100], e.g. 5 for 5 %.")
            if u != "%":
                self.err(row, code, "unit", "pct_of_subtotal needs unit '%'.")
            if values["unit_cost"] is not None:
                self.err(row, code, "unit_cost", "must be empty for pct_of_subtotal (the "
                         "engine sets it from the subtotal).")
        elif u == "%":
            self.err(row, code, "unit", "unit '%' is only for pct_of_subtotal.")
        if rule is Rule.COUNT_CODES and unit and u not in ("EA", "LS"):
            self.warn(row, code, "unit", f"count_codes gives a count; unit '{unit}' "
                      "(expected EA).")
        if values["unit_cost"] is None and rule is not Rule.PCT_OF_SUBTOTAL and not placeholder:
            self.warn(row, code, "unit_cost", "empty: line priced 0.")

    # cross-row checks -------------------------------------------------------
    def check_all(self, lines: list[CostDbRow]) -> None:
        by_code: dict[str, list[CostDbRow]] = defaultdict(list)
        for line in lines:
            by_code[line.code].append(line)

        # duplicates (cluster, code, group, description), case/whitespace-insensitive
        seen: dict[tuple, int] = {}
        for line in lines:
            key = (_norm(line.display_cluster), line.code.upper(), _norm(line.group),
                   _norm(line.description))
            if key in seen:
                self.err(line.row, line.code, None,
                         f"duplicate of row {seen[key]} (same cluster, assembly_code, group "
                         "and description).")
            else:
                seen[key] = line.row

        # rule targets exist
        for line in lines:
            for t in line.rule_targets:
                if t in by_code or uniformat.lookup(t) is not None:
                    if line.rule is Rule.MIRROR and any(
                        src.rule is Rule.MIRROR for src in by_code.get(t, [])
                    ):
                        self.err(line.row, line.code, "quantity_rule",
                                 f"mirror target {t} is itself a mirror (no chains).")
                    continue
                self.err(line.row, line.code, "quantity_rule",
                         f"target {t} is neither in the Uniformat reference list nor a code "
                         "of this cost DB." + _suggest_text(uniformat.suggest(t)))

        # split keywords: consistent per sub-code, one fallback per base code
        spec_by_sub: dict[str, tuple[str, int]] = {}
        subs_by_base: dict[str, list[str]] = defaultdict(list)
        for line in lines:
            if "." not in line.code:
                continue
            base = uniformat.base_code(line.code)
            if line.code not in subs_by_base[base]:
                subs_by_base[base].append(line.code)
            spec = FALLBACK_KEYWORD if line.is_fallback else "|".join(line.keywords)
            if not spec:
                continue
            if line.code in spec_by_sub and spec_by_sub[line.code][0] != spec:
                self.err(line.row, line.code, "split_keywords",
                         f"differs from row {spec_by_sub[line.code][1]} for the same sub-code.")
            spec_by_sub.setdefault(line.code, (spec, line.row))
        for base, subs in subs_by_base.items():
            fallbacks = [s for s in subs if spec_by_sub.get(s, ("",))[0] == FALLBACK_KEYWORD]
            if len(fallbacks) > 1:
                row = spec_by_sub[fallbacks[1]][1]
                self.err(row, fallbacks[1], "split_keywords",
                         f"more than one '*' sub-code for {base}: {', '.join(fallbacks)}.")
            for sub in subs:
                if sub not in spec_by_sub:
                    for line in by_code[sub]:
                        if line.rule is Rule.TAKEOFF:
                            self.warn(line.row, sub, "split_keywords",
                                      f"empty: no {base} element is routed to this sub-code "
                                      "(takeoff quantity 0).")
            if fallbacks and base in by_code:
                for line in by_code[base]:
                    if line.rule is Rule.TAKEOFF:
                        self.warn(line.row, base, "quantity_rule",
                                  f"all {base} elements go to its sub-codes "
                                  f"({', '.join(subs)}); this row gets no takeoff quantity.")

        # custom clusters: one warning per cluster
        for cluster, rows in self._custom_rows.items():
            self.db.warnings.append(
                f"{_rows_label(rows)}: cluster '{cluster}' is a custom cluster (not a "
                "course cluster A-H): Uniformat code check skipped."
            )

        # not rated
        for col, rows in self.db.not_rated.items():
            n = f"{len(rows)} row{'s' if len(rows) != 1 else ''}"
            self.db.warnings.append(
                f"{_rows_label(rows)}: {col}: not rated ({n}); needed for the reliability "
                "summary (P3.5)."
            )

        # mislabels (D codes whose description points to another D group)
        for m in find_mislabels(lines):
            self.db.mislabels.append(m)
            self.warn(m["row"], m["assembly_code"], "description",
                      f"'{m['description']}' suggests {m['suggested_group']} "
                      f"({m['suggested_title']}), but {m['assembly_code']} is "
                      f"'{m['code_title']}' ({m['code_group']}); code kept.")

        self.db.unpriced = [
            {"row": line.row, "cluster": line.display_cluster, "assembly_code": line.code}
            for line in lines
            if line.unit_cost is None and line.rule is not Rule.PCT_OF_SUBTOTAL
        ]


def find_mislabels(lines: Iterable[CostDbRow]) -> list[dict]:
    """D rows whose description names another D level-2 group (e.g. D5030 'Fire ...')."""
    ref = uniformat.reference()
    out = []
    for line in lines:
        if not line.code.startswith("D") or not line.description:
            continue
        desc = line.description.lower()
        for keywords, group in DESCRIPTION_HINTS:
            if any(k in desc for k in keywords) and uniformat.level2(line.code) != group:
                out.append({
                    "row": line.row,
                    "assembly_code": line.code,
                    "description": line.description,
                    "code_title": uniformat.title(line.code) or "",
                    "code_group": uniformat.level2(line.code),
                    "suggested_group": group,
                    "suggested_title": ref[group].title,
                })
                break
    return out


def _records(text: str) -> tuple[list[str] | None, list[tuple[int, list[str]]]]:
    """CSV records with their row number; '#' comment lines and blank lines skipped."""
    text = text.lstrip("\ufeff")
    lines = ["" if ln.lstrip().startswith("#") else ln for ln in text.splitlines()]
    reader = csv.reader(io.StringIO("\n".join(lines) + "\n"))
    header, records, start = None, [], 1
    for rec in reader:
        row, start = start, reader.line_num + 1
        if not rec or all(not c.strip() for c in rec):
            continue
        if header is None:
            header = rec
        else:
            records.append((row, rec))
    return header, records


def validate_cost_db_records(
    header: list[str],
    records: list[tuple[int, list[str]]],
    *,
    custom_clusters: Iterable[str] | None = None,
    source: str = "",
) -> CostDb:
    """Validate parsed CSV records (row number, cells) against the header."""
    v = _Validator(custom_clusters)
    v.db.source = source
    if not v.check_header(header):
        return v.db
    names = [h.strip() for h in header]
    lines = []
    for row, cells in records:
        if len(cells) > len(names) and any(c.strip() for c in cells[len(names):]):
            v.err(row, "", None, f"{len(cells)} cells, but the header has {len(names)} "
                  "columns (unquoted comma?).")
            continue
        rec = {name: (cells[i] if i < len(cells) else "") for i, name in enumerate(names)}
        line = v.check_row(row, rec)
        if line is not None:
            lines.append(line)
    if not records:
        v.db.warnings.append("the cost DB has no rows.")
    v.check_all(lines)
    v.db.lines = lines
    return v.db


def validate_cost_db_dicts(
    rows: list[dict[str, str]], *, custom_clusters: Iterable[str] | None = None
) -> CostDb:
    """Validate rows given as dicts (column → text); row numbers start at 2."""
    header = list(COLUMNS) + [c for c in OPTIONAL_COLUMNS if any(c in r for r in rows)]
    records = [(i + 2, [str(r.get(c, "") or "") for c in header]) for i, r in enumerate(rows)]
    return validate_cost_db_records(header, records, custom_clusters=custom_clusters)


def validate_cost_db_text(
    text: str, *, custom_clusters: Iterable[str] | None = None, source: str = ""
) -> CostDb:
    header, records = _records(text)
    if header is None:
        return CostDb(errors=["header: the file is empty (no header row)."], source=source)
    return validate_cost_db_records(header, records, custom_clusters=custom_clusters,
                                    source=source)


def validate_cost_db_file(
    path: Path | str, *, custom_clusters: Iterable[str] | None = None
) -> CostDb:
    """Read and validate a ``cost_db.csv`` file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return CostDb(errors=[f"{path}: cannot read file ({exc.strerror})."], source=str(path))
    return validate_cost_db_text(text, custom_clusters=custom_clusters, source=str(path))


def load_cost_db(path: Path | str, *, custom_clusters: Iterable[str] | None = None) -> CostDb:
    """Validate a cost DB file; raise :class:`CostDbError` listing all errors."""
    db = validate_cost_db_file(path, custom_clusters=custom_clusters)
    if not db.ok:
        raise CostDbError(db.errors, source=str(path))
    return db


def cost_db_from_dicts(
    rows: list[dict[str, str]], *, custom_clusters: Iterable[str] | None = None
) -> CostDb:
    """Like :func:`load_cost_db` for in-memory rows (tests)."""
    db = validate_cost_db_dicts(rows, custom_clusters=custom_clusters)
    if not db.ok:
        raise CostDbError(db.errors)
    return db


__all__ = [
    "COLUMNS",
    "KNOWN_UNITS",
    "OPTIONAL_COLUMNS",
    "TAKEOFF_UNITS",
    "CostDb",
    "CostDbError",
    "CostDbRow",
    "Rule",
    "cost_db_from_dicts",
    "find_mislabels",
    "json_schema",
    "json_schema_text",
    "load_cost_db",
    "validate_cost_db_dicts",
    "validate_cost_db_file",
    "validate_cost_db_records",
    "validate_cost_db_text",
]
