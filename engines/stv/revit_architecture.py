"""Revit architecture takeoff → STV construction items.

Since P3.6 the rows are mapped by the STV mapping table (``stv_mapping.csv``, see
:mod:`engines.stv.mapping`); the Island rules that were hardcoded here are in
``engines/stv/examples/island/stv_mapping.csv``.
"""

from __future__ import annotations

from pathlib import Path

from .mapping import Discipline, ScheduleReport, StvMapping, load_schedule

DISCIPLINE = Discipline.ARCHITECTURE.value
ArchitectureScheduleReport = ScheduleReport


def load_architecture_schedule(csv_path: Path | str, mapping: StvMapping) -> ScheduleReport:
    return load_schedule(csv_path, mapping, discipline=DISCIPLINE)
