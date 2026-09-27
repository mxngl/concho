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
- Toilet factor (decision D11, since P3.10): 0.75 whenever a urinal flow rate is given,
  including an explicit `0` (course: non-blank urinal cell); 1.0 when `urinal_gpf` is
  `null`/missing (course: blank cell). Before P3.10 the engine applied 0.75 only when
  `urinal_gpf > 0`. `--stv-workbook-input` reads a blank urinal cell as `null`.
- Cogeneration water and ODP come from `Cogen Data` columns G (H₂O) and H (ODP), divided by
  I (MJ/kg), as in the course (P3.10; before: F and G, one column off).

Course logic lives in `engine.py`, `reference.py` and `models.py`. The Revit importers
(`revit_architecture.py`, `revit_structural.py`, `revit_mep.py`, `central_bim.py`) map Revit
rows to (assembly, material type) with the **STV mapping table** (P3.6, below): team data,
not course data. Until P3.6 the Island mapping was hardcoded in the importers; it is now the
Island mapping file `engines/stv/examples/island/stv_mapping.csv`.

## Mapping table: `stv_mapping.csv` (P3.6)

`concho-stv` maps the Revit exports with one table per project: `--stv-mapping`, else
`files.stv_mapping` of `project_config`, else the default table `template/stv_mapping.csv`
(with a warning). The table is **validated before the run** (errors stop the run) against
the course LCA catalog of the workbook given with `--template` / `$COURSE_STV_XLSX`.

> The table names catalog entries (assembly, material type) but holds **no LCA values**;
> the catalog is read from the course workbook at runtime, never committed.

One CSV row per rule, UTF-8, comma-separated, header row with these names (order free).
Lines starting with `#` are comments; blank lines are skipped. Row numbers in messages are
file line numbers. JSON Schema of one row: [`docs/schema/stv_mapping.schema.json`](../schema/stv_mapping.schema.json)
(pydantic model `StvMappingRow` in `engines/stv/mapping.py`; `concho stvmap schema`).

| Column | Required | Content |
|---|---|---|
| `discipline` | – (optional column) | `architecture`, `structural` or `mep`: the rule only sees elements of that export; empty = all. The discipline comes from the importer (`--architecture-schedule` etc., or the `source_schedule` of a central BIM row), not from the export. |
| `assembly_code` | – | Uniformat code, validated like the cost DB codes (P3.4, `engines/common/uniformat.csv`: level 3 `B2010`, the 4-digit form of a level-2 code `B2000`, or an extension). Matches element Assembly Codes that **start with** it (`B2010` → `B2010`, `B2010100`; `B2000` → everything in `B20`). No sub-codes. |
| `category` | – | Revit Category, case-insensitive (`Walls`, `Structural Framing`). |
| `keyword` | – | case-insensitive substrings of Family + Type + Material + Assembly Description; see "Keywords". Needs a category. |
| `priority` | – (optional column) | whole number ≥ 0, default 100; lower wins among rules of the same specificity. |
| `stv_assembly` | yes | assembly of the course LCA catalog (`Exterior Wall`, `Columns`, `MEP`, …) |
| `stv_material_type` | yes | material type of that assembly in the catalog (`Concrete Cladding (sf)`) |
| `quantity_field` | yes | `area` (SF), `volume` (CF), `length` (FT), `count` (1 per element), `weight` (kg: `Weight`, else `Unit Weight`), `airflow` (m³/s: `Airflow`/`Flow`, the snapshot flows, else `Connector Flow`) |
| `conversion` | – | named conversion, see "Conversions"; empty = the quantity as read |
| `note` | yes (may be empty) | free text: why the rule exists, proxies (`proxy, see P3.7`) |

A rule needs a `category` or an `assembly_code`; a `keyword` needs a `category`.

### Matching order

For each element the matching rules are ranked:

1. **Specificity:** code + category + keyword > code + category > code > category + keyword
   > category.
2. **Priority** among the rules of the most specific level: the lowest `priority` wins.

If two rules remain (same specificity, same priority), that is a **tie**: an error that
names the element (ElementId, file and line, category / family / type) and both rules. The
run stops; the fix is a lower priority for one rule or a narrower keyword. Rules with the
same code, category, keyword and priority for overlapping disciplines would tie on every
element and are rejected by the validator without an export. `priority` is how an
`if … elif …` order is written: in the Island file the footing rule (priority 20) beats the
generic concrete rule (30) for `Footing-Rectangular` in concrete.

An element no rule matches is **unmapped**; an element whose winning rule gives a quantity
of 0 (no area, no airflow, …) is **zero quantity**. Neither is counted; both are listed in
the coverage report. Rules do not fall through to a less specific rule on a zero quantity.

