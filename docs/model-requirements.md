# Model requirements and export contract (P4.3, P4.5)

What a team's Revit model must contain so the Concho engines can use its exports, and every
column of the CSV files the Revit add-in (`revit-addin/`, `QTO.dll`) writes. Installation and
build of the add-in: [`revit-addin/README.md`](../revit-addin/README.md).

## Checklist for teams

1. **Assembly Code on every element type** (Uniformat, level 3, e.g. `B2010`), from week 1. It is
   the key the TVD engine prices by; elements without it are reported as *unmapped* and cost $0.
   See [Assembly Codes](#assembly-codes).
2. **Any project units** (imperial or metric). Since P4.5 the add-in converts every quantity
   from Revit's internal units into fixed export units (ft, SF, CF, …; see
   [Units](#units-p45)), so the same model gives the same CSV numbers whatever its display
   units. Exports from add-in versions before P4.5 (display strings) are still read, but only
   correctly from imperial models.
3. Elements on **levels** and in **rooms** (the schedule engine groups by level and room).
4. **Materials** assigned to the element types (STV maps embodied carbon by category, family
   and material).
5. Elements that must not be priced: put `DNC` (do not count) in `Mark` or `Comments` (or the
   family/type name). The TVD engine skips them. `Furniture` is never priced (only counted for
   `count_codes` rules).
6. Run the three takeoffs (Add-Ins → External Tools → Architecture / Structural / MEP TakeOff)
   and check the **summary dialog**: it shows the share of elements with an Assembly Code and
   the elements without one by category (fix the top categories first), and per quantity
   (`Length` / `Area` / `Volume`) how many elements have none, with the top categories (left
   empty, never written as 0). For MEP in metric
   projects it also counts elements whose `Size` was left empty and elements where STV would
   have to fall back to the `Parameter Snapshot` (see [MEP](#model_mep_takeoffcsv-71-columns)).
7. **Any Revit UI language.** The engines map by English category name (`Walls`, `Ducts`,
   `Furniture`, …). The add-in writes the English name from a fixed `BuiltInCategory` table in
   any Revit language (P4.5, see [Categories](#categories-p45)); the Revit name is kept in the
   last column `Category (local)`.

## Categories (P4.5)

`Category` is the English Revit category name, taken from a fixed table keyed by the element's
`BuiltInCategory` (`revit-addin/Categories.cs`), independent of the Revit UI language. The name
Revit shows (e.g. `Wände` in a German Revit) is in the last column `Category (local)`. The
summary dialog uses the English names. A category that is not in the table (none of the
exported ones) falls back to the Revit name.

| Export | English names in the table |
|---|---|
| Architecture | Walls, Doors, Windows, Floors, Roofs, Ceilings, Parts, Curtain Panels, Curtain Wall Mullions, Stairs, Runs, Landings, Railings¹, Generic Models, Casework, Furniture, Furniture Systems, Plumbing Fixtures |
| Structural | Floors, Parts, Structural Columns, Structural Framing, Structural Foundations, Structural Stiffeners¹, Structural Trusses¹, Structural Connections¹, Structural Connection Plates/Bolts/Anchors¹, Structural Rebar¹, Structural Area/Path/Fabric Reinforcement¹ |
| MEP | Ducts, Duct Fittings, Duct Accessories¹, Air Terminals, Flex Ducts, Pipes, Pipe Fittings, Pipe Accessories, Flex Pipes, Cable Trays¹, Cable Tray Fittings¹, Conduits¹, Conduit Fittings¹, Plumbing Fixtures, Mechanical Equipment, Electrical Equipment, Electrical Fixtures, Lighting Fixtures¹, Sprinklers¹ |

¹ Not in the English reference exports or the STV mapping tables; taken from the English Revit
UI. Check in an English Revit: `Category` and `Category (local)` must be identical in every
row; a difference means a wrong table entry.

**Parts** (P4.5): `Original Category` is the English category of the part's source element
(`Part.GetSourceElementIds`, following part-of-part chains), which also decides which parts
are exported (ceiling parts in Architecture; floor, structural, foundation and rebar parts in
Structural). `Assembly Code` of a part is the source element's code (instance, else type); the
part's own value only if the source has none. `Part Source Id` is the source element's
ElementId (empty for non-parts and for sources in linked models), so the engines can tell parts
from their host elements (double counting, P3.9). Part quantities come from the part's computed
built-in parameters (`DPART_LENGTH_COMPUTED`, `DPART_AREA_COMPUTED`, `DPART_VOLUME_COMPUTED`,
`DPART_HEIGHT_COMPUTED`, `DPART_LAYER_WIDTH` as thickness).

## Assembly Codes

### Why

- **TVD** aggregates `Area`, `Length`, `Volume` and the element count **per Assembly Code** and
  prices them with the cost DB rows of the same code. Codes are matched **exactly** (`B2010` ≠
  `B2010100`); sub-codes such as `B2010.CW` come from the cost DB's keyword split, not from
  Revit. Unknown or empty codes → *unmapped* (listed in the TVD results).
- **STV** uses `Assembly Code` / `Assembly Description` to map architecture elements to STV
  assemblies.
- The **schedule** engine carries the code into the element context.

Which codes are valid is defined by the cost DB and the Uniformat list: see
[Cost DB format → Codes](engines/tvd.md#codes) in `docs/engines/tvd.md` (UNIFORMAT II
levels 1–3 from NISTIR 6389 plus the course's cluster H codes `H1000`–`H5000`). Use the codes
that are in your team's `cost_db.csv`; a code that the cost DB doesn't have is priced $0.

### How to set Assembly Codes in Revit

`Assembly Code` is a built-in **type** parameter (group *Identity Data*), so all instances of a
type share one code.

1. Select an element → **Edit Type** (Type Properties) → *Identity Data* → **Assembly Code** →
   click the `…` button and pick the code from the Uniformat tree. `Assembly Description` is
   filled automatically.
2. If elements of one type need different codes (e.g. an exterior and an interior use of the
   same wall), duplicate the type and give each its own code.
3. For many types at once: a **type schedule** per category with the `Assembly Code` field
   (Schedule Properties → *Itemize every instance* off), then fill the column.
4. The tree comes from the classification file under **Manage → Additional Settings → Assembly
   Code** (Revit's default `UniformatClassifications.txt`). Pick **level-3** codes (`B2010`),
   matching the cost DB. If the file offers deeper codes (level 4/5, e.g. `B2010100`), don't use
   them unless your cost DB has rows for exactly those codes.
5. System families without a type Assembly Code (e.g. some MEP fittings) can be left empty if
   the cost DB doesn't price them; they show up as missing in the summary dialog and as
   unmapped in TVD.

The add-in reads `Assembly Code` from the built-in parameter (`BuiltInParameter.UNIFORMAT_CODE`,
named `ASSEMBLY_CODE` in the Revit 2026 API) on the element and, if empty, on its type, so it
works in any Revit UI language. The English parameter name `Assembly Code` is only a fallback.

## General format

- UTF-8 (with BOM), comma-separated, one header row, one row per element, standard CSV quoting
  (fields containing `,`, `"` or line breaks are quoted, `"` doubled).
- File names: `<model>_<export>.csv`, `<model>` = the Revit file name without extension
  (invalid file-name characters replaced by `_`). Folder: `export_folder` from
  `concho_addin.json` (see the add-in README).
- Readers must select columns **by name**. New columns are only ever appended at the end (P4.3
  added `Assembly Code` as the last MEP column).
- Every column is always present; the value is empty when Revit has no value. *Required* below
  means the **model** must provide a value for the engines to work; *recommended* means an
  engine uses the value when present; *optional* columns are informational.
- **Quantities** (every column with a unit in the tables below) are plain decimals: converted
  from Revit's internal units with `UnitUtils.ConvertFromInternalUnits` into the unit given per
  column, invariant culture (`.` decimal separator), no unit suffix, no thousands separator,
  up to 6 decimals (`312.5`, `0.008333`). Independent of the project's display units. The
  one exception is MEP `Length` (fixed feet-inch text, see the MEP table).
- **Lookups**: each column lists its source parameters in order. `BIP:` names a built-in
  parameter, read first (language-independent); the English name after it is the fallback.
  Each candidate is tried on the instance, then on its type. Numeric columns only take Double
  parameters whose spec fits the column unit (e.g. `Power Factor` is not read as `Power`); a
  text parameter is never written into a numeric column. If no candidate has a value, the
  column stays **empty** (not 0) and the summary dialog counts it for `Length`/`Area`/`Volume`.
- **Text values**: element references (e.g. `Level`) are the element name; Yes/No parameters
  `True` / `False`.
- **Computed numbers** (columns with `(ft)`, `(SF)`, `(CF)`, `(in)`, `(deg)` in the name) are
  plain decimals in those units, up to 3 decimals, computed from Revit's internal units.

### Units (P4.5)

| Quantity | Export unit | Columns |
|---|---|---|
| length (Architecture, Structural) | ft (decimal feet) | `Length`, `Width`, `Depth`, `Height`, `Base Offset`, `Top Offset` |
| length (MEP) | ft, as feet-inch text `12' - 6.375"` | `Length` |
| MEP dimensions and thicknesses | in (decimal inches) | `Diameter`, `Width`, `Height`, `Insulation Thickness`, `Lining Thickness` |
| area | SF | `Area` |
| volume | CF | `Volume` |
| mass / weight | kg (a force-type weight in kgf, same number) | `Weight` |
| mass or weight per length, unit weight | kg/m (kgf/m); per volume kN/m³ or kg/m³, by the parameter's spec | `Unit Weight` |
| air and water flow | m³/s | `Airflow`, `Flow`, `Connector Flow` |
| pressure | Pa | `Pressure Drop` |
| cooling / heating capacity, power | W | `Cooling Capacity`, `Heating Capacity`, `Power` |
| voltage | V | `Voltage` |
| current | A | `Current` |
| apparent power | VA | `Apparent Load`, `Connected Load` |

These are the units the engines read without conversion: TVD takes `Length`/`Area`/`Volume`
as LF/SF/CF; STV reads plain MEP dimensions as inches, weights as kg and flows as m³/s.

**Old exports** (add-in before P4.5) contain display strings in the project units (`136' -
0"`, `6590 SF`, `30 m³/h`). The engines still read them, but only correctly from **imperial**
models (a metric model's `612 m²` is read as 612 SF). Their TVD lengths are also slightly low:
TVD's display-string parser reads `9' - 7 3/4"` as 9 ft (inches with a fraction are dropped;
Island ARCH export: 3,638 instead of 3,771 LF on coded elements, −3.5 %). The numeric format
carries the exact values.

Engines: **TVD** reads the Architecture and Structural exports (`--arch`, `--struct`), **STV**
all three, **Schedule** the combined element context built from all three. "Used by" lists the
engines that read the column.

## `<model>_Architecture_TakeOff.csv` and `<model>_Structural_Schedule.csv` (58 columns)

Same header for both. Architecture exports walls, doors, windows, floors, roofs, ceilings,
curtain panels/mullions, stairs (runs, landings), railings, generic models, casework, furniture,
furniture systems, plumbing fixtures and ceiling parts (a ceiling with parts is replaced by its
parts). Structural exports floors, structural columns/framing/foundations/stiffeners/trusses,
structural connections (plates, bolts, anchors), rebar (incl. area/path/fabric reinforcement)
and parts cut from floors or structural/foundation/rebar elements (a floor with parts is replaced
by its parts).

| # | Column | Unit | Source (Revit) | Required | Used by |
|---|---|---|---|---|---|
| 1 | `ElementId` | integer | `Element.Id` | required (always set) | TVD, STV, Schedule |
| 2 | `Category` | text | English category name from the `BuiltInCategory` ([Categories](#categories-p45)) | required (always set) | TVD, STV, Schedule |
| 3 | `Family` | text | family name (family instances only; empty for system families) | recommended | TVD, STV, Schedule |
| 4 | `Type` | text | type name | recommended | TVD, STV, Schedule |
| 5 | `Original Category` | text | parts only: English category of the source element; `Original Category` parameter text if the source can't be resolved | optional | Schedule |
| 6 | `Original Family` | text | parts only: `Original Family` / `Original Family Name` | optional | Schedule |
| 7 | `Original Type` | text | parts only: `Original Type` / `Original Type Name` | optional | Schedule |
| 8 | `Level` | text | `Level` parameter, else the element's level | recommended | TVD (unmapped list), Schedule |
| 9 | `Mark` | text | BIP `ALL_MODEL_MARK`, `Mark` | optional (`DNC` marker) | TVD, Schedule |
| 10 | `Assembly Code` | Uniformat code | BIP `UNIFORMAT_CODE` / `ASSEMBLY_CODE` (2026), `Assembly Code`; parts: of the source element | **required** | TVD, STV, Schedule |
| 11 | `Assembly Description` | text | BIP `UNIFORMAT_DESCRIPTION` / `ASSEMBLY_DESCRIPTION` (2026), `Assembly Description` | recommended | STV, Schedule |
| 12 | `Length` | ft | BIP `DPART_LENGTH_COMPUTED`, `CURVE_ELEM_LENGTH`, `STRUCTURAL_FOUNDATION_LENGTH`, `CONTINUOUS_FOOTING_LENGTH`, `Length`; BIP `STRUCTURAL_FRAME_CUT_LENGTH`, `Cut Length`; `Span`; BIP `INSTANCE_LENGTH_PARAM`, `System Length` (structural columns); else the length of the element's location curve | required for LF-priced codes | TVD, STV, Schedule |
| 13 | `Width` | ft | BIP `WALL_ATTR_WIDTH_PARAM`, `CURTAIN_WALL_PANELS_WIDTH`, `STAIRS_RUN_ACTUAL_RUN_WIDTH`, `STRUCTURAL_FOUNDATION_WIDTH`, `CONTINUOUS_FOOTING_WIDTH`, `DOOR_WIDTH`, `WINDOW_WIDTH`, `FAMILY_WIDTH_PARAM`, `Width`; `Actual Width` | optional | STV, Schedule |
| 14 | `Depth` | ft | `Depth`; BIP `DPART_LAYER_WIDTH`, `STRUCTURAL_FOUNDATION_THICKNESS`, `FLOOR_ATTR_THICKNESS_PARAM`, `CEILING_THICKNESS`, `ROOF_ATTR_THICKNESS_PARAM`, `Thickness`; `Structural Depth` | optional | Schedule |
| 15 | `Height` | ft | BIP `DPART_HEIGHT_COMPUTED`, `CURTAIN_WALL_PANELS_HEIGHT`, `DOOR_HEIGHT`, `WINDOW_HEIGHT`, `FAMILY_HEIGHT_PARAM`, `Height`; thickness as in `Depth` | optional | STV, Schedule |
| 16 | `Area` | SF | BIP `DPART_AREA_COMPUTED`, `HOST_AREA_COMPUTED`, `Area`; `Host Area Computed`; `Computed Area` | required for SF-priced codes | TVD, STV, Schedule |
| 17 | `Volume` | CF | BIP `DPART_VOLUME_COMPUTED`, `HOST_VOLUME_COMPUTED`, `Volume`; `Host Volume Computed` | required for CY/CF-priced codes | TVD, STV, Schedule |
| 18 | `Weight` | kg | `Weight`, `Calculated Weight`, `Mass` | optional | – |
| 19 | `Unit Weight` | kg/m, kN/m³ or kg/m³ | `Material: Unit weight`, `Unit Weight`, `Weight per Unit Length`, `Mass per Unit Length` | optional | – |
| 20 | `Material` | text | names of the element's materials, `; `-separated | recommended | TVD (unmapped list), STV, Schedule |
| 21 | `Type Comments` | text | type parameter `Type Comments` | optional | – |
| 22 | `Base Level` | text | `Base Level` | optional | Schedule |
| 23 | `Top Level` | text | `Top Level` | optional | Schedule |
| 24 | `Base Offset` | ft | BIP `WALL_BASE_OFFSET`, `Base Offset` | optional | – |
| 25 | `Top Offset` | ft | BIP `WALL_TOP_OFFSET`, `Top Offset` | optional | – |
| 26–45 | *spatial columns* | see below | element location / bounding box | recommended | Schedule |
| 46–54 | *room columns* | see below | room of the element | recommended | Schedule |
| 55 | `Comments` | text | BIP `ALL_MODEL_INSTANCE_COMMENTS`, `Comments` | optional (`DNC` marker) | TVD |
| 56 | `Parameter Snapshot` | text (display units) | see below | optional | STV, Schedule |
| 57 | `Part Source Id` | integer | parts only: ElementId of the source element (P4.5) | optional | – (for P3.9) |
| 58 | `Category (local)` | text | category name as Revit shows it (UI language, P4.5) | optional | – |

Both exports use the same parameter lookups, except `Base Level` / `Top Level`: Architecture
reads them from the instance, else the type; Structural only from the instance. The schedule
engine's Manufacton parts adapter uses `Height` / `Length` / `Depth` text as part labels; since
P4.5 these are decimal feet (`12`) instead of `12' - 0"`.

### Quantity coverage by category (P4.5 item 6)

Which categories have `Length` / `Area` / `Volume` at all, from the English Island exports
(Architecture export of `04_Island_ARCH_Concept2`: 1,965 elements, 849 / 42 / 117 without
Length / Area / Volume), compared with Max's test in a German Revit 2026 (empty quantities by
category, add-in build before this table), and what covers them in any language:

| Category | Length | Area | Volume | Source in any language |
|---|---|---|---|---|
| Walls | all | all but 1 | 309 of 385 | `CURVE_ELEM_LENGTH`, `HOST_AREA_COMPUTED`, `HOST_VOLUME_COMPUTED`; curtain/storefront walls have no volume |
| Curtain Wall Mullions | all | all | all | `CURVE_ELEM_LENGTH`, else location curve; `HOST_*_COMPUTED` |
| Parts (ceiling parts) | none | all | all | `DPART_AREA_COMPUTED`, `DPART_VOLUME_COMPUTED`, `DPART_LENGTH_COMPUTED` where Revit has one (P4.5: were empty in the German test) |
| Floors, Ceilings, Roofs | none | all | all | `HOST_AREA_COMPUTED`, `HOST_VOLUME_COMPUTED`; no length by nature |
| Doors, Windows, Curtain Panels, Generic Models, Plumbing Fixtures, Casework | family `Length` only (windows, casework) | all but 1–2 | all but 1–2 | `HOST_*_COMPUTED`; family parameters such as `Length` are named by the family author and not localized, so the name lookup finds them in any language; panels also `CURTAIN_WALL_PANELS_WIDTH/HEIGHT` |
| Furniture | 68 of 370 (family `Length`) | 349 | 349 | as above; 21 furniture families have no geometry-based area/volume |
| Stairs, Runs, Landings | none | none | none | Revit has no computed length/area/volume for them; runs get `Width` from `STAIRS_RUN_ACTUAL_RUN_WIDTH`. Priced by count (`EA`/`FLIGHT`) |
| Parts (structural, 166) | none | all | all | German test: all empty → `DPART_*_COMPUTED` (fixed) |
| Structural Columns (134) | none in the English exports; German test: 135 empty | none | all | column length is only in `System Length` (`INSTANCE_LENGTH_PARAM`); since P4.5 written to `Length` in any language (see below) |
| Structural Framing (162) | all | none (German: 113 empty) | all | framing has no area in Revit: genuinely none |
| Structural Foundations (36) | all in English; German test: 37 empty | all | all | `STRUCTURAL_FOUNDATION_LENGTH` / `CONTINUOUS_FOOTING_LENGTH` (label "Length"), now read (P4.5) |
| MEP Air Terminals (200) | 74 (family parameter) | 126 | all | German test: 126 without Length, 74 without Area: the same gaps as in English, genuinely none |
| MEP Electrical Fixtures (61) | none | all | all | German test: 61 without Length: genuinely none |

**Structural columns carry `Length`** (P4.5): the column's `System Length` (base to top,
`INSTANCE_LENGTH_PARAM`). Earlier exports had no column `Length` in any Revit language (the value
was only in the `Parameter Snapshot`; none of the Island reference exports has it), so this is
new data, not only a German-UI fix. Whether columns are priced by length or by volume is the
team's choice in the cost DB: a row with unit `LF` for the column's Assembly Code gets the
summed `Length`, a row with `CY`/`CF` the `Volume` (see [Quantity rules](engines/tvd.md#quantity-rules)).
Island is unaffected: its column codes are `A1010` (priced in CY) and `B10` (no cost row), no
mirror rule takes a length from them, and STV maps columns by volume.

**Genuinely without a quantity** (no built-in parameter exists; same gaps in English and
German): `Length` for area/volume elements (floors, ceilings, roofs, panels, doors, furniture,
generic models, electrical fixtures, most air terminals, parts without a computed length), all
three for stairs/runs/landings, `Area` for structural framing and some air terminals, `Volume`
for curtain/storefront walls (76 in the German test, 76 in English), and area/volume for
families without solid geometry (some furniture). German-only gaps in Max's test (parts,
structural columns, foundations) are covered by the built-in parameters above. The summary dialog lists the
top categories per missing quantity, so a model can be checked against this table.

## `<model>_MEP_TakeOff.csv` (71 columns)

Ducts, duct fittings/accessories/terminals, flex ducts, pipes, pipe fittings/accessories, flex
pipes, cable trays and fittings, conduits and fittings, plumbing fixtures, mechanical and
electrical equipment, electrical and lighting fixtures, sprinklers.

| # | Column | Unit | Source (Revit) | Required | Used by |
|---|---|---|---|---|---|
| 1 | `ElementId` | integer | `Element.Id` | required (always set) | STV, Schedule |
| 2 | `Category` | text | English category name from the `BuiltInCategory` ([Categories](#categories-p45)) | required (always set) | STV, Schedule |
| 3 | `Family` | text | family name (empty for system families: ducts, pipes, …) | recommended | STV, Schedule |
| 4 | `Type` | text | type name | recommended | STV, Schedule |
| 5 | `Level` | text | `Level` parameter, else the element's level | recommended | Schedule |
| 6 | `Mark` | text | BIP `ALL_MODEL_MARK`, `Mark` | optional | Schedule |
| 7 | `System Name` | text | BIP `RBS_SYSTEM_NAME_PARAM`, `System Name`; `System` | optional | Schedule |
| 8 | `System Type` | text | `System Type` | recommended | STV, Schedule |
| 9 | `Service Type` | text | `Service Type` | optional | Schedule |
| 10 | `Classification` | text | `Classification`, `Flow Classification`, `Part Type` | optional | Schedule |
| 11 | `Size` | text, inches | built by the add-in: `3"` (diameter) or `4"x4"` (width × height), from `Diameter` / `Width`×`Height`, else the largest connector; without dimensions Revit's text (BIP `RBS_CALCULATED_SIZE`, `Size`, `Nominal Size`, `Overall Size`) in imperial projects, **empty** in projects with metric length or size units (counted in the summary dialog) | recommended | STV, Schedule |
| 12 | `Diameter` | in | BIP `RBS_CURVE_DIAMETER_PARAM`, `RBS_PIPE_DIAMETER_PARAM`, `RBS_CONDUIT_DIAMETER_PARAM`, `Diameter`; `Nominal Diameter`; `Duct Diameter` | recommended | STV |
| 13 | `Width` | in | BIP `RBS_CURVE_WIDTH_PARAM`, `RBS_CABLETRAY_WIDTH_PARAM`, `Width`; `Nominal Width`; `Duct Width` | recommended | STV, Schedule |
| 14 | `Height` | in | BIP `RBS_CURVE_HEIGHT_PARAM`, `RBS_CABLETRAY_HEIGHT_PARAM`, `Height`; `Nominal Height`; `Duct Height` | recommended | STV, Schedule |
| 15 | `Length` | ft as **feet-inch text** `12' - 6.375"` | BIP `CURVE_ELEM_LENGTH`, `Length`; `Duct Length`; `Computed Length`; `Length 1`; `Duct Length 1`; else the location curve length | required for ducts/pipes/trays/conduits | STV, Schedule |
| 16 | `Area` | SF | BIP `RBS_CURVE_SURFACE_AREA`, `HOST_AREA_COMPUTED`, `Area`; `Surface Area` | recommended | STV, Schedule |
| 17 | `Volume` | CF | BIP `HOST_VOLUME_COMPUTED`, `Volume` | optional | STV, Schedule |
| 18 | `Material` | text | names of the element's materials, `; `-separated | recommended | STV, Schedule |
| 19 | `Weight` | kg | `Weight`, `Calculated Weight`, `Mass` | optional | STV |
| 20 | `Unit Weight` | kg/m, kN/m³ or kg/m³ | `Unit Weight`, `Weight per Unit Length`, `Mass per Unit Length` | optional | STV |
| 21 | `Insulation Thickness` | in | BIP `RBS_REFERENCE_INSULATION_THICKNESS`, `Insulation Thickness` | optional | – |
| 22 | `Lining Thickness` | in | BIP `RBS_REFERENCE_LINING_THICKNESS`, `Lining Thickness` | optional | – |
| 23 | `Airflow` | m³/s | `Air Flow`, `Airflow`, `Calculated Supply/Exhaust/Return Air Flow`, BIP `RBS_DUCT_FLOW_PARAM`/`RBS_PIPE_FLOW_PARAM` `Flow`, `Supply Air Outlet Flow`, `Supply Air Inlet Flow`, `Return Air Inlet Flow` | optional | STV |
| 24 | `Flow` | m³/s | BIP `RBS_DUCT_FLOW_PARAM`, `RBS_PIPE_FLOW_PARAM`, `Flow`; `Flow Rate`; `Actual Flow`; `Demand Flow` | optional | STV |
| 25 | `Pressure Drop` | Pa | BIP `RBS_DUCT_PRESSURE_DROP`, `RBS_PIPE_PRESSUREDROP_PARAM`, `Pressure Drop`; `Calculated Pressure Drop`; `Fitting Pressure Drop` | optional | – |
| 26 | `Cooling Capacity` | W | `Cooling Capacity`, `Total Cooling Capacity`, `Sensible Cooling Capacity` | optional | – |
| 27 | `Heating Capacity` | W | `Heating Capacity`, `Heating Load`, `Total Heating Capacity` | optional | – |
| 28 | `Power` | W | `Power`, `Motor Power`, `Input Power` | optional | – |
| 29 | `Voltage` | V | `Voltage` | optional | – |
| 30 | `Current` | A | `Current`, `Current Rating` | optional | – |
| 31 | `Apparent Load` | VA | `Apparent Load` | optional | – |
| 32 | `Connected Load` | VA | `Connected Load` | optional | – |
| 33 | `Connector Count` | integer | number of MEP connectors | optional | – |
| 34 | `Connector Flow` | m³/s | sum of connector `Flow` | optional | STV |
| 35 | `Connector Demand` | number (Revit internal units, domain-dependent) | sum of connector `Demand` | optional | – |
| 36 | `Connector Max Diameter (in)` | in | largest connector radius × 2 | optional | – |
| 37 | `Connector Max Width (in)` | in | largest connector width | optional | – |
| 38 | `Connector Max Height (in)` | in | largest connector height | optional | – |
| 39–58 | *spatial columns* | see below | element location / bounding box | recommended | Schedule |
| 59–67 | *room columns* | see below | room of the element | recommended | Schedule |
| 68 | `Comments` | text | BIP `ALL_MODEL_INSTANCE_COMMENTS`, `Comments` | optional | – |
| 69 | `Parameter Snapshot` | text (display units) | see below | optional | STV, Schedule |
| 70 | `Assembly Code` | Uniformat code | BIP `UNIFORMAT_CODE` / `ASSEMBLY_CODE` (2026), `Assembly Code` | **required** (new in P4.3) | – (not read by an engine yet) |
| 71 | `Category (local)` | text | category name as Revit shows it (UI language, P4.5) | optional | – |

**`Length` is the one text column** of the exports: a fixed, culture-invariant feet-inch format
generated from the internal value: whole feet, inches with 3 decimals, no fractions
(`12' - 6.375"`, `0' - 9.000"`). It was chosen because the STV MEP importer before P3.6 only read
lengths with `'` / `"` marks (a plain `12.5` was read as 0). STV reads it back within 1e-4 ft
(`tests/revit_addin/test_export_format.py`). Since P3.6 STV's `parse_length_feet` also reads a
bare number as feet, so the switch to plain decimal feet (planned with the engine part of P4.5)
needs no further engine change. `Size` is text too, but built from the numeric dimensions in inches.

Numeric columns only take numeric parameters: `Overall Size`, `Loss Method`, `Power Factor`
and `Load Name` (text or unitless values that older exports wrote into `Length`, `Pressure Drop`,
`Power`, `Connected Load`) are no longer used there. `Length` also reads `Duct Length`,
`Computed Length`, `Length 1`, `Duct Length 1` and `Airflow` the air-terminal flows, the same
parameters STV would otherwise look up in the `Parameter Snapshot`, so the unit-safe main
columns are filled whenever Revit has the value. In metric projects the summary dialog counts
the MEP elements where STV would still fall back to the snapshot (dimensions, length or flow
empty but present in the snapshot).

Connector columns 34–35 are empty when the sum is 0; 36–38 likewise. `Assembly Code` (P4.3) and
`Category (local)` (P4.5) were appended at the end so readers that use column positions keep
working; no engine reads it from the MEP export
yet (TVD takes only Architecture and Structural). Checked in P4.3: the STV MEP importer gives
identical results with and without the new column.

## Shared column groups

### Spatial columns (20, `SpatialElementData`)

All in feet (degrees for rotation), from the element's location or bounding box (model
coordinates, internal origin).

| Column | Content |
|---|---|
| `Location Type` | `Point` (location point), `Curve` (location curve) or `BoundingBox` (neither) |
| `Position X (ft)`, `Position Y (ft)`, `Position Z (ft)` | location point, curve midpoint or bounding-box center |
| `Start X (ft)`, `Start Y (ft)`, `Start Z (ft)` | curve start (curves only) |
| `End X (ft)`, `End Y (ft)`, `End Z (ft)` | curve end (curves only) |
| `Rotation (deg)` | rotation of a location point (points only) |
| `Bounding Box Min X/Y/Z (ft)` | bounding box minimum (3 columns) |
| `Bounding Box Max X/Y/Z (ft)` | bounding box maximum (3 columns) |
| `Bounding Box Center X/Y/Z (ft)` | bounding box center (3 columns) |

### Room columns (9, `RoomAssignmentData`)

The room is the family instance's room (or to/from room for doors/windows), else the room at
the element's location point, curve midpoint or bounding-box center. Empty if none.

| Column | Unit | Content |
|---|---|---|
| `Room Id` | integer | room ElementId |
| `Room Number` | text | room `Number` |
| `Room Name` | text | room `Name` |
| `Room Level` | text | room level name |
| `Room Area (SF)` | SF | room area |
| `Room Volume (CF)` | CF | room volume |
| `Room Location X/Y/Z (ft)` | ft | room location point (3 columns) |

### `Parameter Snapshot`

`name=value` pairs joined by ` | `, sorted by name, from instance and then type parameters whose
name contains one of the export's keywords (instance value wins; empty values skipped).
**Values are Revit display text in the project's units and UI language** (`Duct Width=4"` or
`Duct Width=100 mm`); the snapshot is informational and not unit-safe. The keywords below are
English, so in a localized Revit the snapshot only holds parameters whose (localized or family)
names happen to contain them. Engines should read the
main columns; STV only falls back to a few snapshot values when a main column is empty.
Keywords:

- Architecture: size, diameter, radius, width, height, length, area, volume, material, weight,
  mass, thickness, depth, mark, level, offset, comment, assembly, type, fire, finish
- Structural: the same without type, fire, finish
- MEP: size, diameter, radius, width, height, length, area, volume, material, weight, mass,
  thickness, insulation, lining, flow, airflow, pressure, capacity, power, voltage, current, load

## `<model>_Room_Boundaries.csv` (18 columns, written by Architecture TakeOff)

One row per boundary segment (finish-face boundaries) of every placed room with area > 0; a room
without boundaries gets one row with empty segment columns. Used by the schedule engine (takt
zones).

| Column | Unit | Content |
|---|---|---|
| `RoomId` | integer | room ElementId |
| `RoomNumber`, `RoomName` | text | room number and name |
| `Level` | text | room level |
| `Area (SF)`, `Volume (CF)` | SF, CF | room area and volume |
| `Room Location X/Y/Z (ft)` | ft | room location point (3 columns) |
| `Boundary Loop` | integer | index of the boundary loop (as returned by Revit) |
| `Segment Index` | integer | index of the segment in the loop |
| `Start X/Y/Z (ft)`, `End X/Y/Z (ft)` | ft | segment end points (6 columns) |
| `Boundary Element Id` | integer | wall/separation line that forms the segment |
