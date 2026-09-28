"""P3.6: STV mapping table (``stv_mapping.csv``): Revit export rows → course STV items.

One CSV row per rule. A rule says which Revit elements it takes (``discipline``,
``assembly_code``, ``category``, ``keyword``), what they become in the course LCA catalog
(``stv_assembly``, ``stv_material_type``) and how the amount is measured
(``quantity_field``, ``conversion``). This is team data, not course data: the table names
catalog entries but holds no LCA values. Format reference: ``docs/engines/stv.md``; JSON
Schema of one row: ``docs/schema/stv_mapping.schema.json`` (from :class:`StvMappingRow`).

Matching (per element of an export):

1. ``discipline`` (optional) must be empty or the discipline of the export being read
   (architecture / structural / mep: given by the importer, not by the export).
2. ``assembly_code``: the element's Assembly Code starts with the rule's code (``B2010``
   matches ``B2010``, ``B2010100``; the level-2 form ``B2000`` matches everything in ``B20``).
3. ``category``: equals the Revit Category (case-insensitive); for a Part (Category
   ``Parts``) its ``Original Category``, or ``Parts`` if that is empty (P3.9).
4. ``keyword``: case-insensitive substrings of Family + Type + Material + Assembly
   Description. ``a|b`` = any, ``a&b`` = all (``&`` binds looser: ``a|b&c`` = (a or b) and
   c). A term can be a numeric test on a named value, e.g. ``diameter_in<=15``
   (:data:`engines.stv.conversions.NUMERIC_TESTS`).

Of the matching rules the most specific wins: code + category + keyword > code + category >
code > category + keyword > category. Within the same specificity the lowest ``priority``
wins (default 100). Two winners with the same priority are a **tie**: an error that names
both rules and the element. Rules with the same key (discipline overlap, code, category,
keyword) and priority are a tie for every element and are rejected by the validator.
"""

from __future__ import annotations

import csv
import difflib
import io
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from engines.common import uniformat
from engines.common.dedup import DedupResult, Export, deduplicate, effective_category

from . import conversions
from .conversions import ConversionSpec, ConversionSpecError, Row
from .models import ConstructionItem

SCHEMA_ID = "https://github.com/mxngl/concho/blob/main/docs/schema/stv_mapping.schema.json"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

COLUMNS: tuple[str, ...] = (
    "assembly_code", "category", "keyword", "stv_assembly", "stv_material_type",
    "quantity_field", "conversion", "note",
)
OPTIONAL_COLUMNS: tuple[str, ...] = ("discipline", "priority")
DEFAULT_PRIORITY = 100
# Default table for common Uniformat codes (used when no project table is given).
DEFAULT_MAPPING_PATH = Path(__file__).resolve().parents[2] / "template" / "stv_mapping.csv"


# P3.7: a rule whose note contains the word "proxy" books its elements as a stand-in
# material; the results flag those quantities (ConstructionItem.proxy_amount).
PROXY_RE = re.compile(r"\bproxy\b", re.IGNORECASE)


class Discipline(StrEnum):
    ARCHITECTURE = "architecture"
    STRUCTURAL = "structural"
    MEP = "mep"


DISCIPLINES = tuple(d.value for d in Discipline)
QUANTITY_FIELDS = tuple(conversions.QUANTITY_FIELDS)

# Units of the catalog material types (the "(...)" at the end of the name) that are physical
# quantities. ``count`` fits every other unit (Bike, Turbine, Panel, ...).
PHYSICAL_UNITS = frozenset({
    "sf", "cf", "cy", "ft", "kg", "m^3/s", "m^3/hr", "btu/hr", "kbtu/h", "gal", "gal/day",
    "l", "kwh", "nominal tons",
})
_UNIT_RE = re.compile(r"\(([^()]*)\)\s*$")
_TEST_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|<|>)\s*(-?[0-9]+(?:\.[0-9]+)?)$")
_TEST_LIKE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*(<=|>=|<|>|=)")


class Specificity(IntEnum):
    """Lower = more specific (wins)."""

    CODE_CATEGORY_KEYWORD = 1
    CODE_CATEGORY = 2
    CODE = 3
    CATEGORY_KEYWORD = 4
    CATEGORY = 5


