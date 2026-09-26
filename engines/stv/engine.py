from __future__ import annotations

from .models import (
    ConstructionImpactResult,
    ImpactBreakdown,
    ImpactVector,
    STVInputs,
    STVResults,
)
from .reference import STVReferenceData

TARGET_BUILDING_AREA_SF = 6.38 * 10**6
TARGET_BUILDING_ENERGY_BASE = 1.51 * 10**8
# Building lifetime of the course formula. project_config may set another value
# (stv.lifetime_years); the use phase is then scaled by it and a warning is reported.
LIFETIME_YEARS = 50


class STVEngine:
    def __init__(
        self,
        reference_data: STVReferenceData | None = None,
        lifetime_years: int = LIFETIME_YEARS,
    ) -> None:
        self.reference_data = reference_data or STVReferenceData.from_workbook()
        self.lifetime_years = lifetime_years

    def calculate(self, inputs: STVInputs) -> STVResults:
        team = self.reference_data.get_team(inputs.team)

        construction_results: list[ConstructionImpactResult] = []
        breakdown = ImpactBreakdown()

        for item in inputs.construction_items:
            material = self.reference_data.get_material(item.assembly, item.material_type)
            total = material.embodied_total.scale(item.amount * material.unit_multiplier)
            materials = material.materials.scale(item.amount * material.unit_multiplier)
            transport = material.transport.scale(item.amount * material.unit_multiplier)
            construction = material.construction.scale(item.amount * material.unit_multiplier)
            construction_result = ConstructionImpactResult(
                assembly=item.assembly,
                material_type=item.material_type,
                amount=item.amount,
                unit_multiplier=material.unit_multiplier,
                embodied_total=total,
                materials=materials,
                transport=transport,
                construction=construction,
            )
            construction_results.append(construction_result)
            breakdown.embodied_materials = breakdown.embodied_materials + materials
            breakdown.embodied_transport = breakdown.embodied_transport + transport
            breakdown.embodied_construction = breakdown.embodied_construction + construction

        annual_electricity = self._calculate_annual_electricity(inputs)
        annual_heating = self._calculate_annual_heating(inputs)
        annual_water = self._calculate_annual_water(inputs)
        breakdown.use_electricity = annual_electricity.scale(self.lifetime_years)
        breakdown.use_heating = annual_heating.scale(self.lifetime_years)
        breakdown.use_water = annual_water.scale(self.lifetime_years)

        targets = ImpactVector(
            carbon=TARGET_BUILDING_AREA_SF * team.target_carbon_factor,
            energy=TARGET_BUILDING_ENERGY_BASE * team.target_energy_factor,
            water=team.target_water_factor,
            ozone=0.0,
        )
        return STVResults(
            team=inputs.team,
            targets=targets,
            breakdown=breakdown,
            construction_items=construction_results,
            lifetime_years=self.lifetime_years,
        )

    def _calculate_annual_electricity(self, inputs: STVInputs) -> ImpactVector:
        team = self.reference_data.get_team(inputs.team)
        use_phase = inputs.use_phase
        cogen = use_phase.cogeneration

        grid = team.grid_electricity.scale(use_phase.electricity_from_grid_kwh)
        onsite_renewable = ImpactVector()

        cogen_vector = ImpactVector()
        if cogen.fuel_type:
            cogen_total = cogen.electricity_split + cogen.heating_split + cogen.cooling_split
            if cogen_total > 0:
                fuel = self.reference_data.get_fuel(cogen.fuel_type)
                cogen_vector = (
                    self._cogen_output_vector(
                        cogen.electricity_kwh,
                        cogen.electricity_split,
                        cogen_total,
                        fuel,
                        convert_kwh_to_mj=True,
                    )
                    + self._cogen_output_vector(
                        cogen.cooling_kwh,
                        cogen.cooling_split,
                        cogen_total,
                        fuel,
                        convert_kwh_to_mj=True,
                    )
                )

        return grid + onsite_renewable + cogen_vector

    def _calculate_annual_heating(self, inputs: STVInputs) -> ImpactVector:
        use_phase = inputs.use_phase
        cogen = use_phase.cogeneration

        cogen_vector = ImpactVector()
        if cogen.fuel_type:
            cogen_total = cogen.electricity_split + cogen.heating_split + cogen.cooling_split
            if cogen_total > 0:
                fuel = self.reference_data.get_fuel(cogen.fuel_type)
                cogen_vector = self._cogen_output_vector(
                    cogen.heating_mj,
                    cogen.heating_split,
                    cogen_total,
                    fuel,
                    convert_kwh_to_mj=False,
                )

        natural_gas = ImpactVector(
            carbon=(use_phase.natural_gas_m3 * 37 * 10**6 / (1.055 * 10**9) * (117 / 2.2))
            + (use_phase.natural_gas_m3 * 0.38),
            energy=37 * use_phase.natural_gas_m3,
            water=0.00618 * 1000 * use_phase.natural_gas_m3,
            ozone=use_phase.natural_gas_m3 * 3.07 * 10**-7,
        )
        return cogen_vector + natural_gas

    def _calculate_annual_water(self, inputs: STVInputs) -> ImpactVector:
        water = inputs.use_phase.water_use
        toilet = self._water_fixture_vector(
            uses_per_person=3 * 250,
            occupants=900,
            rate=water.toilet_gpf,
            # Course: 0.75 whenever the urinal cell is non-blank, even 0 (decision D11).
            occupancy_factor=1.0 if water.urinal_gpf is None else 0.75,
        )
        urinal = self._water_fixture_vector(
            uses_per_person=3 * 250 * 0.25,
            occupants=900,
            rate=water.urinal_gpf or 0.0,
        )
        landscaping = self._water_landscape_vector(water.landscaping_gal)
        total = (
            toilet
            + urinal
            + self._water_fixture_vector(
                uses_per_person=0.5 * 3 * 250,
                occupants=900,
                rate=water.wc_sink_gpm,
            )
            + self._water_fixture_vector(
                uses_per_person=0.2 * 1 * 250,
                occupants=900,
                rate=water.lab_sink_gpm,
            )
            + self._water_fixture_vector(
                uses_per_person=0.25 * 1 * 250,
                occupants=900,
                rate=water.kitchen_sink_gpm,
            )
            + self._water_fixture_vector(
                uses_per_person=0.01 * 10 * 250,
                occupants=900,
                rate=water.shower_gpm,
            )
            + landscaping
        )

        # Course (Use Phase H40 = -MIN(D40 * ..., H32 + H33 + H38)): rainwater only offsets
        # toilet, urinal and landscaping water, not sinks or showers (P3.10, decision D12).
        rainwater = ImpactVector(
            carbon=0.0,
            energy=0.0,
            water=-min(
                water.rainwater_collection_gal * (1 + 0.00113 * 1000) * 3.79,
                toilet.water + urinal.water + landscaping.water,
            ),
            ozone=0.0,
        )
        return total + rainwater

    @staticmethod
    def _cogen_output_vector(
        demand: float,
        split: float,
        total_split: float,
        fuel,
        *,
        convert_kwh_to_mj: bool,
    ) -> ImpactVector:
        if demand == 0 or split == 0 or total_split == 0:
            return ImpactVector()
        conversion = 3.6 if convert_kwh_to_mj else 1.0
        base = demand * (1 / total_split) * (split / total_split) * conversion
        return ImpactVector(
            carbon=base * fuel.carbon_per_mj,
            energy=base,
            water=base * (fuel.water / fuel.mj_per_fu),
            ozone=base * (fuel.ozone / fuel.mj_per_fu),
        )

    @staticmethod
    def _water_fixture_vector(
        *,
        occupants: float,
        uses_per_person: float,
        rate: float,
        occupancy_factor: float = 1.0,
    ) -> ImpactVector:
        gallons = occupants * uses_per_person * occupancy_factor * rate
        return STVEngine._water_gallons_to_impacts(gallons)

    @staticmethod
    def _water_landscape_vector(gallons: float) -> ImpactVector:
        return STVEngine._water_gallons_to_impacts(gallons)

    @staticmethod
    def _water_gallons_to_impacts(gallons: float) -> ImpactVector:
        return ImpactVector(
            carbon=gallons * 0.000317 * 3.79,
            energy=gallons * 8.44 * 10**-5 * 41.868 * 3.79,
            water=gallons * (1 + 0.00113 * 1000) * 3.79,
            ozone=gallons * 1.62 * 10**-11 * 3.79,
        )
