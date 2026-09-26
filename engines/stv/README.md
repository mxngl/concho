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
  (900 occupants, 250 days; rainwater offset capped at total water use), × 50 years.

Known divergence from the workbook: the course applies the 0.75 toilet factor whenever the
urinal cell is non-blank (even at 0); the engine applies it only when `urinal_gpf > 0`.

Course logic lives in `engine.py`, `reference.py` and `models.py`. The Revit importers
(`revit_architecture.py`, `revit_structural.py`, `revit_mep.py`, `central_bim.py`) contain the
**Island-specific** Revit → (assembly, material type) mapping (not course data; to be replaced
by a mapping table in P3.6). The Island example input is `examples/concept_a_bambo.json`.

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

concho-stv --input engines/stv/examples/concept_a_bambo.json --team Island \
    --output-dir out/stv_example
# same as: python -m engines.stv.cli ...
```

`--output-dir` is required; nothing is written inside the package. Other inputs:
`--structural-schedule`, `--mep-schedule`, `--architecture-schedule`,
`--architecture-history-dir`, `--central-bim-model`, `--stv-workbook-input`, and
`--combine-results a/stv_results.json b/stv_results.json` (no workbook needed).
Outputs: `stv_results.json`, `history.json`, PNG charts and per-importer item reports.

## Tests

`pytest tests/stv` runs unit tests on invented reference data. The Island target test
(`tests/stv/test_stv_course_workbook.py`) runs only when `COURSE_STV_XLSX` is set.

## Credit

Originally developed by Ashmitha Jaysi Sivakumar in ashjs2003/IPD_Challenge (commit 989a6b7);
migrated in P1.2.