SPECIFICITY_LABELS = {
    Specificity.CODE_CATEGORY_KEYWORD: "code + category + keyword",
    Specificity.CODE_CATEGORY: "code + category",
    Specificity.CODE: "code",
    Specificity.CATEGORY_KEYWORD: "category + keyword",
    Specificity.CATEGORY: "category",
}


class StvMappingRow(BaseModel):
    """One rule of ``stv_mapping.csv``. Team data, not course data."""

    model_config = ConfigDict(
        extra="forbid",
        title="stv_mapping.csv row",
        json_schema_extra={
            "$schema": SCHEMA_DIALECT,
            "$id": SCHEMA_ID,
            "x-csv-columns": [*COLUMNS, *OPTIONAL_COLUMNS],
            "x-csv-notes": (
                "One CSV row per rule. Empty cells = empty string. discipline and priority "
                "are optional columns. Lines starting with '#' are comments. Most specific "
                "rule wins (code+category+keyword > code+category > code > category+keyword "
                "> category), then the lowest priority; a remaining tie is an error. "
                "See docs/engines/stv.md."
            ),
        },
    )

    discipline: str = Field(
        default="",
        pattern=r"^(|architecture|structural|mep)$",
        description="Only for elements of this export (architecture | structural | mep); "
                    "empty = all. The discipline comes from the importer, not the export.",
    )
    assembly_code: str = Field(
        default="",
        pattern=r"^(|[A-Z][0-9]{4})$",
        description="Uniformat code (engines/common/uniformat.csv: level 3, the 4-digit form "
                    "of a level-2 code such as B2000, or an extension). Matches element "
                    "Assembly Codes that start with it. Empty = any code.",
    )
    category: str = Field(
        default="",
        description="Revit Category (case-insensitive), e.g. 'Walls'; Parts match with their "
                    "'Original Category' ('Parts' if empty). Empty = any category "
                    "(then assembly_code is required and keyword must be empty).",
    )
    keyword: str = Field(
        default="",
        description="Case-insensitive substrings of Family + Type + Material + Assembly "
                    "Description: 'a|b' = any, 'a&b' = all ('&' binds looser). A term can be "
                    "a named numeric test such as 'diameter_in<=15'. Needs a category.",
    )
    priority: int = Field(
        default=DEFAULT_PRIORITY, ge=0,
        description="Orders rules of the same specificity that match the same element: "
                    "lower wins. Default 100.",
    )
    stv_assembly: str = Field(
        min_length=1, description="Assembly of the course LCA catalog, e.g. 'Exterior Wall'."
    )
    stv_material_type: str = Field(
        min_length=1,
        description="Material/Type of the course LCA catalog for that assembly, e.g. "
                    "'Concrete Cladding (sf)'. Its unit must match quantity_field + conversion.",
    )
    quantity_field: str = Field(
        pattern="^(" + "|".join(QUANTITY_FIELDS) + ")$",
        description="area (SF) | volume (CF) | length (FT) | count | weight (kg) | "
                    "airflow (m^3/s), read from the export row.",
    )
    conversion: str = Field(
        default="",
        description="Named conversion: " + ", ".join(
            f"{c.name}" + (f"({';'.join(p + '=...' for p in c.params)})" if c.params else "")
            for c in conversions.CONVERSIONS.values()
        ) + ". One-parameter conversions may be written name=value. Empty = none.",
    )
    note: str = Field(
        default="",
        description="Free text (why this rule, proxies, ...). A note containing the word "
                    "'proxy' marks a proxy rule (P3.7): its quantities are flagged in the "
                    "results (data_flags).",
    )


def json_schema() -> dict[str, Any]:
    return StvMappingRow.model_json_schema()


def json_schema_text() -> str:
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumericTest:
    name: str
    op: str
    value: float

    def __call__(self, row: Row) -> bool:
        actual = conversions.NUMERIC_TESTS[self.name](row)
        if actual is None:
            return False
        return {
            "<=": actual <= self.value, "<": actual < self.value,
            ">=": actual >= self.value, ">": actual > self.value,
        }[self.op]

    def __str__(self) -> str:
        return f"{self.name}{self.op}{self.value:g}"


