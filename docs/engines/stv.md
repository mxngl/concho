# STV engine

The Sustainable Target Value (STV) engine (`engines/stv/`) computes embodied and use-phase
impacts (carbon, energy, water, ozone) of a building and compares them with the course
targets. Usage (CLI, inputs, outputs) is in [`engines/stv/README.md`](../../engines/stv/README.md).

## How it works

The engine is a port of the course workbook `CEE_222_STV_V12.xlsx`. It reads the course data
from a workbook at runtime (never committed, see roadmap §0):

- `LCA Data` rows 8–107: 86 materials with SimaPro/ReCiPe factors (materials, transport,
  construction), grouped by assembly (Floor, Columns, Beams, Exterior Wall, MEP, …);
- team rows 115–121 (Pacific, Atlantic, Ridge, Island, River, Central, Express): grid
  electricity factors and target factors;
- `Cogen Data`: fuels for cogeneration.

Formulas (`engine.py`):

- **Targets:** carbon = `6.38e6` × team carbon factor, energy = `1.51e8` × team energy
  factor, water = team water value. The two constants come from the course workbook (origin:
  decision D10). Island: 7,396,873.85 kgCO₂e, 155,969,076.59 MJ, 271,387,397.26 kg.
- **Embodied:** per construction item, amount × LCA factor × unit multiplier, split into
  materials, transport and construction.
- **Use phase:** annual grid electricity, on-site renewables, cogeneration, natural gas and
  water (900 occupants, 250 days/year), × 50 years. The rainwater credit is capped at toilet
  + urinal + landscaping water, as in the course (`Use Phase` H40; since P3.10, decision
  D12; before it was capped at the total water use).
- Known divergence from the workbook: the course applies the 0.75 toilet factor whenever the
  urinal cell is non-blank (even at 0); the engine only when `urinal_gpf > 0` (P2.4).

Course logic lives in `engine.py`, `reference.py` and `models.py`. The Revit importers
(`revit_architecture.py`, `revit_structural.py`, `revit_mep.py`, `central_bim.py`) hold the
**Island-specific** mapping of Revit rows to (assembly, material type) plus unit conversions.
This is team logic, not course data, and is replaced by a mapping table in P3.6.

## Island 2026 reference result

**The current Island result is 2,517,183.14 kgCO₂e** (28,396,923.44 MJ, 30,026,557.14 kg
water; 34.0 % / 18.2 % / 11.1 % of target). The 1,960,143.66 kgCO₂e that Concho reads is an
older snapshot from 2026-03-30. Both files, and a third variant in IPD_Challenge, were
reproduced **exactly** (identical `stv_results.json` content) with the migrated engine
(P2.3, 2026-09-26).

