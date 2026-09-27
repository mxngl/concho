# engines/stv

Sustainable Target Value (STV) engine: embodied and use-phase impacts (carbon, energy, water,
ozone) of a building, compared with the course targets.

It is a port of the course workbook `CEE_222_STV_V12.xlsx`:

- reads `LCA Data` rows 8–107 (materials, SimaPro/ReCiPe factors), the team rows 115–121
  (Pacific, Atlantic, Ridge, Island, River, Central, Express) and `Cogen Data`;
- **targets:** carbon = `6.38e6` × team carbon factor, energy = `1.51e8` × team energy factor,
  water = team water value (the constants come from the course workbook);
- **embodied:** amount × LCA factor × unit multiplier, per construction item;
- **use phase:** annual grid electricity, cogeneration, natural gas and water
  (900 occupants, 250 days; rainwater offset capped at total water use), × 50 years
  (`stv.lifetime_years` of the config; another value is used but reported as a warning).

Known divergence from the workbook: the course applies the 0.75 toilet factor whenever the
urinal cell is non-blank (even at 0); the engine applies it only when `urinal_gpf > 0`.

Course logic lives in `engine.py`, `reference.py` and `models.py`. The Revit importers
(`revit_architecture.py`, `revit_structural.py`, `revit_mep.py`, `central_bim.py`) map rows
with the **STV mapping table** (P3.6, `mapping.py`, named conversions in `conversions.py`):
team data, not course data. Format, matching order and validation:
[`docs/engines/stv.md`](../../docs/engines/stv.md#mapping-table-stv_mappingcsv-p36). Island
table: `examples/island/stv_mapping.csv`; default table for common Uniformat codes:
`template/stv_mapping.csv`. The Island example input is `examples/concept_a_bambo.json`
(construction items only; team and use phase come from the config).

Project values come from `project_config` (`--config`, P3.2, see `project.py`): course team
(`stv.course_team`, `--team` overrides it), lifetime and use phase (`not_modeled` → 0, with a
warning). `custom_materials.py` loads and validates `stv.custom_materials_file`; the materials
are not used in the calculation before P3.7.

## Course workbook (required, local only)

The engine needs the course workbook at runtime. It is **not** in this repository and must
**never be committed** (roadmap §0, hard rule 2; `*.xlsx` is git-ignored and rejected by CI).
Supply it locally, either with `--template` or via the env var:

```bash
export COURSE_STV_XLSX=/path/to/CEE_222_STV_V12.xlsx
```

Without either, the CLI stops with an error explaining this.

## Run

```bash
pip install -e ".[stv]"

concho-stv --config engines/common/examples/island_2026.project_config.json \
    --input engines/stv/examples/concept_a_bambo.json --output-dir out/stv_example
# same as: python -m engines.stv.cli ...
```

`--output-dir` is required; nothing is written inside the package. Revit exports are mapped
with `--stv-mapping`, else `files.stv_mapping` of `--config`, else `template/stv_mapping.csv`
(warning); `concho stvmap validate` checks a table. `--config` sets the team,
lifetime and use phase; without it, give `--team` (or `team` in the input JSON). With
`--config`, the use phase is added to the run; for per-trade runs that are combined later,
pass `--no-use-phase` to all but one (`--combine-results` sums the use phase and warns when
more than one input has one). Other inputs:
`--structural-schedule`, `--mep-schedule`, `--architecture-schedule` (each takes one or more
CSVs),
`--architecture-history-dir`, `--central-bim-model`, `--stv-workbook-input`, and
`--combine-results a/stv_results.json b/stv_results.json` (no workbook needed).
Outputs: `stv_results.json` (with per-item `estimated` flags), `history.json`, PNG charts and
per-discipline item reports.

Island "Current" in one call (all six exports; same 2,517,183.14 kgCO₂e as the per-trade runs):

```bash
S=.fixtures/IPD_Challenge/revit_schedules/Current
concho-stv --config engines/common/examples/island_2026.project_config.json --output-dir out/island \
    --architecture-schedule $S/04_Island_ARCH_Concept2_Architecture_TakeOff.csv \
        $S/STR_Wall_Bamboo_Concept2_amd03_Architecture_TakeOff.csv \
    --mep-schedule $S/01_Island_MEP_Concept2_MEP_TakeOff.csv $S/04_Island_ARCH_Concept2_MEP_TakeOff.csv \
    --structural-schedule $S/04_Island_ARCH_Concept2_Structural_Schedule.csv \
        $S/STR_Wall_Bamboo_Concept2_amd03_Structural_Schedule.csv
```

## Tests

`pytest tests/stv` runs unit tests on invented reference data (incl. `test_stv_project_config.py`:
config → team/lifetime/use phase, custom materials validation, CLI). The Island target test
(`tests/stv/test_stv_course_workbook.py`) runs only when `COURSE_STV_XLSX` is set.
The course-equivalence test (`tests/stv/test_stv_course_equivalence.py`, P2.4/P3.10) also
needs LibreOffice Calc; see [tests/README.md](../../tests/README.md).

## Credit

Originally developed by Ashmitha Jaysi Sivakumar in ashjs2003/IPD_Challenge (commit 989a6b7);
migrated in P1.2.