Term = str | NumericTest


@dataclass(frozen=True)
class Keyword:
    """Conjunction (``&``) of groups; each group is a disjunction (``|``) of terms."""

    groups: tuple[tuple[Term, ...], ...] = ()

    def __bool__(self) -> bool:
        return bool(self.groups)

    def matches(self, text: str, row: Row) -> bool:
        return all(
            any(term(row) if isinstance(term, NumericTest) else term in text for term in group)
            for group in self.groups
        )

    @property
    def key(self) -> tuple:
        """Order-independent key (for duplicate detection)."""
        return tuple(sorted(tuple(sorted(str(t) for t in g)) for g in self.groups))

    def __str__(self) -> str:
        return "&".join("|".join(str(t) for t in g) for g in self.groups)


def parse_keyword(spec: str) -> Keyword:
    """``'exterior|curtain & concrete'`` → Keyword. Raises ValueError on bad syntax."""
    text = spec.strip()
    if not text:
        return Keyword()
    groups = []
    for raw_group in text.split("&"):
        terms: list[Term] = []
        for raw in raw_group.split("|"):
            term = " ".join(raw.split()).lower()
            if not term:
                raise ValueError(f"empty term in '{spec}' (check '|' and '&').")
            m = _TEST_RE.match(term)
            if m:
                name, op, value = m.groups()
                if name not in conversions.NUMERIC_TESTS:
                    raise ValueError(
                        f"unknown numeric test '{name}' in '{spec}'; known: "
                        f"{', '.join(sorted(conversions.NUMERIC_TESTS))}."
                    )
                terms.append(NumericTest(name, op, float(value)))
            elif _TEST_LIKE_RE.match(term):
                raise ValueError(
                    f"'{term}' looks like a numeric test but is not one: use "
                    "name<=number, name<number, name>=number or name>number with a known "
                    f"name ({', '.join(sorted(conversions.NUMERIC_TESTS))})."
                )
            else:
                terms.append(term)
        groups.append(tuple(terms))
    return Keyword(tuple(groups))


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MappingRule:
    """One validated rule. ``is_proxy``: the note contains the word "proxy" (P3.7)."""

    row: int
    discipline: str
    assembly_code: str
    category: str
    keyword: Keyword
    priority: int
    stv_assembly: str
    stv_material_type: str
    quantity_field: str
    conversion: ConversionSpec | None
    note: str = ""
    keyword_text: str = ""
    conversion_text: str = ""

    @property
    def specificity(self) -> Specificity:
        code, cat, kw = bool(self.assembly_code), bool(self.category), bool(self.keyword)
        if code and cat:
            return Specificity.CODE_CATEGORY_KEYWORD if kw else Specificity.CODE_CATEGORY
        if code:
            return Specificity.CODE
        return Specificity.CATEGORY_KEYWORD if kw else Specificity.CATEGORY

    @property
    def code_prefix(self) -> str:
        """``B2000`` (level-2 form) → ``B20``; ``B2010`` → ``B2010``."""
        if not self.assembly_code:
            return ""
        entry = uniformat.lookup(self.assembly_code)
        if entry is not None and entry.origin == "nist" and entry.level == 2:
            return entry.code
        return self.assembly_code

    @property
    def unit(self) -> str:
        return conversions.output_unit(self.quantity_field, self.conversion)

    @property
    def is_proxy(self) -> bool:
        return bool(PROXY_RE.search(self.note))

    def label(self) -> str:
        parts = [f"row {self.row}"]
        if self.discipline:
            parts.append(self.discipline)
        for value in (self.assembly_code, self.category, self.keyword_text):
            if value:
                parts.append(value)
        return f"{' / '.join(parts)} (priority {self.priority}) → {self.stv_material_type}"

    def summary(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "discipline": self.discipline,
            "assembly_code": self.assembly_code,
            "category": self.category,
            "keyword": self.keyword_text,
            "priority": self.priority,
            "specificity": SPECIFICITY_LABELS[self.specificity],
            "stv_assembly": self.stv_assembly,
            "stv_material_type": self.stv_material_type,
            "quantity_field": self.quantity_field,
            "conversion": self.conversion_text,
            "proxy": self.is_proxy,
        }