| | Carbon kgCO₂e | Produced | Inputs | Where |
|---|---|---|---|---|
| **A** | 1,960,143.66 | 2026-03-30 | early single exports `revit_schedules/{Architecture_TakeOff,Structural_Schedule,MEP_TakeOff}.csv` (IPD_Challenge `519a5c0`, deleted in `b4b918b`) | AutoSTV `outputs/stv_project/` (read by Concho's `get_stv_dashboard`) |
| **B** | 2,350,871.62 | 2026-05-07 | central BIM model (Current exports, but architecture from `…_V35_2026-04-26…_Architecture_TakeOff.csv`) **plus** the Energy/MEP items and use phase of `STV_Template/STV_LAMARCASINA_BAMBOO.xlsx` | IPD_Challenge `outputs/stv_project/` (not shown anywhere) |
| **C** | **2,517,183.14** | 2026-05-15 | `revit_schedules/Current/*` (two CSVs per trade) | IPD_Challenge `outputs/stv_versions/Current/project/`, byte-identical copy in AutoSTV `outputs/Current-20260515T191939Z-3-001/Current/project/` (STV dashboard "Current") |

All three use `STV_Template/STV_ConceptA_Bambo.xlsx` as reference data (the default of the
IPD_Challenge engine) and team Island.

### A: 1,960,143.66 (the file Concho reads)

- Created in IPD_Challenge commit `519a5c0` ("Added Arch Takeoff and STV integration",
  2026-03-30) as the combination of the three trade results in `outputs/stv_{structural,mep,
  architecture}/` (1,502,595.13 + 399,841.78 + 57,706.74 in the original run, combined in the
  order structural, mep, architecture). It was unchanged in `b3244e4` (2026-04-01).
- On 2026-04-24 AutoSTV's first commit (`a706747`) copied IPD_Challenge's `outputs/` as they
  were; AutoSTV's `stv_project/stv_results.json` is byte-identical to IPD `519a5c0` and was
  never updated afterwards. IPD_Challenge itself overwrote its copy with B on 2026-05-13.
- The inputs are the early Revit exports from before the monthly versioning; they were
  deleted from IPD_Challenge in `b4b918b` (2026-04-23) and are not in any fixture ref.
  Reproduction: load the three CSVs from `519a5c0` with the three importers, run the engine
  per trade and combine (structural, mep, architecture) → identical `stv_results.json`.
- The AutoSTV dashboard at `island-2026-final` no longer loads this file at all (its `RUNS`
  are Feb, Mar, Apr, Current). So only Concho shows it.

### B: 2,350,871.62 (IPD_Challenge `outputs/stv_project/`)

- Written on 2026-05-07 (history entry; committed in `c071034`) by a `--central-bim-model`
  + `--stv-workbook-input STV_LAMARCASINA_BAMBOO.xlsx` run. The central BIM CSV it used is not
  committed; `outputs/stv_project/central_bim_model_stv_items.json` lists its source files
  (the Current exports, but the V35 architecture takeoff instead of the Current one).
- Reproduced exactly from that items file + the LAMARCASINA workbook inputs. It is the only
  variant with a use phase (45,414.05 kgCO₂e; 216,992 kWh/yr PV, 396,183 gal/yr rainwater,
  fixture flow rates) and Energy items (PV 5,000 sf, EV battery, solar water heating,
  rainwater tank). Its water (173.4 M kg) is dominated by the use phase.
- It is older than C (2026-05-07 vs. 2026-05-15, older architecture export) and neither
  dashboard nor Concho reads it.

### C: 2,517,183.14 (current)

- Produced on 2026-05-15 (IPD_Challenge `989a6b7` "Updated STV"; copied into AutoSTV
  `dde2a01` the same day) by a batch script that is not committed. `stv_versions/summary.json`
  lists, per month, the source CSVs of each trade. For Current:
  - architecture: `04_Island_ARCH_Concept2_Architecture_TakeOff.csv`,
    `STR_Wall_Bamboo_Concept2_amd03_Architecture_TakeOff.csv`;
  - mep: `01_Island_MEP_Concept2_MEP_TakeOff.csv`, `04_Island_ARCH_Concept2_MEP_TakeOff.csv`;
  - structural: `04_Island_ARCH_Concept2_Structural_Schedule.csv`,
    `STR_Wall_Bamboo_Concept2_amd03_Structural_Schedule.csv`.
- Per trade: import each CSV, sum the items per (assembly, material type), sorted; run the
  engine; then combine the trades in the order architecture, mep, structural
  (1,921,565.69 + 51,298.33 + 544,319.12). This reproduces the project file and all three
  trade files exactly. It is **not** the central BIM model run: running
  `stv_versions/Current/central_bim_model.csv` gives 2,497,747.35 (different mapping of the
  combined rows).
- **Why C is current:** it is the newest result (from the tagged IPD_Challenge commit), it is
  computed from the newest Revit exports (`revit_schedules/Current/`), and it is what the STV
  dashboard shows as "Current". A is a stale copy from March; B is an intermediate run with an
  older architecture export that nothing reads.
- Difference A → C (+557,040 kgCO₂e) comes from the newer model, not from code changes:
  Floor +486,132 (mainly concrete floor area 35,657 → 70,509 sf in architecture, plus
  22,661 sf concrete floor now also in structural), Exterior Wall +75,828 (concrete cladding added, EIFS removed),
  Beams +15,350; Interior Wall −15,351, MEP −6,408.

The golden test `tests/stv/test_golden_stv.py` pins C: it re-runs the engine on the C inputs
from the fixtures and compares targets, totals, breakdown, construction items and the three
trade results within 1e-6 relative. Run it with:

```bash
python scripts/fetch_fixtures.py   # clones the reference repos into .fixtures/, verifies sha256
pytest tests/stv/test_golden_stv.py
```

**Follow-up (not done here):** Concho's `get_stv_dashboard` still reads A. Re-pointing it to
C (or to the Phase 5 data API) needs approval to change the live n8n workflow (roadmap §0,
rule 4).

### Known assumptions and caveats in the reference result

- **Bamboo booked as glulam.** Bamboo is not in the course catalog. The structural bamboo
  (material "Structural Bamboo (CLB)") is modelled with the Revit families
  `Glulam-Western Species` and `Timber-Column`, so the importer books it as
  **Glulam Beam (kg)** / **Glulam Column (kg)** at 19.43 kg/cf (`GLULAM_KG_PER_CF`). In C
  that is 81,954 kg of beams and 33,932 kg of columns. Undocumented in the original; an
  explicit custom material follows in P3.7.
- **Use phase = 0.** A and C contain no use-phase inputs (no kWh, gas, water or PV), while
  the target covers construction + 50 years of operation. So C is embodied only and its
  % of target is not comparable with the target's scope. Only B has use-phase inputs (P3.8).
- **Unmapped Parts.** In C, 166 structural `Parts` rows (plus 1 floor) are skipped by the
  structural importer, and 96 `Parts` rows by the architecture importer (together with 370
  furniture, 118 generic models, 32 plumbing fixtures, …; 655 skipped architecture rows).
  The Revit add-in exports parts and skips a floor/ceiling that has parts, so whether parts
  should be counted is open (P3.9). MEP skips 170 rows (air terminals, electrical and
  plumbing fixtures).
- **MEP mapping uses literal Revit family names** (`revit_mep.py`).
- **Possible double counting of floors.** Three floor elements (IDs 1241457, 1789623,
  1789655; about 10,000 sf) appear in both the Current architecture and structural exports and
  both importers map floors. Not verified further; the golden test keeps the behaviour as is.
- **Reference workbook.** The team workbooks in IPD_Challenge `STV_Template/` are used as the
  reference data here (never copied into this repo). `STV_ConceptA_Bambo.xlsx` reproduces all
  files exactly. `STV_LAMARCASINA_BAMBOO.xlsx` gives the same carbon, energy and water for C
  but a slightly different ozone value (0.070735 vs 0.070731), so its LCA ozone data differs
  somewhere. Equivalence with the course template itself is P2.4.
- **Dashboard observations (AutoSTV `index.html`, not fixed here):** the PDF export looks up a
  run with id `stv_project`, which no longer exists, and falls back to the first run
  (February, 2,314,773.72); the charts label energy as kWh and water as L, while the engine
  reports MJ and kg.
