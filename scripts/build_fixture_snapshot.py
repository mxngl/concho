"""Build the private fixture snapshot for ``mxngl/concho-fixtures`` (roadmap P2.1 follow-up).

Copies exactly the files the test suite reads from the reference clones in ``.fixtures/``
(``python scripts/fetch_fixtures.py --source public``) into an output folder with the SAME
relative layout (``AutoTVD/...``, ``AutoSTV/...``, ``IPD_Challenge/...``), so no test path
changes. Writes ``MANIFEST.json`` (file, sha256, size, source repo + commit) and a
``README.md`` (private, never publish) next to them and prints the total size.

The file list below was recorded by running the full suite with fixtures required under
``strace -f`` (pandas 2.3.3, as in the CI job ``reference``): every file opened for reading
under the fixture root, plus every file the ORIGINAL scripts (AutoTVD ``tvd_analysis.py``,
IPD ``src/``) read in their temporary copies, minus outputs those scripts generate
themselves. The ``shutil.copytree`` of IPD_Challenge in ``test_schedule_equivalence.py``
touches every file and is not counted. ``AutoTVD/results/latest.json`` and
``AutoSTV/outputs/stv_project/stv_results.json`` are not opened by any test but are pinned in
``tests/fixtures/checksums.json`` (roadmap §1), so ``fetch_fixtures.py`` needs them. The 3D
view ``.fbx`` (13.9 MB) is never opened either: ``test_schedule_equivalence.py`` globs
``revit_schedules/*.fbx`` and passes its path as ``--fbx``; the scripts only write that path.
Files that are only stat'ed or globbed do not show up in an ``openat`` trace, so the list was
finally validated by running the whole suite on a snapshot built from it.

This folder is for Max/Ash to push to the PRIVATE repo. It contains course workbooks and
RSMeans-derived cost data: never commit it to ``mxngl/concho`` (``.gitignore`` does not
cover an arbitrary ``--out``).

Usage::

    python scripts/build_fixture_snapshot.py --out ../concho-fixtures-snapshot [--src .fixtures]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_fixtures import (  # noqa: E402
    FILE_SECTIONS,
    FixtureError,
    head_commit,
    load_manifest,
    resolve_dest,
    sha256,
)

# Paths relative to each repo root.
SNAPSHOT_FILES: dict[str, tuple[str, ...]] = {
    "AutoTVD": (
        "cost_data.csv",
        "qto/Architecture_TakeOff.csv",
        "qto/Structural_Schedule.csv",
        "results/latest.json",
        "tvd_analysis.py",
    ),
    "AutoSTV": (
        "outputs/Current-20260515T191939Z-3-001/Current/project/stv_results.json",
        "outputs/stv_project/stv_results.json",
    ),
    "IPD_Challenge": (
        "STV_Template/STV_ConceptA_Bambo.xlsx",
        "STV_Template/STV_LAMARCASINA_BAMBOO.xlsx",
        "floor_plans/cropped_png/04_Island_ARCH_ConceptB_Level -1_Mar6_page_0_cropped.png",
        "floor_plans/cropped_png/04_Island_ARCH_ConceptB_Level 0_Mar6 (1)_page_0_cropped.png",
        "floor_plans/cropped_png/04_Island_ARCH_ConceptB_Level 1_Mar6_page_0_cropped.png",
        "outputs/room_boundaries/room_takt_zones.csv",
        "outputs/stv_versions/Current/architecture/stv_results.json",
        "outputs/stv_versions/Current/mep/stv_results.json",
        "outputs/stv_versions/Current/project/stv_results.json",
        "outputs/stv_versions/Current/structural/stv_results.json",
        "outputs/takt_zones/central_bim_model_with_takt.csv",
        "outputs/takt_zones/takt_zones.json",
        "revit_schedules/04_Island_ARCH_Concept2-3DView-IFC_EXPORT.fbx",
        "revit_schedules/04_Island_ARCH_Concept2_Room_Boundaries.csv",
        "revit_schedules/Arch/04_Island_ARCH_Concept2_V24_2026-04-23_04-35-08pm_detached_Architecture_TakeOff.csv",
        "revit_schedules/Current/01_Island_MEP_Concept2_MEP_TakeOff.csv",
        "revit_schedules/Current/04_Island_ARCH_Concept2_Architecture_TakeOff.csv",
        "revit_schedules/Current/04_Island_ARCH_Concept2_MEP_TakeOff.csv",
        "revit_schedules/Current/04_Island_ARCH_Concept2_Structural_Schedule.csv",
        "revit_schedules/Current/STR_Wall_Bamboo_Concept2_amd03_Architecture_TakeOff.csv",
        "revit_schedules/Current/STR_Wall_Bamboo_Concept2_amd03_Structural_Schedule.csv",
        "revit_schedules/Struct/STR_Wall_Bamboo_Concept2_amd03_V3_2026-04-24_08-20-35am_detached_Architecture_TakeOff.csv",
        "src/Planning_engine/ALICE_BIM_mapper/generate_inputs.py",
        "src/Planning_engine/ALICE_BIM_mapper/generate_p6_task_schedule_xml.py",
        "src/Planning_engine/ALICE_BIM_mapper/inputs/ALICE_macro.xlsx",
        "src/Planning_engine/ALICE_BIM_mapper/outputs/Macro_Schedule.csv",
        "src/Planning_engine/Fuzor_Mapper/generate_fuzor_p6_xml.py",
        "src/Planning_engine/Logistics_Analysis/compare_delivery_windows.py",
        "src/Planning_engine/Micro_Schedule_Generator/generate_micro_schedule.py",
        "src/Planning_engine/Micro_Schedule_Generator/generate_takt_viewer.py",
        "src/Planning_engine/Micro_Schedule_Generator/inputs/ALICE_BIM_Map.csv",
        "src/Planning_engine/Micro_Schedule_Generator/inputs/micro_schedule_rules.json",
        "src/Planning_engine/Micro_Schedule_Generator/outputs/Micro_Schedule.csv",
        "src/Planning_engine/Prefab_BIM_Mapper/generate_assembly_import.py",
        "src/Planning_engine/Prefab_BIM_Mapper/generate_kit_import.py",
        "src/Planning_engine/Prefab_BIM_Mapper/generate_parts_import.py",
        "src/Planning_engine/Prefab_BIM_Mapper/generate_prefab_wall_mapping.py",
        "src/Planning_engine/Prefab_BIM_Mapper/inputs/4d_build_code_to_assembly_id_mapping.csv",
        "src/Planning_engine/Prefab_BIM_Mapper/inputs/Assembly.Import.xlsx",
        "src/Planning_engine/Prefab_BIM_Mapper/inputs/ITEM IMPORT TEMPLATE.xlsx",
        "src/Planning_engine/Prefab_BIM_Mapper/inputs/ORDER IMPORT TEMPLATE.xlsx",
        "src/Planning_engine/Prefab_BIM_Mapper/inputs/Parts Import.xlsx",
        "src/Planning_engine/Prefab_BIM_Mapper/inputs/vendors.csv",
        "src/Planning_engine/Prefab_BIM_Mapper/outputs/Production_Order.xlsx",
        "src/Planning_engine/Prefab_BIM_Mapper/outputs/Production_Order_Items.xlsx",
        "src/Planning_engine/Prefab_BIM_Mapper/outputs/Revit_Assembly_Id_Map.csv",
        "src/Planning_engine/Prefab_BIM_Mapper/outputs/Revit_Kit_Parameter_Map.csv",
        "src/Planning_engine/generate_llm_bim_context.py",
        "src/Planning_engine/generate_spatial_visualizer.py",
        "src/Takt_engine/__init__.py",
        "src/Takt_engine/outputs/Takt_Productivity_Rates.csv",
        "src/Takt_engine/outputs/Takt_Schedule.csv",
        "src/Takt_engine/takt_planner.py",
        "src/__init__.py",
        "src/takt_zone_calibrator.py",
    ),
}

MANIFEST_NAME = "MANIFEST.json"
README_NAME = "README.md"

README = """\
# concho-fixtures (PRIVATE)