### Keywords

- `a|b`: any of the terms; `a&b`: all of them. `&` binds looser than `|`:
  `exterior|curtain & glass|glazing` = (exterior or curtain) and (glass or glazing).
- Terms are matched as substrings of the lowercased Family, Type, Material and Assembly
  Description (each field on its own); whitespace inside a term is kept, around it trimmed.
- **Numeric tests** on named values defined in code (`engines/stv/conversions.py`):
  `diameter_in<=15`, `diameter_in>15` (also `<`, `>=`). `diameter_in` is the nominal duct
  diameter from `Diameter`/`Size`/`Width`/`Height` or the parameter snapshot; when it is
  unknown the test is false (the Island file then falls back to a category rule). No free
  formulas.

### Conversions

Named conversions in `engines/stv/conversions.py`. Their parameters are **team values and
must be given in the table** (no code defaults). `name=value` is the short form for
conversions with one parameter; several parameters: `name(a=1;b=2)`; lists: `a/b/c`.

| `conversion` | `quantity_field` | Unit | Quantity |
|---|---|---|---|
| (empty) | any | sf, cf, ft, count, kg, m^3/s | the field as read |
| `cf_to_cy` | `volume` | cy | CF / 27 |
| `density_kg_per_cf=<ρ>` | `volume` | kg | CF × ρ |
| `door_area(thickness_in=<t>)` | `area` | sf | Area; else Width × Height; else Volume / t (fallbacks = estimate) |
| `duct_equivalent_length` | `length` | ft | Length; else Volume / Area; else Volume^(1/3) (fallbacks = estimate) |
| `duct_weight_estimate(surface_factor=<f>;density_kg_per_m3=<ρ>;gauge_m=<g1/g2/…>;gauge_limits_m=<l1/…>)` | `weight` | kg | Weight; else sheet weight of a rectangular duct: f × 2 (w + h) × length × gauge × ρ, gauge = first `gauge_m` whose `gauge_limits_m` ≥ the larger side, else the last (estimate) |

**Unit check:** the unit that `quantity_field` + `conversion` produce must equal the unit of
the material type in the catalog (the `(…)` at the end of its name: `Glulam Beam (kg)` →
kg). `count` fits the catalog's count units (Turbine, Panel, Charger, …), not physical units.

**Estimates:** a quantity that comes from a fallback (marked above) is flagged. Each line item
of the results carries `estimated` (true/false) and `estimated_amount` (the part of `amount`
from estimates), and the coverage report sums quantity and kgCO₂e resting on estimates.

### Validation

```bash
concho stvmap validate stv_mapping.csv [--template CEE_222_STV_V12.xlsx] \
    [--architecture a.csv ...] [--structural s.csv ...] [--mep m.csv ...]   # 0 = valid, 1 = errors
concho stvmap schema                                                           # JSON Schema of one row
```

Without a workbook (`--template` or `$COURSE_STV_XLSX`) the catalog check is skipped with a
warning. With exports, every element is matched and ties are errors. From Python:
`engines.stv.mapping.validate_stv_mapping_file(path, catalog=reference_data)` or
`load_stv_mapping(path, catalog=...)` (raises `StvMappingError`).

| Check | Result |
|---|---|
| missing, unknown (with suggestion) or duplicated column; empty file; more cells than columns | error |
| `discipline` not architecture / structural / mep | error |
| `assembly_code` not in the Uniformat reference (with suggestions), malformed, sub-code | error |
| neither category nor code; keyword without category | error |
| keyword: empty term, unknown numeric test, malformed test | error |
| `priority` not a whole number ≥ 0 | error |
| `stv_assembly` / `stv_material_type` empty, not in the course catalog (with suggestions) | error |
| `quantity_field` unknown | error |
| conversion unknown, parameter missing / unknown / not a positive decimal, wrong `quantity_field` | error |
| unit of quantity_field + conversion ≠ unit of the material type | error |
| same code, category, keyword and priority for overlapping disciplines (static tie) | error |
| an element of a given export matches two rules with the same specificity and priority | error |
| no course workbook given (catalog not checked) | warning |

### Island mapping file

`engines/stv/examples/island/stv_mapping.csv` (72 rules) reproduces the importers of
concho `17da703` (before P3.6). All 4,007 rows of the six Current exports map to the same
(assembly, material type, amount), bit for bit, and the golden test reproduces
2,517,183.14 kgCO₂e and every stored result file exactly. Most Island elements have no
Assembly Code and the MEP export has no Assembly Code column, so the Island rules use
category and keyword (only the exterior walls use `B2000`). The file makes the implicit
choices explicit (note column):

