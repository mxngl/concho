from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .models import ConstructionItem
from .revit_architecture import _map_architecture_row
from .revit_mep import _map_mep_row
from .revit_structural import _map_structural_row


@dataclass(slots=True)
class CentralBIMScheduleReport:
    construction_items: list[ConstructionItem]
    mapped_rows: int
    skipped_rows: list[dict[str, str]]
    source_schedule_counts: dict[str, int]
    mapper_counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "mapped_rows": self.mapped_rows,
            "source_schedule_counts": self.source_schedule_counts,
            "mapper_counts": self.mapper_counts,
            "skipped_rows": self.skipped_rows,
            "construction_items": [
                {
                    "assembly": item.assembly,
                    "material_type": item.material_type,
                    "amount": item.amount,
                }
                for item in self.construction_items
            ],
        }


def load_central_bim_model(csv_path: Path | str) -> CentralBIMScheduleReport:
    path = Path(csv_path)
    totals: dict[tuple[str, str], float] = defaultdict(float)
    skipped_rows: list[dict[str, str]] = []
    source_schedule_counts: Counter[str] = Counter()
    mapper_counts: Counter[str] = Counter()
    mapped_rows = 0

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_schedule = row.get("source_schedule", "")
            source_schedule_counts[source_schedule] += 1
            mapper_name = _mapper_name_for_source(source_schedule)
            mapper_counts[mapper_name] += 1

            mapped = _map_row(row, mapper_name)
            if mapped is None:
                skipped_rows.append(
                    {
                        "element_id": row.get("ElementId", ""),
                        "category": row.get("Category", ""),
                        "family": row.get("Family", ""),
                        "type": row.get("Type", ""),
                        "source_schedule": source_schedule,
                        "mapper": mapper_name,
                        "reason": "No STV central BIM mapping rule matched this row.",
                    }
                )
                continue

            mapped_rows += 1
            totals[(mapped.assembly, mapped.material_type)] += mapped.amount

    construction_items = [
        ConstructionItem(assembly=assembly, material_type=material_type, amount=amount)
        for (assembly, material_type), amount in sorted(totals.items())
        if amount > 0
    ]

    return CentralBIMScheduleReport(
        construction_items=construction_items,
        mapped_rows=mapped_rows,
        skipped_rows=skipped_rows,
        source_schedule_counts=dict(source_schedule_counts),
        mapper_counts=dict(mapper_counts),
    )


def _map_row(row: dict[str, str], mapper_name: str) -> ConstructionItem | None:
    if mapper_name == "architecture":
        return _map_architecture_row(row)
    if mapper_name == "structural":
        return _map_structural_row(row)
    if mapper_name == "mep":
        return _map_mep_row(row)
    return None


def _mapper_name_for_source(source_schedule: str) -> str:
    name = Path(source_schedule).name.lower()
    if "architecture_takeoff" in name:
        return "architecture"
    if "structural_schedule" in name:
        return "structural"
    if "mep_takeoff" in name:
        return "mep"
    return "unknown"
