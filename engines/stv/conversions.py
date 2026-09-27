"""P3.6: quantities, named conversions and numeric keyword tests for the STV mapping table.

The mapping table (``stv_mapping.csv``, see :mod:`engines.stv.mapping`) only *names* what is
defined here; there are no free formulas in the table. Parameters that are team assumptions
(densities, fitting factors, door thickness, duct gauges) are given in the table, never as
code defaults.

- **Quantity fields** (``quantity_field``): what is read from a Revit export row, in the
  export's units: ``area`` (SF), ``volume`` (CF), ``length`` (FT), ``count`` (1 per element),
  ``weight`` (kg, ``Weight`` else ``Unit Weight``), ``airflow`` (m³/s).
- **Conversions** (``conversion``): ``cf_to_cy``, ``density_kg_per_cf=<x>``,
  ``door_area(thickness_in=<x>)``, ``duct_equivalent_length``,
  ``duct_weight_estimate(surface_factor=..;density_kg_per_m3=..;gauge_m=a/b/c;
  gauge_limits_m=x/y)``. The last three have fallbacks; a quantity that comes from a
  fallback is flagged as *estimated*.
- **Numeric tests** (in ``keyword``): ``diameter_in<=15`` etc. on named element values.

The parsing helpers and the fallback logic come unchanged from the former Island importers
(``revit_architecture.py``, ``revit_structural.py``, ``revit_mep.py`` before P3.6).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

Row = dict[str, str]

# ---------------------------------------------------------------------------
# Parsing Revit export values
# ---------------------------------------------------------------------------


def parse_number(raw_value: str | None) -> float:
    """``'6848 SF'`` → 6848.0; first token, else the first number in the text; blank → 0."""
    text = (raw_value or "").strip()
    if not text:
        return 0.0
    cleaned = text.replace(",", "")
    token = cleaned.split()[0].strip("'\"")
    if token:
        try:
            return float(token)
        except ValueError:
            pass
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group(0)) if match else 0.0


def parse_length_feet(raw_value: str | None) -> float:
    """Revit feet-inches (``3' - 6 1/2"``, ``11"``) → feet; a bare number is feet."""
    text = (raw_value or "").strip()
    if not text:
        return 0.0
    feet_match = re.search(r"(-?\d+)\s*'", text)
    inches_match = re.search(r"(-?\d+(?:\s+\d+/\d+|\.\d+)?)\s*\"", text)
    if not feet_match and not inches_match:
        return parse_number(text)
    feet = float(feet_match.group(1)) if feet_match else 0.0
    inches = _parse_inches_fraction(inches_match.group(1)) if inches_match else 0.0
    return feet + inches / 12.0


def _parse_inches_fraction(text: str) -> float:
    value = text.strip()
    if " " in value:
        whole, fraction = value.split(" ", 1)
        return float(whole) + _parse_fraction(fraction)
    if "/" in value:
        return _parse_fraction(value)
    return float(value)


def _parse_fraction(value: str) -> float:
    numerator, denominator = value.split("/", 1)
    denominator_value = float(denominator)
    if math.isclose(denominator_value, 0.0):
        return 0.0
    return float(numerator) / denominator_value


def _extract_snapshot_value(snapshot: str, parameter_name: str) -> str:
    prefix = f"{parameter_name}="
    for part in snapshot.split(" | "):
        if part.startswith(prefix):
            return part[len(prefix):]
    return ""


def _extract_inches(text: str | None) -> float:
    raw = (text or "").strip()
    if not raw:
        return 0.0
    values = re.findall(r"(\d+(?:\.\d+)?)\s*\"", raw)
    if values:
        return max(float(value) for value in values)
    metric = re.findall(r"(\d+(?:\.\d+)?)", raw)
    if metric:
        return max(float(value) for value in metric)
    return 0.0


def _extract_size_pair_inches(text: str | None) -> tuple[float, float]:
    raw = (text or "").strip()
    if not raw:
        return 0.0, 0.0
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*\"", raw)
    if len(matches) >= 2:
        return float(matches[0]), float(matches[1])
    metric_matches = re.findall(r"(\d+(?:\.\d+)?)", raw)
    if len(metric_matches) >= 2:
        return float(metric_matches[0]), float(metric_matches[1])
    return 0.0, 0.0


