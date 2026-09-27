"""P3.11 / P4.5: the tolerant quantity parser (engines/common/quantities.py). Invented values."""

import pytest

from engines.common.quantities import (
    AMBIGUOUS_SEPARATOR,
    AREA,
    LENGTH,
    MAX_EXAMPLES,
    METRIC_CONVERTED,
    NO_NUMBER,
    UNIT_MISMATCH,
    UNKNOWN_UNIT,
    VOLUME,
    QuantityParseLog,
    parse_quantity,
)

FT_PER_M = 1 / 0.3048


def _ok(text, kind, expected):
    parsed = parse_quantity(text, kind)
    assert parsed.issue is None, (text, parsed)
    assert parsed.value == pytest.approx(expected, abs=1e-12), text


# ── new format: plain decimals in the column's imperial unit ─────────────────

@pytest.mark.parametrize("text, expected", [
    ("312.5", 312.5), ("12", 12.0), ("0", 0.0), (".5", 0.5), ("12.", 12.0),
    ("0.008333", 0.008333), ("-3.25", -3.25), ("+4", 4.0), ("−2", -2.0),
])
@pytest.mark.parametrize("kind", [LENGTH, AREA, VOLUME])
def test_plain_decimals(text, expected, kind):
    _ok(text, kind, expected)


# ── feet-inch display strings ────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("9' - 7 3/4\"", 9 + 7.75 / 12),
    ("9'-7 3/4\"", 9 + 7.75 / 12),
    ("9' 7 3/4\"", 9 + 7.75 / 12),
    ("9'  -  7  3 / 4 \"", 9 + 7.75 / 12),
    ("136' - 0\"", 136.0),
    ("10' - 6\"", 10.5),
    ("10' - 6.5\"", 10 + 6.5 / 12),
    ("0' - 0 1/2\"", 0.5 / 12),
    ("12'", 12.0),
    ("12' - 0 15/16\"", 12 + (15 / 16) / 12),
    ("7 3/4\"", 7.75 / 12),
    ("1/2\"", 0.5 / 12),
    ("11\"", 11 / 12),
    ("-2' - 6\"", -2.5),
    ("-0' - 6\"", -0.5),
    ("-7 3/4\"", -7.75 / 12),
    ("1,234.5' - 6\"", 1235.0),
    ("  9' - 7 3/4\"  ", 9 + 7.75 / 12),
])
def test_feet_inch(text, expected):
    _ok(text, LENGTH, expected)


def test_whole_inches_are_bit_identical_to_the_legacy_parser():
    """Only fractional inches change the value (the Island delta is only those lines)."""
    from engines.tvd.loading import parse_qty_str

    for text in ("136' - 0\"", "10' - 6\"", "125' - 8\"", "3' - 11\"", "4' - 0\"", "10' - 6.5\""):
        assert parse_quantity(text, LENGTH).value == parse_qty_str(text), text
    assert parse_qty_str("9' - 7 3/4\"") == 9.0  # the P3.11 bug, kept in legacy mode


# ── unit suffixes ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, kind, expected", [
    ("6590 SF", AREA, 6590.0),
    ("6590SF", AREA, 6590.0),
    ("6590 sf", AREA, 6590.0),
    ("12.5 ft²", AREA, 12.5),
    ("12.5 ft2", AREA, 12.5),
    ("12.5 sq ft", AREA, 12.5),
    ("42.75 CF", VOLUME, 42.75),
    ("42.75 ft³", VOLUME, 42.75),
    ("42.75 cu ft", VOLUME, 42.75),
    ("88 LF", LENGTH, 88.0),
    ("88 ft", LENGTH, 88.0),
    ("6 in", LENGTH, 0.5),
    ("-5 SF", AREA, -5.0),
])
def test_imperial_suffixes(text, kind, expected):
    _ok(text, kind, expected)


# ── thousands and decimal separators ─────────────────────────────────────────

@pytest.mark.parametrize("text, kind, expected", [
    ("1,234,567", AREA, 1_234_567.0),
    ("1,234.5 SF", AREA, 1234.5),
    ("12,345.67 CF", VOLUME, 12345.67),
    ("-1,234,567.25", AREA, -1_234_567.25),
])
def test_unambiguous_thousands_separator(text, kind, expected):
    _ok(text, kind, expected)


@pytest.mark.parametrize("text", [
    "1,234",        # 1234 or 1.234?
    "1,000 SF",
    "1.234,5",      # European grouping + decimal comma
    "12,5",         # decimal comma
    "12,50 SF",
    "1,23,456.7",   # malformed grouping
    "1.234.567",    # dots as grouping
    "1.2.3",
])
def test_ambiguous_separator_is_not_guessed(text):
    parsed = parse_quantity(text, AREA)
    assert (parsed.value, parsed.issue) == (0.0, AMBIGUOUS_SEPARATOR)


