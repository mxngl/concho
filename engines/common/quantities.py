"""Tolerant quantity parser for Revit takeoff exports (P4.5 engine part, P3.11).

Reads the ``Length`` / ``Area`` / ``Volume`` cells of both export generations:

- **new add-in exports** (since concho #18): plain invariant decimals in the course's
  imperial units (``312.5``), taken as the column's unit (ft / SF / CF);
- **old add-in exports** (Island fixtures): Revit display strings in the project units,
  e.g. ``9' - 7 3/4"``, ``136' - 0"``, ``6590 SF``, ``42.75 CF``.

Accepted forms (whitespace around every part is ignored, a leading ``-`` negates the whole
value, including ``-2' - 6"`` = -2.5 ft):

- plain decimals ``12``, ``12.5``, ``.5``, ``-3``;
- feet-inch: ``9' - 7 3/4"``, ``9'-7 3/4"``, ``9' 7.5"``, ``12'``, ``7 3/4"``, ``1/2"``;
- imperial suffixes: ``LF`` / ``ft`` / ``feet`` (length), ``SF`` / ``ft²`` / ``ft2`` /
  ``sq ft`` (area), ``CF`` / ``ft³`` / ``ft3`` / ``cu ft`` (volume), ``in`` (length, inches);
- metric suffixes ``mm`` / ``cm`` / ``m`` (length), ``m²`` / ``m2`` (area), ``m³`` / ``m3``
  (volume): converted to ft / SF / CF and reported as ``metric_converted``, never read as
  imperial numbers.

**Thousands and decimal separators.** ``.`` is the decimal point. ``,`` is taken as a
thousands separator only when that is the only possible reading: US grouping with a decimal
point (``1,234.5``) or with at least two groups (``1,234,567``). Every other comma
(``1,234``: 1234 or 1.234?, ``1.234,5``, ``12,5``) is ``ambiguous_separator``: the value is
not guessed and not counted (0), the raw string is reported.

Anything that is not one of these forms (an unknown suffix such as ``kg``, a unit of the wrong
dimension such as ``SF`` in ``Length``, or text without a number) is not counted either and
is reported with its issue. Callers collect the issues per column with
:class:`QuantityParseLog`; the TVD engine writes them to the ``quantity_parse_warnings``
block of its results JSON.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Quantity kinds (the dimension a column holds).
LENGTH, AREA, VOLUME = "length", "area", "volume"

# Issues. ``metric_converted`` values are counted (converted); all others count as 0.
METRIC_CONVERTED = "metric_converted"
AMBIGUOUS_SEPARATOR = "ambiguous_separator"
UNKNOWN_UNIT = "unknown_unit"
UNIT_MISMATCH = "unit_mismatch"
NO_NUMBER = "no_number"
ISSUES = (METRIC_CONVERTED, AMBIGUOUS_SEPARATOR, UNKNOWN_UNIT, UNIT_MISMATCH, NO_NUMBER)

MAX_EXAMPLES = 20

_FT_PER_M = 1 / 0.3048

# suffix (lower case, spaces removed) -> (kind, factor to ft / SF / CF, metric?)
_UNITS: dict[str, tuple[str, float, bool]] = {
    "lf": (LENGTH, 1.0, False),
    "ft": (LENGTH, 1.0, False),
    "feet": (LENGTH, 1.0, False),
    "in": (LENGTH, 1 / 12, False),
    "sf": (AREA, 1.0, False),
    "ft²": (AREA, 1.0, False),
    "ft2": (AREA, 1.0, False),
    "sqft": (AREA, 1.0, False),
    "cf": (VOLUME, 1.0, False),
    "ft³": (VOLUME, 1.0, False),
    "ft3": (VOLUME, 1.0, False),
    "cuft": (VOLUME, 1.0, False),
    "mm": (LENGTH, _FT_PER_M / 1000, True),
    "cm": (LENGTH, _FT_PER_M / 100, True),
    "m": (LENGTH, _FT_PER_M, True),
    "m²": (AREA, _FT_PER_M ** 2, True),
    "m2": (AREA, _FT_PER_M ** 2, True),
    "m³": (VOLUME, _FT_PER_M ** 3, True),
    "m3": (VOLUME, _FT_PER_M ** 3, True),
}

# A number as written in the cell: digits with optional `,` / `.` separators, validated by
# _to_float (separator rules above).
_NUM = r"(?:\d[\d,.]*|\.\d+)"
_NUMBER_WITH_SUFFIX = re.compile(rf"^(?P<num>{_NUM})\s*(?P<unit>.*)$")
# feet-inch: optional feet `F'`, optional separator `-`, optional inches `I"`, `I N/D"` (space
# between whole inches and fraction) or `N/D"`; at least one of the two parts (checked in code).
_FEET_INCH = re.compile(
    rf"""^(?:(?P<feet>{_NUM})\s*')?\s*-?\s*
        (?:(?:(?P<inch>{_NUM})(?:\s+(?P<num>\d+)\s*/\s*(?P<den>\d+))?
            |(?P<num2>\d+)\s*/\s*(?P<den2>\d+))\s*")?$""",
    re.VERBOSE,
)
_US_GROUPED = re.compile(r"^\d{1,3}(?:,\d{3})+\.\d*$|^\d{1,3}(?:,\d{3}){2,}$")
_PLAIN = re.compile(r"^(?:\d+\.?\d*|\.\d+)$")


class _Ambiguous(ValueError):
    pass


def _to_float(text: str) -> float:
    """Unsigned number with the separator rules of the module docstring."""
    if "," in text:
        if not _US_GROUPED.match(text):
            raise _Ambiguous(text)
        text = text.replace(",", "")
    if not _PLAIN.match(text):
        # e.g. 1.234.567 (dots as grouping) or 1.2.3: no single reading
        raise _Ambiguous(text)
    return float(text)


@dataclass(frozen=True)
class ParsedQuantity:
    """Value in the column's imperial unit (ft / SF / CF) and the issue, if any.

    ``issue`` is None for a clean value (and for an empty cell), else one of :data:`ISSUES`.
    Only ``metric_converted`` values carry a non-zero value besides clean ones.
    """

    value: float
    issue: str | None = None


def _feet_inch(body: str) -> float | None:
    m = _FEET_INCH.match(body)
    if not m or '"' not in body and "'" not in body:
        return None
    feet, inch = m.group("feet", "inch")
    num, den = m.group("num", "den") if m.group("num") else m.group("num2", "den2")
    if feet is None and inch is None and num is None:
        return None
    value = _to_float(feet) if feet is not None else 0.0
    inches = _to_float(inch) if inch is not None else 0.0
    if num is not None:
        if int(den) == 0:
            return None
        inches += int(num) / int(den)
    return value + inches / 12


def parse_quantity(raw: str | None, kind: str) -> ParsedQuantity:
    """Parse one export cell of a ``kind`` column (:data:`LENGTH`, :data:`AREA`,
    :data:`VOLUME`) into ft / SF / CF. Empty or blank → 0 without an issue."""
    text = (raw or "").strip()
    if not text:
        return ParsedQuantity(0.0)
    sign = 1.0
    body = text
    if body[0] in "-−":
        sign, body = -1.0, body[1:].lstrip()
    elif body[0] == "+":
        body = body[1:].lstrip()
    try:
        if "'" in body or '"' in body:
            if kind != LENGTH:
                return ParsedQuantity(0.0, UNIT_MISMATCH)
            feet = _feet_inch(body)
            if feet is None:
                return ParsedQuantity(0.0, NO_NUMBER)
            return ParsedQuantity(sign * feet)
        m = _NUMBER_WITH_SUFFIX.match(body)
        if not m:
            return ParsedQuantity(0.0, NO_NUMBER)
        number = _to_float(m.group("num"))
    except _Ambiguous:
        return ParsedQuantity(0.0, AMBIGUOUS_SEPARATOR)
    suffix = re.sub(r"\s+", "", m.group("unit")).lower()
    if not suffix:
        return ParsedQuantity(sign * number)
    unit = _UNITS.get(suffix)
    if unit is None:
        return ParsedQuantity(0.0, UNKNOWN_UNIT)
    unit_kind, factor, metric = unit
    if unit_kind != kind:
        return ParsedQuantity(0.0, UNIT_MISMATCH)
    return ParsedQuantity(sign * number * factor, METRIC_CONVERTED if metric else None)


@dataclass
class _ColumnLog:
    count: int = 0
    by_issue: dict[str, int] = field(default_factory=dict)
    examples: list[dict[str, str]] = field(default_factory=list)


class QuantityParseLog:
    """Parse issues per column: count, count per issue, up to :data:`MAX_EXAMPLES` distinct
    raw strings (the cell text only, no ElementIds or other row data)."""

    def __init__(self) -> None:
        self._columns: dict[str, _ColumnLog] = {}

    def parse(self, raw: str | None, kind: str, column: str) -> float:
        """:func:`parse_quantity` that records the issue under ``column``; returns the value."""
        parsed = parse_quantity(raw, kind)
        if parsed.issue is not None:
            self.record(column, parsed.issue, (raw or "").strip())
        return parsed.value

    def record(self, column: str, issue: str, raw: str) -> None:
        log = self._columns.setdefault(column, _ColumnLog())
        log.count += 1
        log.by_issue[issue] = log.by_issue.get(issue, 0) + 1
        example = {"value": raw, "issue": issue}
        if len(log.examples) < MAX_EXAMPLES and example not in log.examples:
            log.examples.append(example)

    @property
    def total(self) -> int:
        return sum(log.count for log in self._columns.values())

    def block(self) -> dict:
        """``{total, columns: {column: {count, by_issue, examples}}}`` (JSON-ready)."""
        return {
            "total": self.total,
            "columns": {
                name: {
                    "count": log.count,
                    "by_issue": dict(sorted(log.by_issue.items())),
                    "examples": list(log.examples),
                }
                for name, log in sorted(self._columns.items())
            },
        }
