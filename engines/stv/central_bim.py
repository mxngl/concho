"""Combined central BIM CSV → STV construction items.

Each row is mapped with the rules of its discipline, taken from its ``source_schedule``
file name (``*Architecture_TakeOff*``, ``*Structural_Schedule*``, ``*MEP_TakeOff*``); rows
of other sources stay unmapped. Since P3.6 the mapping comes from the STV mapping table.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .mapping import Element, ScheduleReport, StvMapping, map_elements
from .models import ConstructionItem


@dataclass(slots=True)
class CentralBIMScheduleReport:
    report: ScheduleReport
    source_schedule_counts: dict[str, int]
    mapper_counts: dict[str, int]

    @property
    def construction_items(self) -> list[ConstructionItem]:
        return self.report.construction_items

    @property
    def mapped_rows(self) -> int:
        return self.report.mapped_rows

    @property
    def skipped_rows(self) -> list[dict[str, str]]:
        return self.report.skipped_rows

    def to_dict(self) -> dict[str, object]:
        payload = self.report.to_dict()
        payload["source_schedule_counts"] = self.source_schedule_counts
        payload["mapper_counts"] = self.mapper_counts
        return payload


def load_central_bim_model(csv_path: Path | str, mapping: StvMapping) -> CentralBIMScheduleReport:
    path = Path(csv_path)
    elements: list[Element] = []
    source_schedule_counts: Counter[str] = Counter()
    mapper_counts: Counter[str] = Counter()

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_schedule = row.get("source_schedule", "")
            source_schedule_counts[source_schedule] += 1
            discipline = _mapper_name_for_source(source_schedule)
            mapper_counts[discipline] += 1
            elements.append(
                Element(discipline=discipline, row=row, source=str(path), line=reader.line_num)
            )

    return CentralBIMScheduleReport(
        report=map_elements(elements, mapping, discipline="central_bim", source=str(path)),
        source_schedule_counts=dict(source_schedule_counts),
        mapper_counts=dict(mapper_counts),
    )


def _mapper_name_for_source(source_schedule: str) -> str:
    name = Path(source_schedule).name.lower()
    if "architecture_takeoff" in name:
        return "architecture"
    if "structural_schedule" in name:
        return "structural"
    if "mep_takeoff" in name:
        return "mep"
    return "unknown"