def _parse_flow_m3s(raw_value: str | None) -> float:
    text = (raw_value or "").strip().lower()
    if not text:
        return 0.0
    value = parse_number(text)
    if value <= 0:
        return 0.0
    if "/h" in text:
        return value / 3600.0
    return value


# ---------------------------------------------------------------------------
# Quantity fields
# ---------------------------------------------------------------------------


def area_sf(row: Row) -> float:
    return parse_number(row.get("Area"))


def volume_cf(row: Row) -> float:
    return parse_number(row.get("Volume"))


def length_ft(row: Row) -> float:
    return parse_length_feet(row.get("Length"))


def weight_kg(row: Row) -> float:
    """``Weight``, else ``Unit Weight`` (the exports give kg)."""
    for name in ("Weight", "Unit Weight"):
        value = parse_number(row.get(name))
        if value > 0:
            return value
    return 0.0


def airflow_m3s(row: Row) -> float:
    """Airflow in m³/s: ``Airflow``/``Flow``, else the snapshot flows, else ``Connector Flow``
    (lower fidelity; used as the last fallback, as before P3.6)."""
    for name in ("Airflow", "Flow"):
        value = _parse_flow_m3s(row.get(name))
        if value > 0:
            return value
    snapshot = row.get("Parameter Snapshot", "") or ""
    for key in ("Supply Air Outlet Flow", "Supply Air Inlet Flow", "Return Air Inlet Flow",
                "Flow"):
        value = _parse_flow_m3s(_extract_snapshot_value(snapshot, key))
        if value > 0:
            return value
    connector_flow = parse_number(row.get("Connector Flow"))
    return connector_flow if connector_flow > 0 else 0.0


# quantity_field → (reader, unit of the raw quantity)
QUANTITY_FIELDS: dict[str, tuple[Callable[[Row], float], str]] = {
    "area": (area_sf, "sf"),
    "volume": (volume_cf, "cf"),
    "length": (length_ft, "ft"),
    "count": (lambda row: 1.0, "count"),
    "weight": (weight_kg, "kg"),
    "airflow": (airflow_m3s, "m^3/s"),
}

# ---------------------------------------------------------------------------
# Numeric tests (keyword terms such as ``diameter_in<=15``)
# ---------------------------------------------------------------------------


def nominal_diameter_in(row: Row) -> float | None:
    """Nominal duct diameter in inches: ``Diameter``/``Size``/``Width``/``Height``, the
    snapshot's hydraulic diameter, else the equivalent diameter 2wh/(w+h) of the snapshot's
    duct width/height. ``None`` when unknown (before P3.6 the importer then assumed 12")."""
    for name in ("Diameter", "Size", "Width", "Height"):
        diameter = _extract_inches(row.get(name))
        if diameter > 0:
            return diameter
    snapshot = row.get("Parameter Snapshot", "") or ""
    hydraulic = _extract_snapshot_value(snapshot, "Hydraulic Diameter")
    if hydraulic:
        diameter = _extract_inches(hydraulic)
        if diameter > 0:
            return diameter
    width_in = _extract_inches(_extract_snapshot_value(snapshot, "Duct Width"))
    height_in = _extract_inches(_extract_snapshot_value(snapshot, "Duct Height"))
    if width_in > 0 and height_in > 0:
        return 2 * width_in * height_in / (width_in + height_in)
    if width_in > 0:
        return width_in
    if height_in > 0:
        return height_in
    return None


NUMERIC_TESTS: dict[str, Callable[[Row], float | None]] = {
    "diameter_in": nominal_diameter_in,
}

# ---------------------------------------------------------------------------
# Named conversions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Quantity:
    amount: float
    estimated: bool = False


@dataclass(frozen=True)
class ConversionDef:
    """A named conversion: which quantity field it takes, its parameters and output unit."""

    name: str
    quantity_field: str
    unit: str
    params: tuple[str, ...] = ()
    list_params: tuple[str, ...] = ()  # parameters given as a/b/c
    apply: Callable[[Row, dict[str, float | tuple[float, ...]]], Quantity] = field(
        default=lambda row, p: Quantity(0.0), compare=False
    )
    description: str = ""


CF_TO_CY = 1.0 / 27.0


def _cf_to_cy(row: Row, p) -> Quantity:
    return Quantity(volume_cf(row) * CF_TO_CY)


def _density(row: Row, p) -> Quantity:
    return Quantity(volume_cf(row) * p["density_kg_per_cf"])