- **bamboo → glulam proxy** (`proxy, see P3.7`): structural rules with keyword
  `structural bamboo` book the Island bamboo columns (99) and beams (113) as Glulam Column /
  Beam (kg) at 19.43 kg/cf; the architecture rules book the bamboo floors as Concrete (sf) and
  the bamboo walls as Steel Studs and Painted Gypsum (sf), as the old default rules did.
- MEP family names (diffusers → AHU airflow, fitting families with their surface factors),
  duct size 12"/18"D at 15 in, 12 in when unknown; stainless 8000 kg/m³, gauges 0.5/0.6/0.8 mm.
- Unmapped as before (no rule): MEP `34274` electrical fixtures and `Utility Switchboard`
  (the old code had explicit "no mapping" entries), all `Parts` (P3.9), furniture, generic
  models, plumbing fixtures, structural floors without concrete/wood keywords.

Where the table generalises the old code (same result on the Island exports, possibly a
different one on other data): keywords are always searched in Family + Type + Material +
Assembly Description (the old code searched some keywords only in the family, the material or
the type; pipe materials also in the parameter snapshot); a stainless duct without a weight is
zero quantity (the old code fell back to the duct length); the bamboo rules also catch
bamboo members of other families.

### Default table

`template/stv_mapping.csv`: a small, reviewed set for common Uniformat codes, only where the
catalog entry is unambiguous for the code (A1010 → Strip Foundation, A1020 → Mat and Pile,
A1030 → Concrete Slab, all in cy) or for the code plus an explicit product keyword (B1010
floors wood / concrete, concrete columns and beams; B2010 EIFS, brick on metal stud / on
concrete, SIP; B3010 EPDM, green roof, asphalt shingle; C1010 metal / wood stud, interior
curtain wall; C3020 carpet; D20 copper / stainless / HDPE pipes and D30 stainless ducts by
weight). Left out on purpose: members that need a density (steel, timber, glulam), steel
ducts (size threshold), windows (pane count and frame are rarely exported), roof structure
(B1020), and anything without an Assembly Code (e.g. the MEP export). Teams copy it and
extend it; the coverage report lists what is left.

### Coverage report: `mapping_coverage`

When Revit exports are mapped, `stv_results.json` gets a `mapping_coverage` block
(`engines/stv/coverage.py`):

- `mapping_file`; `total`: element counts and kgCO₂e over all disciplines;
- `disciplines.<architecture|structural|mep>`: `sources`; `elements` (`total`, `mapped`,
  `zero_quantity`, `unmapped`, `mapped_pct` = mapped / total × 100); `by_quantity`: the
  export's own `area_sf`, `volume_cf`, `length_ft`, total and mapped (`mapped_pct`); `kgco2e`
  of the discipline; `estimated` (elements, quantity per STV item, kgCO₂e and its share);
  `unmapped_types` and `zero_quantity_types` (category, family, type, count, up to five
  materials, area/volume/length sums; zero-quantity types with the rule rows);
- `rules`: every rule with `won` (elements it mapped, `won_zero_quantity` of them with 0
  quantity), `lost_to_priority` (it matched, but a rule of the same specificity with a lower
  priority won) and `lost_to_specificity` (a more specific rule won), so overlaps are visible;
- `cross_discipline_elements`: ElementIds in more than one discipline export, with how each
  occurrence maps (input for P3.9; nothing is deduplicated here).

`--combine-results` merges the blocks of the inputs (disciplines and rule counts summed);
cross-discipline elements cannot be recovered there (`null` with a note), so run all
exports in one `concho-stv` call (the export flags take several files) to get them.

Island (all six Current exports in one call, `engines/common/examples/island_2026.project_config.json`):

| Discipline | Elements | Mapped | Zero qty | Unmapped | Mapped by area / volume / length | kgCO₂e | on estimates |
|---|---|---|---|---|---|---|---|
| architecture | 1,986 | 1,331 (67.0 %) | 3 | 652 | 72.8 % / 89.3 % / 93.8 % | 1,921,565.69 | 0 |
| structural | 505 | 338 (66.9 %) | 0 | 167 | 36.2 % / 46.4 % / 100 % | 544,319.12 | 0 |
| mep | 1,516 | 1,346 (88.8 %) | 74 | 96 | 73.9 % / 46.5 % / 95.1 % | 51,298.33 | 5,731.34 (11.2 %) |

Unmapped/zero quantity = the rows skipped before P3.6 (655 / 167 / 170). Structural: 166
`Parts` (Structural Bamboo (CLB)) and the floor 1241457; MEP zero quantity: 74 return
grilles without airflow. 35 ElementIds appear in two disciplines, among them the floors
1241457 (architecture: 6,848 sf Concrete; structural: unmapped), 1789623 and 1789655 (both
mapped in both).