def material_unit(material_type: str) -> str | None:
    """``'Glulam Beam (kg)'`` → ``'kg'``."""
    m = _UNIT_RE.search(material_type)
    return m.group(1).strip().lower() if m else None


def units_compatible(unit: str, catalog_unit: str | None) -> bool:
    if catalog_unit is None:
        return False
    if unit == "count":
        return catalog_unit not in PHYSICAL_UNITS
    return unit == catalog_unit


# ---------------------------------------------------------------------------
# Elements and matching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Element:
    """One row of a Revit export, as the mapping sees it."""

    discipline: str
    row: Row
    source: str = ""
    line: int = 0

    def get(self, name: str) -> str:
        return (self.row.get(name) or "").strip()

    @property
    def element_id(self) -> str:
        return self.get("ElementId")

    @property
    def category(self) -> str:
        return self.get("Category")

    @property
    def match_category(self) -> str:
        """The category the rules match (P3.9): a Part's ``Original Category``, else
        ``Category`` (``Parts`` when ``Original Category`` is empty, as in old exports)."""
        return effective_category(self.row)

    @property
    def assembly_code(self) -> str:
        return self.get("Assembly Code").upper()

    @property
    def keyword_text(self) -> str:
        return "\n".join(
            self.get(name).lower()
            for name in ("Family", "Type", "Material", "Assembly Description")
        )

    def describe(self) -> str:
        where = f"{Path(self.source).name}:{self.line}" if self.source else f"line {self.line}"
        return (f"element {self.element_id or '?'} ({where}; {self.category} / "
                f"{self.get('Family')} / {self.get('Type')})")


class StvMappingTieError(ValueError):
    pass


@dataclass
class Match:
    rule: MappingRule | None
    lost_to_priority: tuple[MappingRule, ...] = ()
    lost_to_specificity: tuple[MappingRule, ...] = ()
    tie: tuple[MappingRule, ...] = ()


class StvMapping:
    """A validated mapping table."""

    def __init__(self, rules: list[MappingRule], source: str = "", warnings=None):
        self.rules = rules
        self.source = source
        self.warnings: list[str] = list(warnings or [])
        self._by_category: dict[str, list[MappingRule]] = defaultdict(list)
        for rule in rules:
            self._by_category[rule.category.lower()].append(rule)

    def candidates(self, element: Element) -> list[MappingRule]:
        category = element.match_category.lower()
        code = element.assembly_code
        text = element.keyword_text
        out = []
        for rule in self._by_category.get(category, []) + (
            self._by_category.get("", []) if category else []
        ):
            if rule.discipline and rule.discipline != element.discipline:
                continue
            if rule.assembly_code and not code.startswith(rule.code_prefix):
                continue
            if rule.keyword and not rule.keyword.matches(text, element.row):
                continue
            out.append(rule)
        return out

    def match(self, element: Element) -> Match:
        """The winning rule (or None); ``tie`` is set when two rules share the best rank.
        Elements of an unknown discipline (central BIM rows of other sources) stay unmapped."""
        if element.discipline not in DISCIPLINES:
            return Match(None)
        found = self.candidates(element)
        if not found:
            return Match(None)
        best_spec = min(r.specificity for r in found)
        same_spec = [r for r in found if r.specificity == best_spec]
        best_prio = min(r.priority for r in same_spec)
        winners = sorted((r for r in same_spec if r.priority == best_prio), key=lambda r: r.row)
        return Match(
            rule=winners[0] if len(winners) == 1 else None,
            lost_to_priority=tuple(r for r in same_spec if r.priority != best_prio),
            lost_to_specificity=tuple(r for r in found if r.specificity != best_spec),
            tie=tuple(winners) if len(winners) > 1 else (),
        )