def _door_area(row: Row, p) -> Quantity:
    area = area_sf(row)
    if area > 0:
        return Quantity(area)
    width_ft = parse_length_feet(row.get("Width"))
    height_ft = parse_length_feet(row.get("Height"))
    if width_ft > 0 and height_ft > 0:
        return Quantity(width_ft * height_ft, estimated=True)
    volume = volume_cf(row)
    if volume > 0 and width_ft > 0:
        return Quantity(volume / (p["thickness_in"] / 12.0), estimated=True)
    return Quantity(0.0)


def _duct_equivalent_length(row: Row, p) -> Quantity:
    length = length_ft(row)
    if length > 0:
        return Quantity(length)
    area = area_sf(row)
    volume = volume_cf(row)
    if area > 0 and volume > 0:
        return Quantity(volume / area, estimated=True)
    if volume > 0:
        return Quantity(volume ** (1.0 / 3.0), estimated=True)
    return Quantity(0.0)


def _rectangular_dimensions_m(row: Row) -> tuple[float, float]:
    width_in = _extract_inches(row.get("Width"))
    height_in = _extract_inches(row.get("Height"))
    snapshot = row.get("Parameter Snapshot", "") or ""
    if width_in <= 0:
        width_in = _extract_inches(_extract_snapshot_value(snapshot, "Duct Width"))
    if height_in <= 0:
        height_in = _extract_inches(_extract_snapshot_value(snapshot, "Duct Height"))
    if width_in <= 0 or height_in <= 0:
        parsed_width_in, parsed_height_in = _extract_size_pair_inches(row.get("Size"))
        if width_in <= 0:
            width_in = parsed_width_in
        if height_in <= 0:
            height_in = parsed_height_in
    return width_in * 0.0254, height_in * 0.0254


def _duct_length_m(row: Row) -> float:
    length = parse_length_feet(row.get("Length"))
    if length > 0:
        return length * 0.3048
    snapshot = row.get("Parameter Snapshot", "") or ""
    for key in ("Length", "Duct Length", "Computed Length", "Length 1", "Duct Length 1"):
        candidate_ft = parse_length_feet(_extract_snapshot_value(snapshot, key))
        if candidate_ft > 0:
            return candidate_ft * 0.3048
    volume = volume_cf(row)
    width_m, height_m = _rectangular_dimensions_m(row)
    if volume > 0 and width_m > 0 and height_m > 0:
        return volume * 0.0283168 / (width_m * height_m)
    return 0.0


def _duct_weight_estimate(row: Row, p) -> Quantity:
    weight = weight_kg(row)
    if weight > 0:
        return Quantity(weight)
    width_m, height_m = _rectangular_dimensions_m(row)
    length_m = _duct_length_m(row)
    if width_m <= 0 or height_m <= 0 or length_m <= 0:
        return Quantity(0.0)
    largest_m = max(width_m, height_m)
    gauges_m, limits_m = p["gauge_m"], p["gauge_limits_m"]
    thickness_m = gauges_m[-1]
    for gauge, limit in zip(gauges_m, limits_m, strict=False):
        if largest_m <= limit:
            thickness_m = gauge
            break
    sheet_area_m2 = p["surface_factor"] * 2.0 * (width_m + height_m) * length_m
    return Quantity(sheet_area_m2 * thickness_m * p["density_kg_per_m3"], estimated=True)


CONVERSIONS: dict[str, ConversionDef] = {c.name: c for c in (
    ConversionDef("cf_to_cy", "volume", "cy", apply=_cf_to_cy,
                  description="volume CF / 27 → CY"),
    ConversionDef("density_kg_per_cf", "volume", "kg", ("density_kg_per_cf",),
                  apply=_density, description="volume CF × density → kg"),
    ConversionDef("door_area", "area", "sf", ("thickness_in",), apply=_door_area,
                  description="Area; else Width × Height; else Volume / thickness "
                              "(fallbacks are estimates)"),
    ConversionDef("duct_equivalent_length", "length", "ft", apply=_duct_equivalent_length,
                  description="Length; else Volume / Area; else Volume^(1/3) "
                              "(fallbacks are estimates)"),
    ConversionDef("duct_weight_estimate", "weight", "kg",
                  ("surface_factor", "density_kg_per_m3", "gauge_m", "gauge_limits_m"),
                  ("gauge_m", "gauge_limits_m"), apply=_duct_weight_estimate,
                  description="Weight; else sheet weight of a rectangular duct: surface_factor "
                              "× perimeter × length × sheet gauge × density (estimate). The "
                              "gauge is the first gauge_m whose gauge_limits_m ≥ the larger "
                              "side (m), else the last gauge_m."),
)}

