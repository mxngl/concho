from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

IMPACT_KEYS = ("carbon", "energy", "water", "ozone")


@dataclass(slots=True)
class ImpactVector:
    carbon: float = 0.0
    energy: float = 0.0
    water: float = 0.0
    ozone: float = 0.0

    def __add__(self, other: ImpactVector) -> ImpactVector:
        return ImpactVector(
            carbon=self.carbon + other.carbon,
            energy=self.energy + other.energy,
            water=self.water + other.water,
            ozone=self.ozone + other.ozone,
        )

    def scale(self, factor: float) -> ImpactVector:
        return ImpactVector(
            carbon=self.carbon * factor,
            energy=self.energy * factor,
            water=self.water * factor,
            ozone=self.ozone * factor,
        )

    def get(self, key: str) -> float:
        return getattr(self, key)

    def to_dict(self) -> dict[str, float]:
        return {key: self.get(key) for key in IMPACT_KEYS}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ImpactVector:
        return cls(
            carbon=float(payload.get("carbon", 0.0)),
            energy=float(payload.get("energy", 0.0)),
            water=float(payload.get("water", 0.0)),
            ozone=float(payload.get("ozone", 0.0)),
        )


@dataclass(slots=True)
class ImpactBreakdown:
    embodied_materials: ImpactVector = field(default_factory=ImpactVector)
    embodied_transport: ImpactVector = field(default_factory=ImpactVector)
    embodied_construction: ImpactVector = field(default_factory=ImpactVector)
    use_electricity: ImpactVector = field(default_factory=ImpactVector)
    use_heating: ImpactVector = field(default_factory=ImpactVector)
    use_water: ImpactVector = field(default_factory=ImpactVector)

    @property
    def embodied(self) -> ImpactVector:
        return (
            self.embodied_materials
            + self.embodied_transport
            + self.embodied_construction
        )

    @property
    def use_phase(self) -> ImpactVector:
        return self.use_electricity + self.use_heating + self.use_water

    @property
    def life_cycle(self) -> ImpactVector:
        return self.embodied + self.use_phase

    def __add__(self, other: ImpactBreakdown) -> ImpactBreakdown:
        return ImpactBreakdown(
            embodied_materials=self.embodied_materials + other.embodied_materials,
            embodied_transport=self.embodied_transport + other.embodied_transport,
            embodied_construction=self.embodied_construction + other.embodied_construction,
            use_electricity=self.use_electricity + other.use_electricity,
            use_heating=self.use_heating + other.use_heating,
            use_water=self.use_water + other.use_water,
        )

    def to_dict(self) -> dict[str, dict[str, float]]:
        return {
            "embodied_materials": self.embodied_materials.to_dict(),
            "embodied_transport": self.embodied_transport.to_dict(),
            "embodied_construction": self.embodied_construction.to_dict(),
            "use_electricity": self.use_electricity.to_dict(),
            "use_heating": self.use_heating.to_dict(),
            "use_water": self.use_water.to_dict(),
            "embodied": self.embodied.to_dict(),
            "use_phase": self.use_phase.to_dict(),
            "life_cycle": self.life_cycle.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ImpactBreakdown:
        return cls(
            embodied_materials=ImpactVector.from_dict(payload.get("embodied_materials", {})),
            embodied_transport=ImpactVector.from_dict(payload.get("embodied_transport", {})),
            embodied_construction=ImpactVector.from_dict(payload.get("embodied_construction", {})),
            use_electricity=ImpactVector.from_dict(payload.get("use_electricity", {})),
            use_heating=ImpactVector.from_dict(payload.get("use_heating", {})),
            use_water=ImpactVector.from_dict(payload.get("use_water", {})),
        )


@dataclass(slots=True)
class ConstructionItem:
    assembly: str
    material_type: str
    amount: float
    # P3.6: part of ``amount`` that comes from a fallback estimate of the mapping
    # (engines/stv/conversions.py); reporting only, not used in the calculation.
    estimated_amount: float = 0.0
    # P3.7: part of ``amount`` mapped by a proxy rule (mapping note "proxy"); reporting only.
    proxy_amount: float = 0.0
    # P3.8: "project_config" for stv.construction_items of the config (taken once when
    # results are combined), else "input".
    origin: str = "input"


@dataclass(slots=True)
class CogenerationInputs:
    fuel_type: str | None = None
    electricity_kwh: float = 0.0
    heating_mj: float = 0.0
    cooling_kwh: float = 0.0
    electricity_split: float = 0.0
    heating_split: float = 0.0
    cooling_split: float = 0.0


def _all_zero(values: Any) -> bool:
    """True if no number in the (nested) use-phase inputs is non-zero; a stated urinal
    flow rate (even 0) counts as an input (decision D11)."""
    if isinstance(values, dict):
        return all(_all_zero(v) if k != "urinal_gpf" else v is None
                   for k, v in values.items())
    return not isinstance(values, (int, float)) or not values


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


@dataclass(slots=True)
class WaterUseInputs:
    toilet_gpf: float = 0.0
    # None = no urinals (course: blank cell, toilet factor 1.0); a number, including 0,
    # = course behaviour (non-blank cell, toilet factor 0.75). Decision D11.
    urinal_gpf: float | None = None
    wc_sink_gpm: float = 0.0
    lab_sink_gpm: float = 0.0
    kitchen_sink_gpm: float = 0.0
    shower_gpm: float = 0.0
    landscaping_gal: float = 0.0
    rainwater_collection_gal: float = 0.0


@dataclass(slots=True)
class UsePhaseInputs:
    electricity_from_grid_kwh: float = 0.0
    onsite_renewable_kwh: float = 0.0
    natural_gas_m3: float = 0.0
    cogeneration: CogenerationInputs = field(default_factory=CogenerationInputs)
    water_use: WaterUseInputs = field(default_factory=WaterUseInputs)


@dataclass(slots=True)
class STVInputs:
    team: str
    construction_items: list[ConstructionItem]
    use_phase: UsePhaseInputs = field(default_factory=UsePhaseInputs)

    def use_phase_status(self) -> dict[str, Any]:
        """P3.8: the use-phase status as far as the inputs show it (source ``input``).

        ``modeled`` is true when any input is non-zero or a urinal flow rate is stated;
        ``concho-stv --config`` replaces it with the config's explicit statement.
        """
        inputs = asdict(self.use_phase)
        all_zero = _all_zero(inputs)
        return {
            "modeled": not all_zero,
            "source": "input",
            "not_modeled_reason": "no use-phase inputs given" if all_zero else None,
            "all_zero": all_zero,
            "inputs": inputs,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> STVInputs:
        construction_items = [
            ConstructionItem(
                assembly=item["assembly"],
                material_type=item["material_type"],
                amount=float(item["amount"]),
                estimated_amount=float(item.get("estimated_amount", 0.0)),
                proxy_amount=float(item.get("proxy_amount", 0.0)),
                origin=item.get("origin", "input"),
            )
            for item in payload.get("construction_items", [])
        ]
        use_phase_payload = payload.get("use_phase", {})
        cogen_payload = use_phase_payload.get("cogeneration", {})
        water_payload = use_phase_payload.get("water_use", {})
        return cls(
            team=payload["team"],
            construction_items=construction_items,
            use_phase=UsePhaseInputs(
                electricity_from_grid_kwh=float(
                    use_phase_payload.get("electricity_from_grid_kwh", 0.0)
                ),
                onsite_renewable_kwh=float(
                    use_phase_payload.get("onsite_renewable_kwh", 0.0)
                ),
                natural_gas_m3=float(use_phase_payload.get("natural_gas_m3", 0.0)),
                cogeneration=CogenerationInputs(
                    fuel_type=cogen_payload.get("fuel_type"),
                    electricity_kwh=float(cogen_payload.get("electricity_kwh", 0.0)),
                    heating_mj=float(cogen_payload.get("heating_mj", 0.0)),
                    cooling_kwh=float(cogen_payload.get("cooling_kwh", 0.0)),
                    electricity_split=float(
                        cogen_payload.get("electricity_split", 0.0)
                    ),
                    heating_split=float(cogen_payload.get("heating_split", 0.0)),
                    cooling_split=float(cogen_payload.get("cooling_split", 0.0)),
                ),
                water_use=WaterUseInputs(
                    toilet_gpf=float(water_payload.get("toilet_gpf", 0.0)),
                    urinal_gpf=_optional_float(water_payload.get("urinal_gpf")),
                    wc_sink_gpm=float(water_payload.get("wc_sink_gpm", 0.0)),
                    lab_sink_gpm=float(water_payload.get("lab_sink_gpm", 0.0)),
                    kitchen_sink_gpm=float(water_payload.get("kitchen_sink_gpm", 0.0)),
                    shower_gpm=float(water_payload.get("shower_gpm", 0.0)),
                    landscaping_gal=float(water_payload.get("landscaping_gal", 0.0)),
                    rainwater_collection_gal=float(
                        water_payload.get("rainwater_collection_gal", 0.0)
                    ),
                ),
            ),
        )


@dataclass(slots=True)
class ConstructionImpactResult:
    assembly: str
    material_type: str
    amount: float
    unit_multiplier: float
    embodied_total: ImpactVector
    materials: ImpactVector
    transport: ImpactVector
    construction: ImpactVector
    estimated_amount: float = 0.0  # P3.6, see ConstructionItem
    proxy_amount: float = 0.0  # P3.7, see ConstructionItem
    origin: str = "input"  # P3.8, see ConstructionItem
    # P3.7: EPD source when the material is a custom material (not course data), else None.
    custom_material_source: str | None = None

    @property
    def custom_material(self) -> bool:
        return self.custom_material_source is not None

    @property
    def proxy_share(self) -> float:
        """Share of the item (and its impacts) that rests on proxy mapping rules."""
        return min(self.proxy_amount / self.amount, 1.0) if self.amount else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "assembly": self.assembly,
            "material_type": self.material_type,
            "amount": self.amount,
            "unit_multiplier": self.unit_multiplier,
            "embodied_total": self.embodied_total.to_dict(),
            "materials": self.materials.to_dict(),
            "transport": self.transport.to_dict(),
            "construction": self.construction.to_dict(),
            "estimated": self.estimated_amount > 0,
            "estimated_amount": self.estimated_amount,
            "custom_material": self.custom_material,
            "custom_material_source": self.custom_material_source,
            "proxy": self.proxy_amount > 0,
            "proxy_amount": self.proxy_amount,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConstructionImpactResult:
        return cls(
            assembly=payload["assembly"],
            material_type=payload["material_type"],
            amount=float(payload["amount"]),
            unit_multiplier=float(payload.get("unit_multiplier", 1.0)),
            embodied_total=ImpactVector.from_dict(payload.get("embodied_total", {})),
            materials=ImpactVector.from_dict(payload.get("materials", {})),
            transport=ImpactVector.from_dict(payload.get("transport", {})),
            construction=ImpactVector.from_dict(payload.get("construction", {})),
            estimated_amount=float(payload.get("estimated_amount", 0.0)),
            proxy_amount=float(payload.get("proxy_amount", 0.0)),
            custom_material_source=payload.get("custom_material_source"),
            origin=payload.get("origin", "input"),
        )


# ConstructionItem.origin of the config's stv.construction_items (P3.8).
CONFIG_ORIGIN = "project_config"


def _embodied_breakdown(items: list[ConstructionImpactResult]) -> ImpactBreakdown:
    out = ImpactBreakdown()
    for item in items:
        out.embodied_materials = out.embodied_materials + item.materials
        out.embodied_transport = out.embodied_transport + item.transport
        out.embodied_construction = out.embodied_construction + item.construction
    return out


def _single_use_phase(
    results: list[STVResults],
) -> tuple[STVResults | None, dict[str, Any] | None]:
    """The one use phase of the inputs (P3.8): inputs with a non-zero use phase must agree."""
    with_use = [r for r in results if any(r.breakdown.use_phase.to_dict().values())]
    if with_use:
        use = with_use[0].breakdown
        for other in with_use[1:]:
            if [v.to_dict() for v in (other.breakdown.use_electricity,
                                      other.breakdown.use_heating, other.breakdown.use_water)
                ] != [v.to_dict() for v in (use.use_electricity, use.use_heating,
                                            use.use_water)]:
                raise ValueError(
                    "Cannot combine STV results with different use phases; the use phase "
                    "belongs to the project, not to a trade. Combine with the project config "
                    "(concho-stv --combine-results ... --config project_config.json)."
                )
        status = dict(with_use[0].use_phase_status or {"modeled": True, "source": "input"})
        status["combined"] = (f"use phase taken once (found in {len(with_use)} of "
                              f"{len(results)} inputs)")
        return with_use[0], status
    statuses = [r.use_phase_status for r in results if r.use_phase_status]
    modeled = [s for s in statuses if s.get("modeled")]
    status = dict((modeled or statuses or [{}])[0])
    if statuses:
        status["combined"] = f"no input has a non-zero use phase ({len(results)} inputs)"
    return None, status or None


def _single_config_items(results: list[STVResults]) -> list[ConstructionImpactResult]:
    """The config items (origin project_config) of the inputs, once (P3.8)."""
    groups = [[i for i in r.construction_items if i.origin == CONFIG_ORIGIN] for r in results]
    groups = [g for g in groups if g]
    if not groups:
        return []

    def key(group):
        return sorted((i.assembly, i.material_type, i.amount) for i in group)

    if any(key(g) != key(groups[0]) for g in groups[1:]):
        raise ValueError(
            "Cannot combine STV results with different stv.construction_items of the config; "
            "combine with the project config (concho-stv --combine-results ... --config)."
        )
    return groups[0]


def _share(part: ImpactVector, whole: ImpactVector) -> dict[str, float | None]:
    return {key: (part.get(key) / whole.get(key) if whole.get(key) else None)
            for key in IMPACT_KEYS}


def data_flags(
    items: list[ConstructionImpactResult], breakdown: ImpactBreakdown
) -> dict[str, Any]:
    """P3.7: which results rest on custom materials (EPD values, not course data) or on
    proxies (mapping rules whose note says "proxy"), per assembly and in total, with the
    impacts that rest on them (embodied, same units as ``breakdown``)."""
    custom, proxy = ImpactVector(), ImpactVector()
    assemblies: dict[str, dict[str, Any]] = {}
    custom_materials: dict[tuple[str, str], dict[str, Any]] = {}
    proxy_items: list[dict[str, Any]] = []
    for item in items:
        block = assemblies.setdefault(item.assembly, {
            "embodied": ImpactVector(), "custom_material_embodied": ImpactVector(),
            "proxy_embodied": ImpactVector(), "custom_material": False, "proxy": False,
        })
        block["embodied"] = block["embodied"] + item.embodied_total
        if item.custom_material:
            block["custom_material"] = True
            custom = custom + item.embodied_total
            block["custom_material_embodied"] = (block["custom_material_embodied"]
                                                 + item.embodied_total)
            entry = custom_materials.setdefault((item.assembly, item.material_type), {
                "assembly": item.assembly, "material_type": item.material_type,
                "source": item.custom_material_source, "amount": 0.0,
                "embodied": ImpactVector(),
            })
            entry["amount"] += item.amount
            entry["embodied"] = entry["embodied"] + item.embodied_total
        if item.proxy_amount > 0:
            block["proxy"] = True
            part = item.embodied_total.scale(item.proxy_share)
            proxy = proxy + part
            block["proxy_embodied"] = block["proxy_embodied"] + part
            proxy_items.append({
                "assembly": item.assembly, "material_type": item.material_type,
                "amount": item.amount, "proxy_amount": item.proxy_amount,
                "embodied": part.to_dict(),
            })

    def summary(part: ImpactVector) -> dict[str, Any]:
        return {
            "embodied": part.to_dict(),
            "share_of_embodied": _share(part, breakdown.embodied),
            "share_of_life_cycle": _share(part, breakdown.life_cycle),
        }

    return {
        "custom_material": any(i.custom_material for i in items),
        "proxy": any(i.proxy_amount > 0 for i in items),
        "custom_materials": {
            **summary(custom),
            "materials": [{**m, "embodied": m["embodied"].to_dict()}
                          for m in custom_materials.values()],
        },
        "proxies": {**summary(proxy), "items": proxy_items},
        "by_assembly": {
            name: {
                "custom_material": b["custom_material"],
                "proxy": b["proxy"],
                "embodied": b["embodied"].to_dict(),
                "custom_material_embodied": b["custom_material_embodied"].to_dict(),
                "proxy_embodied": b["proxy_embodied"].to_dict(),
            }
            for name, b in assemblies.items()
        },
    }


@dataclass(slots=True)
class STVResults:
    team: str
    targets: ImpactVector
    breakdown: ImpactBreakdown
    construction_items: list[ConstructionImpactResult]
    lifetime_years: int
    # P3.6: mapping coverage of the Revit exports (engines/stv/coverage.py); None when the
    # items did not come from a mapped export.
    mapping_coverage: dict[str, Any] | None = None
    # P3.8: is the use phase modeled, where do its inputs come from (STVInputs.
    # use_phase_status, replaced by concho-stv --config); None in results from before P3.8.
    use_phase_status: dict[str, Any] | None = None
    # P3.9: rows dropped by the duplicate / Parts rule (D15, engines/common/dedup.py), and the
    # counted rows with the DNC marker (TVD skips them, STV counts them); None when the items
    # did not come from mapped exports.
    deduplication: dict[str, Any] | None = None
    dnc_rows: list[dict[str, Any]] | None = None

    def metric_summary(self) -> dict[str, dict[str, float | None]]:
        totals = self.breakdown.life_cycle
        summary: dict[str, dict[str, float | None]] = {}
        for key in IMPACT_KEYS:
            target = self.targets.get(key)
            project = totals.get(key)
            pct = None if target == 0 else project / target
            summary[key] = {"target": target, "project": project, "percent_of_target": pct}
        return summary

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "team": self.team,
            "targets": self.targets.to_dict(),
            "metric_summary": self.metric_summary(),
            "breakdown": self.breakdown.to_dict(),
            "construction_items": [item.to_dict() for item in self.construction_items],
            "lifetime_years": self.lifetime_years,
            "data_flags": data_flags(self.construction_items, self.breakdown),
        }
        if self.use_phase_status is not None:
            payload["use_phase_status"] = self.use_phase_status
        if self.mapping_coverage is not None:
            payload["mapping_coverage"] = self.mapping_coverage
        if self.deduplication is not None:
            payload["deduplication"] = self.deduplication
        if self.dnc_rows is not None:
            payload["dnc_rows"] = self.dnc_rows
        return payload

    def to_json_ready(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> STVResults:
        return cls(
            team=payload["team"],
            targets=ImpactVector.from_dict(payload.get("targets", {})),
            breakdown=ImpactBreakdown.from_dict(payload.get("breakdown", {})),
            construction_items=[
                ConstructionImpactResult.from_dict(item)
                for item in payload.get("construction_items", [])
            ],
            lifetime_years=int(payload.get("lifetime_years", 0)),
            mapping_coverage=payload.get("mapping_coverage"),
            use_phase_status=payload.get("use_phase_status"),
            deduplication=payload.get("deduplication"),
            dnc_rows=payload.get("dnc_rows"),
        )

    @classmethod
    def combine(
        cls,
        results: list[STVResults],
        *,
        team: str | None = None,
        project: STVResults | None = None,
    ) -> STVResults:
        """Combine per-trade (or per-export) results into one project result.

        Embodied impacts and line items are summed. The project-level parts are taken
        **once**, not summed per input (P3.8): the use phase and the ``stv.construction_items``
        of the config (line items with ``origin == "project_config"``, e.g. PV panels).

        - ``project`` given (``concho-stv --combine-results --config``): a result computed
          from the config alone (its use phase and config items); the inputs' use phase and
          config items are ignored.
        - otherwise: the inputs that have a use phase must all have the same one, which is
          taken once; the same holds for their config items. Different ones raise
          ``ValueError`` (combine with the config instead).
        """
        if not results:
            raise ValueError("At least one STV result is required to create a project STV.")

        first = results[0]
        combined_team = team or first.team
        combined_targets = first.targets
        combined_lifetime = first.lifetime_years
        combined_breakdown = ImpactBreakdown()
        combined_items: list[ConstructionImpactResult] = []

        for result in [*results, *([project] if project is not None else [])]:
            if result.team != first.team:
                raise ValueError(
                    "Cannot combine STV results from different teams: "
                    f"'{first.team}' and '{result.team}'."
                )
            if result.lifetime_years != combined_lifetime:
                raise ValueError(
                    "Cannot combine STV results with different lifetimes: "
                    f"{combined_lifetime} and {result.lifetime_years}."
                )
            if result.targets.to_dict() != combined_targets.to_dict():
                raise ValueError("Cannot combine STV results with different target values.")

        for result in results:
            own = [i for i in result.construction_items if i.origin != CONFIG_ORIGIN]
            if len(own) == len(result.construction_items):
                part = result.breakdown
            else:
                part = _embodied_breakdown(own)
            combined_breakdown = combined_breakdown + ImpactBreakdown(
                embodied_materials=part.embodied_materials,
                embodied_transport=part.embodied_transport,
                embodied_construction=part.embodied_construction,
            )
            combined_items.extend(own)

        if project is not None:
            use_source, config_items = project, [
                i for i in project.construction_items if i.origin == CONFIG_ORIGIN]
            status = dict(project.use_phase_status or {})
            status["combined"] = "use phase and config items taken once from the config"
        else:
            use_source, status = _single_use_phase(results)
            config_items = _single_config_items(results)
        if use_source is not None:
            combined_breakdown.use_electricity = use_source.breakdown.use_electricity
            combined_breakdown.use_heating = use_source.breakdown.use_heating
            combined_breakdown.use_water = use_source.breakdown.use_water
        if config_items:
            config_part = _embodied_breakdown(config_items)
            combined_breakdown.embodied_materials = (combined_breakdown.embodied_materials
                                                     + config_part.embodied_materials)
            combined_breakdown.embodied_transport = (combined_breakdown.embodied_transport
                                                     + config_part.embodied_transport)
            combined_breakdown.embodied_construction = (
                combined_breakdown.embodied_construction + config_part.embodied_construction)
            combined_items.extend(config_items)

        coverage_blocks = [r.mapping_coverage for r in results if r.mapping_coverage]
        mapping_coverage = None
        if coverage_blocks:
            from .coverage import merge_coverage

            mapping_coverage = merge_coverage(coverage_blocks)
        dnc_lists = [r.dnc_rows for r in results if r.dnc_rows is not None]
        return cls(
            team=combined_team,
            targets=combined_targets,
            breakdown=combined_breakdown,
            construction_items=combined_items,
            lifetime_years=combined_lifetime,
            mapping_coverage=mapping_coverage,
            use_phase_status=status,
            deduplication=combined_deduplication(results),
            dnc_rows=[row for rows in dnc_lists for row in rows] if dnc_lists else None,
        )


# P3.9: --combine-results sees no ElementIds, so it cannot apply the duplicate / Parts rule.
COMBINE_DEDUP_NOTE = (
    "not deduplicated across the combined results: --combine-results sees no ElementIds, so "
    "an element in the exports of two inputs is counted twice and a host is counted next to "
    "its Parts. Run all discipline exports in one concho-stv call instead (D15, "
    "docs/engines/stv.md)."
)


def combined_deduplication(results: list[STVResults]) -> dict[str, Any]:
    """The ``deduplication`` block of a ``--combine-results`` result: the note above and what
    each input dropped within its own run (None for inputs without the block)."""
    return {
        "deduplicated_across_inputs": False,
        "note": COMBINE_DEDUP_NOTE,
        "inputs": [
            None if r.deduplication is None else {
                "dropped": r.deduplication.get("dropped", 0),
                "by_reason": r.deduplication.get("by_reason", {}),
            }
            for r in results
        ],
    }
