"""STV project values from ``project_config`` (P3.2).

``stv.course_team``, ``stv.lifetime_years`` and ``stv.use_phase`` of the config become the
engine inputs; ``stv.custom_materials_file`` (or ``files.custom_materials``) is loaded and
validated only (used in the calculation from P3.7). ``files.stv_mapping`` (P3.6) is the STV
mapping table for Revit exports (resolved relative to the config file).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engines.common.config import ProjectConfig, UsePhase

from .custom_materials import CustomMaterials, load_custom_materials
from .engine import LIFETIME_YEARS


@dataclass
class STVProjectSettings:
    team: str
    lifetime_years: int
    use_phase: dict[str, Any]
    use_phase_modeled: bool
    custom_materials: CustomMaterials | None = None
    warnings: list[str] = field(default_factory=list)
    stv_mapping: Path | None = None

    @classmethod
    def from_config(
        cls, config: ProjectConfig, config_dir: Path | str = "."
    ) -> STVProjectSettings:
        stv = config.stv
        warnings: list[str] = []
        if stv.lifetime_years != LIFETIME_YEARS:
            warnings.append(
                f"stv.lifetime_years is {stv.lifetime_years}; the course formula uses "
                f"{LIFETIME_YEARS} years, so the use-phase results differ from the course "
                "workbook."
            )
        modeled = not stv.use_phase.not_modeled
        if not modeled:
            warnings.append(
                "stv.use_phase.not_modeled is true: use-phase inputs are 0, the result "
                "covers construction only."
            )
        elif stv.use_phase.all_zero():
            warnings.append("stv.use_phase: all use-phase values are 0.")

        custom = None
        rel = stv.custom_materials_file or config.files.custom_materials
        if rel is not None:
            custom = load_custom_materials(Path(config_dir) / rel)
            warnings += custom.warnings
            warnings.append(
                f"custom materials file {rel}: {len(custom.records)} valid material(s), not "
                "used in the calculation yet (P3.7)."
            )

        mapping = config.files.stv_mapping
        return cls(
            team=stv.course_team.value,
            lifetime_years=stv.lifetime_years,
            use_phase=use_phase_payload(stv.use_phase) if modeled else {},
            use_phase_modeled=modeled,
            custom_materials=custom,
            warnings=warnings,
            stv_mapping=None if mapping is None else Path(config_dir) / mapping,
        )


def use_phase_payload(use_phase: UsePhase) -> dict[str, Any]:
    """``stv.use_phase`` in the ``STVInputs.from_dict`` format (``not_modeled`` → ``{}``).

    ``cogeneration: null`` = no cogeneration. ``water.urinal_gpf`` is passed as is:
    ``null`` = no urinals (toilet factor 1.0), a number incl. ``0`` = course behaviour
    (toilet factor 0.75), decision D11.
    """
    if use_phase.not_modeled:
        return {}
    payload: dict[str, Any] = {
        "electricity_from_grid_kwh": use_phase.grid_kwh or 0.0,
        "onsite_renewable_kwh": use_phase.onsite_renewable_kwh or 0.0,
        "natural_gas_m3": use_phase.natural_gas_m3 or 0.0,
    }
    cogen = use_phase.cogeneration
    if cogen is not None:
        payload["cogeneration"] = {
            "fuel_type": cogen.fuel_type,
            "electricity_kwh": cogen.electricity_kwh,
            "heating_mj": cogen.heating_mj,
            "cooling_kwh": cogen.cooling_kwh,
            "electricity_split": cogen.splits.electricity,
            "heating_split": cogen.splits.heating,
            "cooling_split": cogen.splits.cooling,
        }
    water = use_phase.water
    if water is not None:
        payload["water_use"] = {
            "toilet_gpf": water.toilet_gpf or 0.0,
            "urinal_gpf": water.urinal_gpf,
            "wc_sink_gpm": water.wc_sink_gpm or 0.0,
            "lab_sink_gpm": water.lab_sink_gpm or 0.0,
            "kitchen_sink_gpm": water.kitchen_sink_gpm or 0.0,
            "shower_gpm": water.shower_gpm or 0.0,
            "landscaping_gal": water.landscaping_gal or 0.0,
            "rainwater_collection_gal": water.rainwater_gal or 0.0,
        }
    return payload