def test_ambiguous_separator_in_feet_inch():
    parsed = parse_quantity("1,234' - 6\"", LENGTH)
    assert (parsed.value, parsed.issue) == (0.0, AMBIGUOUS_SEPARATOR)


# ── metric display strings: converted and flagged ────────────────────────────

@pytest.mark.parametrize("text, kind, expected", [
    ("3 m", LENGTH, 3 * FT_PER_M),
    ("3000 mm", LENGTH, 3 * FT_PER_M),
    ("300 cm", LENGTH, 3 * FT_PER_M),
    ("612 m²", AREA, 612 * FT_PER_M ** 2),
    ("612 m2", AREA, 612 * FT_PER_M ** 2),
    ("1.5 m³", VOLUME, 1.5 * FT_PER_M ** 3),
    ("1.5m3", VOLUME, 1.5 * FT_PER_M ** 3),
    ("-2 m", LENGTH, -2 * FT_PER_M),
])
def test_metric_is_converted_and_flagged(text, kind, expected):
    parsed = parse_quantity(text, kind)
    assert parsed.issue == METRIC_CONVERTED
    assert parsed.value == pytest.approx(expected, rel=1e-12)


def test_metric_is_never_read_as_feet():
    assert parse_quantity("612 m²", AREA).value == pytest.approx(6587.5, abs=0.1)
    assert parse_quantity("10 m", LENGTH).value == pytest.approx(32.8084, abs=1e-4)


# ── not counted, with an issue ───────────────────────────────────────────────

@pytest.mark.parametrize("text, kind, issue", [
    ("12 kg", AREA, UNKNOWN_UNIT),
    ("12 yd", LENGTH, UNKNOWN_UNIT),
    ("12 SF extra", AREA, UNKNOWN_UNIT),
    ("12 SF", LENGTH, UNIT_MISMATCH),
    ("12 CF", AREA, UNIT_MISMATCH),
    ("12 m²", VOLUME, UNIT_MISMATCH),
    ("9' - 6\"", AREA, UNIT_MISMATCH),
    ("n/a", AREA, NO_NUMBER),
    ("SF", AREA, NO_NUMBER),
    ("-", LENGTH, NO_NUMBER),
    ("'", LENGTH, NO_NUMBER),
    ("\"", LENGTH, NO_NUMBER),
    ("1/0\"", LENGTH, NO_NUMBER),
    ("9' - 7 3/4", LENGTH, NO_NUMBER),  # inch mark missing
])
def test_unreadable_values_count_zero_with_an_issue(text, kind, issue):
    parsed = parse_quantity(text, kind)
    assert (parsed.value, parsed.issue) == (0.0, issue)


@pytest.mark.parametrize("text", ["", " ", "\t", "  \n ", None])
@pytest.mark.parametrize("kind", [LENGTH, AREA, VOLUME])
def test_empty_is_zero_without_an_issue(text, kind):
    parsed = parse_quantity(text, kind)
    assert (parsed.value, parsed.issue) == (0.0, None)


# ── the per-column log ───────────────────────────────────────────────────────

def test_parse_log_block():
    log = QuantityParseLog()
    assert log.parse("12 kg", AREA, "Area") == 0.0
    assert log.parse("12 kg", AREA, "Area") == 0.0
    assert log.parse("1,234", AREA, "Area") == 0.0
    assert log.parse("3 m", LENGTH, "Length") == pytest.approx(3 * FT_PER_M)
    assert log.parse("9' - 7 3/4\"", LENGTH, "Length") == pytest.approx(9 + 7.75 / 12)
    assert log.parse("", VOLUME, "Volume") == 0.0
    assert log.block() == {
        "total": 4,
        "columns": {
            "Area": {
                "count": 3,
                "by_issue": {AMBIGUOUS_SEPARATOR: 1, UNKNOWN_UNIT: 2},
                "examples": [{"value": "12 kg", "issue": UNKNOWN_UNIT},
                             {"value": "1,234", "issue": AMBIGUOUS_SEPARATOR}],
            },
            "Length": {
                "count": 1,
                "by_issue": {METRIC_CONVERTED: 1},
                "examples": [{"value": "3 m", "issue": METRIC_CONVERTED}],
            },
        },
    }


def test_parse_log_keeps_at_most_20_distinct_examples():
    log = QuantityParseLog()
    for i in range(50):
        log.parse(f"{i} kg", AREA, "Area")
    column = log.block()["columns"]["Area"]
    assert column["count"] == 50
    assert len(column["examples"]) == MAX_EXAMPLES == 20
    assert column["examples"][0] == {"value": "0 kg", "issue": UNKNOWN_UNIT}