_PLAIN = r"[0-9]+(?:\.[0-9]+)?"
_CONVERSION_RE = re.compile(r"^([a-z_][a-z0-9_]*)(?:=(.+)|\((.*)\))?$")


class ConversionSpecError(ValueError):
    pass


@dataclass(frozen=True)
class ConversionSpec:
    name: str
    params: tuple[tuple[str, float | tuple[float, ...]], ...] = ()

    @property
    def definition(self) -> ConversionDef:
        return CONVERSIONS[self.name]

    def apply(self, row: Row) -> Quantity:
        return self.definition.apply(row, dict(self.params))


def _parse_param_value(name: str, raw: str, is_list: bool) -> float | tuple[float, ...]:
    raw = raw.strip()
    parts = raw.split("/") if is_list else [raw]
    values = []
    for part in parts:
        part = part.strip()
        if not re.fullmatch(_PLAIN, part):
            raise ConversionSpecError(
                f"parameter {name}: '{raw}' is not a plain positive decimal"
                + (" list (a/b/c)" if is_list else "") + "."
            )
        values.append(float(part))
    if not is_list and values[0] <= 0:
        raise ConversionSpecError(f"parameter {name} must be > 0.")
    return tuple(values) if is_list else values[0]


def parse_conversion(spec: str) -> ConversionSpec | None:
    """``''`` → None; ``cf_to_cy``; ``density_kg_per_cf=19.43`` (one-parameter shorthand);
    ``door_area(thickness_in=1.75)``; ``name(a=1;b=2/3)``. Raises ConversionSpecError."""
    text = spec.strip()
    if not text:
        return None
    m = _CONVERSION_RE.match(text.replace(" ", ""))
    if not m:
        raise ConversionSpecError(
            f"'{spec}' is not a conversion: use name, name=value or name(key=value;...)."
        )
    name, shorthand, paren = m.groups()
    if name not in CONVERSIONS:
        raise ConversionSpecError(
            f"unknown conversion '{name}'; known: {', '.join(sorted(CONVERSIONS))}."
        )
    definition = CONVERSIONS[name]
    given: dict[str, str] = {}
    if shorthand is not None:
        if len(definition.params) != 1:
            raise ConversionSpecError(
                f"{name} takes {len(definition.params)} parameters; write "
                f"{name}({';'.join(p + '=...' for p in definition.params)})."
                if definition.params else f"{name} takes no parameters."
            )
        given[definition.params[0]] = shorthand
    elif paren is not None and paren.strip():
        for item in paren.split(";"):
            if "=" not in item:
                raise ConversionSpecError(f"{name}: '{item}' is not key=value.")
            key, value = item.split("=", 1)
            if key in given:
                raise ConversionSpecError(f"{name}: parameter {key} given twice.")
            given[key] = value
    unknown = sorted(set(given) - set(definition.params))
    if unknown:
        raise ConversionSpecError(
            f"{name}: unknown parameter(s) {', '.join(unknown)}; expected "
            f"{', '.join(definition.params) or 'none'}."
        )
    missing = [p for p in definition.params if p not in given]
    if missing:
        raise ConversionSpecError(
            f"{name}: missing parameter(s) {', '.join(missing)} (no defaults: team "
            "assumptions belong in the mapping file)."
        )
    params = tuple(
        (p, _parse_param_value(p, given[p], p in definition.list_params))
        for p in definition.params
    )
    if name == "duct_weight_estimate":
        values = dict(params)
        if len(values["gauge_m"]) != len(values["gauge_limits_m"]) + 1:
            raise ConversionSpecError(
                "duct_weight_estimate: gauge_m needs one value more than gauge_limits_m "
                "(the last gauge applies above the last limit)."
            )
    return ConversionSpec(name, params)


def quantity(row: Row, quantity_field: str, conversion: ConversionSpec | None) -> Quantity:
    if conversion is not None:
        return conversion.apply(row)
    reader, _unit = QUANTITY_FIELDS[quantity_field]
    return Quantity(reader(row))


def output_unit(quantity_field: str, conversion: ConversionSpec | None) -> str:
    if conversion is not None:
        return conversion.definition.unit
    return QUANTITY_FIELDS[quantity_field][1]