Reference fixtures for the tests of [mxngl/concho](https://github.com/mxngl/concho):
a snapshot of the files the test suite reads from AutoTVD, AutoSTV and IPD_Challenge
(Island 2026, tags `island-2026-final` / IPD `989a6b7`), with the same layout as the
original repos.

**This repository is private. It contains course workbooks and RSMeans-derived cost data.
Never make it public, fork it publicly, or copy its files into another repository.**

- `MANIFEST.json`: every file with sha256, size and the source repo + commit.
- Built by `scripts/build_fixture_snapshot.py` in mxngl/concho; fetched and verified by
  `scripts/fetch_fixtures.py` at the commit pinned in `tests/fixtures/checksums.json`.
- Read access in CI: Actions secret `CONCHO_FIXTURES_TOKEN` (fine-grained PAT, read-only
  on this repo only).
"""


def build(src: Path, out: Path) -> tuple[list[dict], int]:
    """Copy the listed files from ``src`` to ``out``; return (manifest entries, bytes)."""
    pinned = load_manifest()
    expected = {
        f"{repo}/{rel}": digest
        for repo, spec in pinned.items()
        for section in FILE_SECTIONS
        for rel, digest in spec.get(section, {}).items()
    }
    listed = {f"{repo}/{rel}" for repo, rels in SNAPSHOT_FILES.items() for rel in rels}
    unlisted = sorted(set(expected) - listed)
    if unlisted:
        raise FixtureError(
            "files pinned in checksums.json but missing from SNAPSHOT_FILES: " + ", ".join(unlisted)
        )

    entries: list[dict] = []
    total = 0
    for repo, rels in SNAPSHOT_FILES.items():
        commit = head_commit(src / repo)
        if commit != pinned[repo]["commit"]:
            raise FixtureError(
                f"{src / repo} is at {commit or 'no clone'}, expected {pinned[repo]['commit']} "
                "(run python scripts/fetch_fixtures.py --source public)"
            )
        for rel in rels:
            source = src / repo / rel
            if not source.is_file():
                raise FixtureError(f"{source} is missing")
            digest = sha256(source)
            key = f"{repo}/{rel}"
            if key in expected and digest != expected[key]:
                raise FixtureError(f"{key}: sha256 {digest} differs from checksums.json")
            target = out / repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)  # content only: no mode/mtime
            size = target.stat().st_size
            total += size
            entries.append({
                "file": key,
                "sha256": digest,
                "size": size,
                "source_repo": pinned[repo]["url"],
                "source_commit": commit,
            })
    entries.sort(key=lambda e: e["file"])
    return entries, total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="output folder (must not exist or be empty)")
    parser.add_argument(
        "--src",
        help="folder with the public clones (default: $CONCHO_FIXTURES_DIR, else .fixtures/)",
    )
    args = parser.parse_args(argv)

    src = resolve_dest(args.src)
    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        print(f"{out} exists and is not empty; choose a new folder.", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    try:
        entries, total = build(src, out)
    except FixtureError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    manifest = {"version": 1, "files": entries}
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / README_NAME).write_text(README, encoding="utf-8")
    print(f"{len(entries)} files, {total:,} bytes ({total / 1e6:.1f} MB) in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