def tie_message(element: Element, rules: tuple[MappingRule, ...]) -> str:
    return (
        f"tie: {element.describe()} matches {len(rules)} rules with the same specificity "
        f"({SPECIFICITY_LABELS[rules[0].specificity]}) and priority {rules[0].priority}: "
        + "; ".join(r.label() for r in rules)
        + ". Give one of them a lower priority or a narrower keyword."
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class Catalog(Protocol):
    """What the validator needs from the course LCA catalog (``STVReferenceData``)."""

    valid_materials: dict[str, set[str]]


class StvMappingError(ValueError):
    """Raised by :func:`load_stv_mapping` when the table has errors."""

    def __init__(self, errors: list[str], source: str = "STV mapping"):
        self.errors = errors
        super().__init__(f"invalid {source}:\n" + "\n".join(f"  - {e}" for e in errors))


@dataclass
class MappingValidation:
    mapping: StvMapping | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _suggest(value: str, options: list[str]) -> str:
    close = difflib.get_close_matches(value, options, n=3, cutoff=0.5)
    return f" Did you mean {' / '.join(repr(c) for c in close)}?" if close else ""


class _Validator:
    def __init__(self, catalog: Catalog | None):
        self.catalog = catalog
        self.result = MappingValidation()

    def err(self, row: int, column: str, msg: str) -> None:
        where = f"row {row}" + (f", {column}" if column else "")
        self.result.errors.append(f"{where}: {msg}")

    def check_header(self, header: list[str]) -> bool:
        names = [h.strip() for h in header]
        ok = True
        for dup in sorted({n for n in names if names.count(n) > 1}):
            self.result.errors.append(f"header: column '{dup}' appears more than once.")
            ok = False
        missing = [c for c in COLUMNS if c not in names]
        if missing:
            self.result.errors.append(f"header: missing column(s): {', '.join(missing)}.")
            ok = False
        unknown = [n for n in names if n not in COLUMNS + OPTIONAL_COLUMNS]
        for name in unknown:
            self.result.errors.append(
                f"header: unknown column '{name}'."
                + _suggest(name, list(COLUMNS + OPTIONAL_COLUMNS))
            )
            ok = False
        return ok

    def check_row(self, row: int, rec: dict[str, str]) -> MappingRule | None:
        n_errors = len(self.result.errors)
        get = {k: (v or "").strip() for k, v in rec.items()}

        discipline = get.get("discipline", "").lower()
        if discipline and discipline not in DISCIPLINES:
            self.err(row, "discipline", f"'{get['discipline']}' is not one of "
                     f"{', '.join(DISCIPLINES)} (or empty = all).")

        code = get["assembly_code"].upper()
        if code:
            if "." in code:
                self.err(row, "assembly_code", f"'{code}': sub-codes are not used in the STV "
                         "mapping; use the base code.")
            elif not uniformat.is_well_formed(code) or uniformat.lookup(code) is None:
                suggestions = uniformat.suggest(code)
                self.err(row, "assembly_code",
                         f"'{get['assembly_code']}' is not in the Uniformat reference list "
                         "(engines/common/uniformat.csv, level 3 or X##00, or an extension)."
                         + (f" Did you mean {' / '.join(suggestions)}?" if suggestions else ""))

        category = " ".join(get["category"].split())
        keyword = Keyword()
        try:
            keyword = parse_keyword(get["keyword"])
        except ValueError as exc:
            self.err(row, "keyword", str(exc))
        if not code and not category:
            self.err(row, "", "a rule needs a category or an assembly_code (or both).")
        elif keyword and not category:
            self.err(row, "keyword", "a keyword needs a category (the specificity order has "
                     "no 'code + keyword' or 'keyword' level).")

        raw_priority = get.get("priority", "")
        priority = DEFAULT_PRIORITY
        if raw_priority:
            if re.fullmatch(r"[0-9]+", raw_priority):
                priority = int(raw_priority)
            else:
                self.err(row, "priority", f"'{raw_priority}' is not a whole number ≥ 0.")

        assembly, material = get["stv_assembly"], get["stv_material_type"]
        if not assembly:
            self.err(row, "stv_assembly", "empty.")
        if not material:
            self.err(row, "stv_material_type", "empty.")
        if assembly and material and self.catalog is not None:
            known = self.catalog.valid_materials
            if assembly not in known:
                self.err(row, "stv_assembly", f"'{assembly}' is not an assembly of the course "
                         f"LCA catalog." + _suggest(assembly, sorted(known)))
            elif material not in known[assembly]:
                self.err(row, "stv_material_type",
                         f"'{material}' is not in the course LCA catalog for '{assembly}'."
                         + _suggest(material, sorted(known[assembly])))

        quantity_field = get["quantity_field"].lower()
        if quantity_field not in QUANTITY_FIELDS:
            self.err(row, "quantity_field", f"'{get['quantity_field']}' is not one of "
                     f"{' | '.join(QUANTITY_FIELDS)}.")
        conversion = None
        try:
            conversion = conversions.parse_conversion(get["conversion"])
        except ConversionSpecError as exc:
            self.err(row, "conversion", str(exc))
        if conversion is not None and quantity_field in QUANTITY_FIELDS:
            needed = conversion.definition.quantity_field
            if needed != quantity_field:
                self.err(row, "conversion", f"{conversion.name} converts quantity_field "
                         f"'{needed}', not '{quantity_field}'.")
                conversion = None
        if quantity_field in QUANTITY_FIELDS and material and len(self.result.errors) == n_errors:
            unit = conversions.output_unit(quantity_field, conversion)
            catalog_unit = material_unit(material)
            if not units_compatible(unit, catalog_unit):
                how = f"{quantity_field}" + (f" + {conversion.name}" if conversion else "")
                self.err(row, "quantity_field",
                         f"unit mismatch: {how} gives '{unit}', but '{material}' is "
                         f"measured in '{catalog_unit or '?'}'.")

        if len(self.result.errors) != n_errors:
            return None
        return MappingRule(
            row=row, discipline=discipline, assembly_code=code, category=category,
            keyword=keyword, priority=priority, stv_assembly=assembly,
            stv_material_type=material, quantity_field=quantity_field, conversion=conversion,
            note=get["note"], keyword_text=get["keyword"],
            conversion_text=get["conversion"],
        )

    def check_ties(self, rules: list[MappingRule]) -> None:
        groups: dict[tuple, list[MappingRule]] = defaultdict(list)
        for rule in rules:
            key = (rule.assembly_code, _norm(rule.category), rule.keyword.key, rule.priority)
            groups[key].append(rule)
        for same in groups.values():
            for i, a in enumerate(same):
                for b in same[i + 1:]:
                    if a.discipline and b.discipline and a.discipline != b.discipline:
                        continue
                    self.result.errors.append(
                        f"rows {a.row} and {b.row}: tie: same code, category, keyword and "
                        f"priority ({a.priority}) for overlapping disciplines "
                        f"('{a.discipline or 'all'}' / '{b.discipline or 'all'}'); every "
                        "element they match would be a tie. Change the priority of one."
                    )


def _records(text: str) -> tuple[list[str] | None, list[tuple[int, list[str]]]]:
    """CSV records with their line number; '#' comment lines and blank lines skipped."""
    text = text.lstrip("﻿")
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


def validate_stv_mapping_records(
    header: list[str],
    records: list[tuple[int, list[str]]],
    *,
    catalog: Catalog | None = None,
    source: str = "",
) -> MappingValidation:
    v = _Validator(catalog)
    v.result.source = source
    if not v.check_header(header):
        return v.result
    names = [h.strip() for h in header]
    rules = []
    for row, cells in records:
        if len(cells) > len(names) and any(c.strip() for c in cells[len(names):]):
            v.err(row, "", f"{len(cells)} cells, but the header has {len(names)} columns "
                  "(unquoted comma?).")
            continue
        rec = {name: (cells[i] if i < len(cells) else "") for i, name in enumerate(names)}
        for name in COLUMNS + OPTIONAL_COLUMNS:
            rec.setdefault(name, "")
        rule = v.check_row(row, rec)
        if rule is not None:
            rules.append(rule)
    if not records:
        v.result.warnings.append("the mapping table has no rules.")
    v.check_ties(rules)
    if catalog is None:
        v.result.warnings.append(
            "stv_assembly / stv_material_type not checked against the course LCA catalog "
            "(no course workbook given: --template or $COURSE_STV_XLSX)."
        )
    if v.result.ok:
        v.result.mapping = StvMapping(rules, source=source, warnings=v.result.warnings)
    return v.result


def validate_stv_mapping_dicts(
    rows: list[dict[str, str]], *, catalog: Catalog | None = None
) -> MappingValidation:
    """Validate rules given as dicts (column → text); row numbers start at 2."""
    header = list(COLUMNS) + [c for c in OPTIONAL_COLUMNS if any(c in r for r in rows)]
    records = [(i + 2, [str(r.get(c, "") or "") for c in header]) for i, r in enumerate(rows)]
    return validate_stv_mapping_records(header, records, catalog=catalog)


def validate_stv_mapping_text(
    text: str, *, catalog: Catalog | None = None, source: str = ""
) -> MappingValidation:
    header, records = _records(text)
    if header is None:
        return MappingValidation(errors=["header: the file is empty (no header row)."],
                                 source=source)
    return validate_stv_mapping_records(header, records, catalog=catalog, source=source)


def validate_stv_mapping_file(
    path: Path | str, *, catalog: Catalog | None = None
) -> MappingValidation:
    path = Path(os.path.normpath(path))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return MappingValidation(errors=[f"{path}: cannot read file ({exc.strerror})."],
                                 source=str(path))
    return validate_stv_mapping_text(text, catalog=catalog, source=str(path))


def load_stv_mapping(path: Path | str, *, catalog: Catalog | None = None) -> StvMapping:
    """Validate a mapping file; raise :class:`StvMappingError` listing all errors."""
    result = validate_stv_mapping_file(path, catalog=catalog)
    if not result.ok:
        raise StvMappingError(result.errors, source=str(path))
    assert result.mapping is not None
    return result.mapping


def stv_mapping_from_dicts(
    rows: list[dict[str, str]], *, catalog: Catalog | None = None
) -> StvMapping:
    """Like :func:`load_stv_mapping` for in-memory rows (tests)."""
    result = validate_stv_mapping_dicts(rows, catalog=catalog)
    if not result.ok:
        raise StvMappingError(result.errors)
    assert result.mapping is not None
    return result.mapping


# ---------------------------------------------------------------------------
# Mapping an export
# ---------------------------------------------------------------------------


@dataclass
class MappedElement:
    element: Element
    rule: MappingRule | None
    amount: float = 0.0
    estimated: bool = False
    lost_to_priority: tuple[MappingRule, ...] = ()
    lost_to_specificity: tuple[MappingRule, ...] = ()

    @property
    def status(self) -> str:
        if self.rule is None:
            return "unmapped"
        return "mapped" if self.amount > 0 else "zero_quantity"

    def skipped_row(self) -> dict[str, str]:
        e = self.element
        reason = (
            "No STV mapping rule matched this row." if self.rule is None
            else f"Rule row {self.rule.row} matched, but the quantity is 0."
        )
        return {
            "element_id": e.element_id,
            "category": e.category,
            "family": e.get("Family"),
            "type": e.get("Type"),
            "assembly_code": e.get("Assembly Code"),
            "material": e.get("Material"),
            "area": e.get("Area"),
            "volume": e.get("Volume"),
            "length": e.get("Length"),
            "reason": reason,
        }


@dataclass(slots=True)
class ScheduleReport:
    """Result of mapping one Revit export (one discipline)."""

    discipline: str
    source: str
    construction_items: list[ConstructionItem]
    elements: list[MappedElement]
    mapping_source: str = ""

    @property
    def mapped_rows(self) -> int:
        return sum(1 for e in self.elements if e.status == "mapped")

    @property
    def skipped_rows(self) -> list[dict[str, str]]:
        return [e.skipped_row() for e in self.elements if e.status != "mapped"]

    def to_dict(self) -> dict[str, object]:
        return {
            "discipline": self.discipline,
            "source": self.source,
            "mapping": self.mapping_source,
            "mapped_rows": self.mapped_rows,
            "skipped_rows": self.skipped_rows,
            "construction_items": [
                {
                    "assembly": item.assembly,
                    "material_type": item.material_type,
                    "amount": item.amount,
                    "estimated_amount": item.estimated_amount,
                    "proxy_amount": item.proxy_amount,
                }
                for item in self.construction_items
            ],
        }


def map_elements(
    elements: list[Element], mapping: StvMapping, *, discipline: str, source: str = ""
) -> ScheduleReport:
    """Map elements; raise :class:`StvMappingTieError` listing every tie."""
    totals: dict[tuple[str, str], float] = defaultdict(float)
    estimated: dict[tuple[str, str], float] = defaultdict(float)
    proxy: dict[tuple[str, str], float] = defaultdict(float)
    mapped: list[MappedElement] = []
    ties: list[str] = []
    for element in elements:
        match = mapping.match(element)
        if match.tie:
            ties.append(tie_message(element, match.tie))
            continue
        result = MappedElement(element, match.rule, lost_to_priority=match.lost_to_priority,
                               lost_to_specificity=match.lost_to_specificity)
        if match.rule is not None:
            q = conversions.quantity(element.row, match.rule.quantity_field,
                                     match.rule.conversion)
            result.amount, result.estimated = q.amount, q.estimated and q.amount > 0
            if result.amount > 0:
                key = (match.rule.stv_assembly, match.rule.stv_material_type)
                totals[key] += result.amount
                if result.estimated:
                    estimated[key] += result.amount
                if match.rule.is_proxy:
                    proxy[key] += result.amount
        mapped.append(result)
    if ties:
        raise StvMappingTieError(
            f"{source or discipline}: {len(ties)} tie(s) in {mapping.source or 'the mapping'}:"
            "\n" + "\n".join(f"  - {t}" for t in ties)
        )
    items = [
        ConstructionItem(assembly=assembly, material_type=material_type, amount=amount,
                         estimated_amount=estimated.get((assembly, material_type), 0.0),
                         proxy_amount=proxy.get((assembly, material_type), 0.0))
        for (assembly, material_type), amount in sorted(totals.items())
        if amount > 0
    ]
    return ScheduleReport(discipline=discipline, source=source, construction_items=items,
                          elements=mapped, mapping_source=mapping.source)


def read_export(csv_path: Path | str, discipline: str) -> list[Element]:
    path = Path(csv_path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return [
            Element(discipline=discipline, row=row, source=str(path), line=reader.line_num)
            for row in reader
        ]


def load_schedule(
    csv_path: Path | str, mapping: StvMapping, *, discipline: str
) -> ScheduleReport:
    """Read one Revit export of ``discipline`` and map it with ``mapping``."""
    return map_elements(read_export(csv_path, discipline), mapping, discipline=discipline,
                        source=str(csv_path))


def can_map(mapping: StvMapping, element: Element) -> bool:
    """A rule matches the element (a tie counts: it stops the run later anyway)."""
    match = mapping.match(element)
    return match.rule is not None or bool(match.tie)


def map_exports(
    exports: list[tuple[str, Path | str]], mapping: StvMapping
) -> tuple[list[ScheduleReport], DedupResult]:
    """Read (discipline, path) exports, apply the P3.9 rule (D15, :mod:`engines.common.dedup`)
    over all of them, and map the rows that are kept, one report per export (input order).
    A mapping tie in any export raises :class:`StvMappingTieError`."""
    read = [(discipline, Path(path), read_export(path, discipline))
            for discipline, path in exports]
    result = deduplicate([Export(path.name, discipline, elements)
                          for discipline, path, elements in read],
                         is_mapped=lambda element, _discipline: can_map(mapping, element))
    reports = [map_elements(kept, mapping, discipline=discipline, source=str(path))
               for (discipline, path, _), kept in zip(read, result.kept, strict=True)]
    return reports, result


def check_exports(mapping: StvMapping, exports: list[tuple[str, Path | str]]) -> list[str]:
    """Tie errors of the mapping on real exports ((discipline, path) pairs)."""
    errors = []
    for discipline, path in exports:
        for element in read_export(path, discipline):
            match = mapping.match(element)
            if match.tie:
                errors.append(tie_message(element, match.tie))
    return errors
