"""The migrated schedule modules differ from IPD_Challenge@989a6b7 only where P1.7 allows.

Uses the IPD_Challenge@989a6b7 checkout from ``IPD_CHALLENGE_DIR`` or the shared fixture root
(see ``tests/conftest.py``); skipped without it (fails in the CI job ``reference``).

Every top-level function, class and constant of each original script is compared (as AST, so
comments and formatting are ignored) with the migrated module. Allowed differences:

- constants whose name ends in ``_PATH``, ``_PATHS``, ``_DIR``, ``_GLOB`` or is ``ROOT`` /
  ``BACKGROUND_BY_LEVEL`` (repo-relative paths replaced by ``configure()``);
- the functions listed in ``CHANGED_FUNCTIONS`` (path lookups, ``None`` guards for optional
  inputs, ``main``);
- new CLI helpers (``configure``, ``build_parser``, ``main``, ``parse_floor_plan``);
- the P3B.8 bug fixes listed in ``P3B8_CHANGED_FUNCTIONS`` / ``P3B8_NEW_FUNCTIONS``.

Everything else (rules, constants, task logic) must be identical.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEDULE = REPO / "engines" / "schedule"

# original (relative to the checkout) -> migrated (relative to engines/schedule)
MODULES = {
    "src/takt_zone_calibrator.py": "core/takt_zones.py",
    "src/Planning_engine/generate_llm_bim_context.py": "core/llm_context.py",
    "src/Planning_engine/Micro_Schedule_Generator/generate_micro_schedule.py":
        "core/micro_schedule.py",
    "src/Takt_engine/takt_planner.py": "core/takt_planner.py",
    "src/Planning_engine/Logistics_Analysis/compare_delivery_windows.py":
        "core/delivery_windows.py",
    "src/Planning_engine/ALICE_BIM_mapper/generate_inputs.py": "adapters/alice/macro_inputs.py",
    "src/Planning_engine/ALICE_BIM_mapper/generate_p6_task_schedule_xml.py":
        "adapters/alice/p6_xml.py",
    "src/Planning_engine/Fuzor_Mapper/generate_fuzor_p6_xml.py": "adapters/fuzor/p6_xml.py",
    "src/Planning_engine/Prefab_BIM_Mapper/generate_prefab_wall_mapping.py":
        "adapters/manufacton/prefab_wall_mapping.py",
    "src/Planning_engine/Prefab_BIM_Mapper/generate_parts_import.py":
        "adapters/manufacton/parts_import.py",
    "src/Planning_engine/Prefab_BIM_Mapper/generate_assembly_import.py":
        "adapters/manufacton/assembly_import.py",
    "src/Planning_engine/Prefab_BIM_Mapper/generate_kit_import.py":
        "adapters/manufacton/kit_import.py",
    "src/Planning_engine/generate_spatial_visualizer.py": "viewers/spatial_visualizer.py",
    "src/Planning_engine/Micro_Schedule_Generator/generate_takt_viewer.py":
        "viewers/takt_viewer.py",
}

# Original functions whose body changed, per migrated module (reviewed in the P1.7 PR).
CHANGED_FUNCTIONS = {
    "core/takt_zones.py": {"load_existing_takt_zones", "main"},
    "core/micro_schedule.py": {
        "latest_room_boundaries_path", "load_element_discipline_lookup", "load_micro_rules",
        "load_prefab_mapping",
    },
    "core/takt_planner.py": {
        "latest_fbx_path", "latest_room_boundaries_path", "load_equipment", "main",
        "parse_args", "productivity_rates_frame", "run",
    },
    "core/delivery_windows.py": {"main"},
    "adapters/alice/p6_xml.py": {"load_wbs_lookup"},
    "adapters/manufacton/prefab_wall_mapping.py": {"main"},
    "adapters/manufacton/parts_import.py": {"build_part_element_rows"},
    "viewers/takt_viewer.py": {"load_wbs_by_task_id", "main"},
}

# P3B.8 bug fixes to the original code, per migrated module (see engines/schedule/README.md,
# "Fixed in P3B.8"): functions whose body changed on purpose, and new helper functions.
P3B8_CHANGED_FUNCTIONS = {
    "core/takt_zones.py": {"assign_takt_ids"},  # fix 1: keep the last polygon corner
    # fix 3: resolve the static 4D mapping against the current model
    "adapters/manufacton/kit_import.py": {"load_mapping", "load_dynamic_mapping"},
}
P3B8_NEW_FUNCTIONS: dict[str, set[str]] = {
    "adapters/manufacton/kit_import.py": {"resolve_static_mapping", "warn"},
}

NEW_FUNCTIONS = {"configure", "build_parser", "main", "parse_floor_plan"}
PATH_CONSTANT = re.compile(r"(_PATH|_PATHS|_DIR|_GLOB)$|^(ROOT|BACKGROUND_BY_LEVEL)$")


def _top_level(path: Path) -> dict[str, str | None]:
    """Name -> AST dump of every top-level def/class and (``=NAME``) constant."""
    items: dict[str, str | None] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            items[node.name] = ast.dump(node)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = ast.dump(node.value) if node.value is not None else None
            for target in targets:
                if isinstance(target, ast.Name):
                    items[f"={target.id}"] = value
    return items


@pytest.mark.parametrize("original", list(MODULES), ids=list(MODULES.values()))
def test_only_paths_and_cli_changed(ipd_challenge_dir: Path, original: str) -> None:
    migrated = MODULES[original]
    old = _top_level(ipd_challenge_dir / original)
    new = _top_level(SCHEDULE / migrated)

    changed = {name for name in old if name in new and old[name] != new[name]}
    removed = set(old) - set(new)
    added = set(new) - set(old)

    constants = {name[1:] for name in changed | removed | added if name.startswith("=")}
    assert all(PATH_CONSTANT.search(name) for name in constants), sorted(
        name for name in constants if not PATH_CONSTANT.search(name)
    )
    assert {name for name in changed if not name.startswith("=")} == CHANGED_FUNCTIONS.get(
        migrated, set()
    ) | P3B8_CHANGED_FUNCTIONS.get(migrated, set())
    assert not {name for name in removed if not name.startswith("=")}
    assert {name for name in added if not name.startswith("=")} <= NEW_FUNCTIONS | (
        P3B8_NEW_FUNCTIONS.get(migrated, set())
    )


# Modules without an original script (P3B.8 fix 2: IPD_Challenge has no generator for
# room_takt_zones.csv).
NEW_MODULES = {"core/room_takt_zones.py"}


def test_every_migrated_module_is_covered() -> None:
    migrated = {
        str(path.relative_to(SCHEDULE))
        for path in SCHEDULE.rglob("*.py")
        if path.name not in {"__init__.py", "__main__.py", "cli.py"}
    }
    assert migrated == set(MODULES.values()) | NEW_MODULES