## Custom materials: `custom_materials.csv` (P3.7)

A custom material is a material the course LCA catalog does not have, with values from an
EPD. It is **team data, not course data**. The file is named by `stv.custom_materials_file`
(or `files.custom_materials`) of `project_config`, or `--custom-materials` of `concho-stv`.
It is validated before the run (errors stop it). Template: `template/custom_materials.csv`
(header only). JSON Schema of one row:
[`docs/schema/custom_materials.schema.json`](../schema/custom_materials.schema.json)
(`concho custmat schema`).

One CSV row per material, UTF-8, comma-separated, header row with these names (order free).
Lines starting with `#` are comments; blank lines are skipped. The columns are those of a
course `LCA Data` row (B–T) plus `source` and `is_course_data`; all values are **per unit of
`material_type`**, like the course catalog.

| Column | Course `LCA Data` | Content |
|---|---|---|
| `assembly` | B | course assembly: `Foundation`, `Interior Wall`, `Exterior Wall`, `Floor`, `Roof`, `Window`, `Columns`, `Beams`, `MEP`, `Energy`, `Misc` (`Column` / `Beam` as in `LCA Data` are accepted) |
| `material_type` | C | a new name ending with its unit in brackets, like the course names (`Bamboo Beam (kg)`); the unit is what the mapping table's unit check uses |
| `embodied_gwp_kgco2e`, `embodied_energy_mj`, `embodied_water_kg`, `embodied_odp_kgcfc11e` | D–G "Embodied" | must equal materials + transport + construction |
| `materials_…` (same four) | H–K "Materials" | EN 15804 modules A1–A3 |
| `transport_…` | L–O "Transport" | A4 |
| `construction_…` | P–S "Construction" | A5 |
| `life_units` | T "Life Units No." | unit multiplier over the building life (1 = no replacement; the course uses e.g. 2 for carpet) |
| `source` | – | EPD reference: document, registration number, page, declared unit and the conversion to the unit of `material_type` (e.g. per m³ ÷ density) |
| `is_course_data` | – | always `false` |

Energy is primary energy in MJ, water in kg (m³ × 1000), ODP in kg CFC-11e, as in the
course. The course catalog comes from SimaPro / ReCiPe Midpoint (H); EPD values (EN 15804,
usually CML / EF) are not the same method, so a custom material is never fully comparable
with a catalog entry. That is why results that rest on custom materials are flagged (below).

### Validation (`concho custmat validate`)

```bash
concho custmat validate custom_materials.csv [--template CEE_222_STV_V12.xlsx]  # 0 = valid, 1 = errors
concho custmat schema                                                         # JSON Schema of one row
```

| Check | Result |
|---|---|
| missing, unknown or duplicated column; empty file; more cells than columns | error |
| `assembly` not a course assembly | error |
| `material_type` empty, without a `(unit)` at the end, or used twice | error |
| `material_type` is a course catalog name (any assembly, case and spacing ignored) | error |
| `source` empty | error |
| `is_course_data` not `false` | error |
| a value not a plain number; energy, water or ODP negative (GWP may be negative, e.g. biogenic carbon); `life_units` ≤ 0 | error |
| `embodied_*` ≠ materials + transport + construction (relative 1e-6) | error |
| no course workbook given (names not checked against the catalog) | warning |
| no materials in the file | warning |

From Python: `engines.stv.custom_materials.validate_custom_materials_file(path,
catalog=reference_data)` or `load_custom_materials(path, catalog=...)` (raises
`CustomMaterialsError`).

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
  that is 81,954 kg of beams and 33,932 kg of columns. Undocumented in the original; since
  P3.6 explicit proxy rules in the Island mapping file (note "proxy, see P3.7"); an explicit
  custom material follows in P3.7.
- **Use phase = 0.** A and C contain no use-phase inputs (no kWh, gas, water or PV), while
  the target covers construction + 50 years of operation. So C is embodied only and its
  % of target is not comparable with the target's scope. Only B has use-phase inputs (P3.8).
- **Unmapped Parts.** In C, 166 structural `Parts` rows (plus 1 floor) are skipped by the
  structural importer, and 96 `Parts` rows by the architecture importer (together with 370
  furniture, 118 generic models, 32 plumbing fixtures, …; 655 skipped architecture rows).
  The Revit add-in exports parts and skips a floor/ceiling that has parts, so whether parts
  should be counted is open (P3.9). MEP skips 170 rows (air terminals, electrical and
  plumbing fixtures).
- **MEP mapping uses literal Revit family names** (since P3.6 in the Island mapping file).
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
