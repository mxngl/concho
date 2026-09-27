"""Revit MEP takeoff → STV construction items.

Since P3.6 the rows are mapped by the STV mapping table (``stv_mapping.csv``, see
:mod:`engines.stv.mapping`); the Island rules that were hardcoded here (family names, duct
sizes, fitting factors) are in ``engines/stv/examples/island/stv_mapping.csv``, the
quantity logic (weights, airflow, duct lengths) in :mod:`engines.stv.conversions`. The MEP
export has no Assembly Code column, so MEP rules use category and keyword.
"""

from __future__ import annotations

from pathlib import Path

from .mapping import Discipline, ScheduleReport, StvMapping, load_schedule

DISCIPLINE = Discipline.MEP.value
MEPScheduleReport = ScheduleReport


def load_mep_schedule(csv_path: Path | str, mapping: StvMapping) -> ScheduleReport:
    return load_schedule(csv_path, mapping, discipline=DISCIPLINE)
