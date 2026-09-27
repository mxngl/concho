# Model requirements and export contract (P4.3)

What a team's Revit model must contain so the Concho engines can use its exports, and every
column of the CSV files the Revit add-in (`revit-addin/`, `QTO.dll`) writes. Installation and
build of the add-in: [`revit-addin/README.md`](../revit-addin/README.md).

## Checklist for teams

1. **Assembly Code on every element type** (Uniformat, level 3, e.g. `B2010`), from week 1. It is
   the key the TVD engine prices by; elements without it are reported as *unmapped* and cost $0.
   See [Assembly Codes](#assembly-codes).
2. **Imperial project units** (Manage → Project Units): length in feet (`ft-in` or decimal
   feet), area in SF, volume in CF. The engines read `Length`, `Area` and `Volume` from Revit's
   display strings and take the first number; a metric model is read without an error but with
   wrong quantities.
3. Elements on **levels** and in **rooms** (the schedule engine groups by level and room).
4. **Materials** assigned to the element types (STV maps embodied carbon by category, family
   and material).
5. Elements that must not be priced: put `DNC` (do not count) in `Mark` or `Comments` (or the
   family/type name). The TVD engine skips them. `Furniture` is never priced (only counted for
   `count_codes` rules).
6. Run the three takeoffs (Add-Ins → External Tools → Architecture / Structural / MEP TakeOff)
   and check the **summary dialog**: it shows the share of elements with an Assembly Code and
   the elements without one by category. Fix the top categories first.

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

The add-in reads `Assembly Code` from the element (instance parameter) and, if empty, from its
type, by parameter **name** (English Revit UI; a localized Revit has a different parameter name
and would export empty codes, not tested).

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
- **Parameter values** (unit "display") are Revit's display strings (`AsValueString`) in the
  project units, e.g. `136' - 0"`, `6590 SF`, `42.75 CF`, taken from the first listed parameter
  that has a value on the instance and, if empty, on the type. Yes/No parameters are `True` /
  `False`; element references (e.g. `Level`) are the element name.
- **Computed numbers** (columns with `(ft)`, `(SF)`, `(CF)`, `(in)`, `(deg)`) are plain decimals
  in those units, invariant culture (`.` decimal separator), up to 3 decimals, computed from
  Revit's internal units (feet).

Engines: **TVD** reads the Architecture and Structural exports (`--arch`, `--struct`), **STV**
all three, **Schedule** the combined element context built from all three. "Used by" lists the
engines that read the column.

## `<model>_Architecture_TakeOff.csv` and `<model>_Structural_Schedule.csv` (56 columns)

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
| 2 | `Category` | text | category name | required (always set) | TVD, STV, Schedule |
| 3 | `Family` | text | family name (family instances only; empty for system families) | recommended | TVD, STV, Schedule |
| 4 | `Type` | text | type name | recommended | TVD, STV, Schedule |
| 5 | `Original Category` | text | parts only: `Original Category` (Architecture also `Original Category Id`) | optional | Schedule |
| 6 | `Original Family` | text | parts only: `Original Family` / `Original Family Name` | optional | Schedule |
| 7 | `Original Type` | text | parts only: `Original Type` / `Original Type Name` | optional | Schedule |
| 8 | `Level` | text | `Level` parameter, else the element's level | recommended | TVD (unmapped list), Schedule |
| 9 | `Mark` | text | `Mark` | optional (`DNC` marker) | TVD, Schedule |
| 10 | `Assembly Code` | Uniformat code | `Assembly Code` (instance, else type) | **required** | TVD, STV, Schedule |
| 11 | `Assembly Description` | text | `Assembly Description` | recommended | STV, Schedule |
| 12 | `Length` | display (ft) | `Length`, `Cut Length`, `Span` | required for LF-priced codes | TVD, STV, Schedule |
| 13 | `Width` | display (ft) | `Width`, `Actual Width` | optional | STV, Schedule |
| 14 | `Depth` | display (ft) | `Depth`, `Thickness`, `Structural Depth` | optional | Schedule |
| 15 | `Height` | display (ft) | `Height`, `Thickness` | optional | STV, Schedule |
| 16 | `Area` | display (SF) | `Area`, `Host Area Computed`, `Computed Area` | required for SF-priced codes | TVD, STV, Schedule |
| 17 | `Volume` | display (CF) | `Volume`, `Host Volume Computed` | required for CY/CF-priced codes | TVD, STV, Schedule |
| 18 | `Weight` | display | `Weight`, `Calculated Weight`, `Mass` | optional | – |
| 19 | `Unit Weight` | display | `Material: Unit weight`, `Unit Weight`, `Weight per Unit Length`, `Mass per Unit Length` | optional | – |
| 20 | `Material` | text | names of the element's materials, `; `-separated | recommended | TVD (unmapped list), STV, Schedule |
| 21 | `Type Comments` | text | type parameter `Type Comments` | optional | – |
| 22 | `Base Level` | text | `Base Level` | optional | Schedule |
| 23 | `Top Level` | text | `Top Level` | optional | Schedule |
| 24 | `Base Offset` | display (ft) | `Base Offset` | optional | – |
| 25 | `Top Offset` | display (ft) | `Top Offset` | optional | – |
| 26–45 | *spatial columns* | see below | element location / bounding box | recommended | Schedule |
| 46–54 | *room columns* | see below | room of the element | recommended | Schedule |
| 55 | `Comments` | text | `Comments` | optional (`DNC` marker) | TVD |
| 56 | `Parameter Snapshot` | text | see below | optional | STV, Schedule |

Both exports use the same parameter lookups, except `Base Level` / `Top Level`: Architecture
reads them from the instance, else the type; Structural only from the instance.

## `<model>_MEP_TakeOff.csv` (70 columns)

Ducts, duct fittings/accessories/terminals, flex ducts, pipes, pipe fittings/accessories, flex
pipes, cable trays and fittings, conduits and fittings, plumbing fixtures, mechanical and
electrical equipment, electrical and lighting fixtures, sprinklers.

| # | Column | Unit | Source (Revit) | Required | Used by |
|---|---|---|---|---|---|
| 1 | `ElementId` | integer | `Element.Id` | required (always set) | STV, Schedule |
| 2 | `Category` | text | category name | required (always set) | STV, Schedule |
| 3 | `Family` | text | family name (empty for system families: ducts, pipes, …) | recommended | STV, Schedule |
| 4 | `Type` | text | type name | recommended | STV, Schedule |
| 5 | `Level` | text | `Level` parameter, else the element's level | recommended | Schedule |
| 6 | `Mark` | text | `Mark` | optional | Schedule |
| 7 | `System Name` | text | `System Name`, `System` | optional | Schedule |
| 8 | `System Type` | text | `System Type` | recommended | STV, Schedule |
| 9 | `Service Type` | text | `Service Type` | optional | Schedule |
| 10 | `Classification` | text | `Classification`, `Flow Classification`, `Part Type` | optional | Schedule |
| 11 | `Size` | display | `Size`, `Nominal Size`, `Overall Size` | recommended | STV, Schedule |
| 12 | `Diameter` | display (in) | `Diameter`, `Nominal Diameter`, `Duct Diameter` | recommended | STV |
| 13 | `Width` | display (in) | `Width`, `Nominal Width`, `Duct Width` | recommended | STV, Schedule |
| 14 | `Height` | display (in) | `Height`, `Nominal Height`, `Duct Height` | recommended | STV, Schedule |
| 15 | `Length` | display (ft) | `Length`, `Overall Size` | required for ducts/pipes/trays/conduits | STV, Schedule |
| 16 | `Area` | display (SF) | `Area`, `Surface Area` | recommended | STV, Schedule |
| 17 | `Volume` | display (CF) | `Volume` | optional | STV, Schedule |
| 18 | `Material` | text | names of the element's materials, `; `-separated | recommended | STV, Schedule |
| 19 | `Weight` | display | `Weight`, `Calculated Weight`, `Mass` | optional | STV |
| 20 | `Unit Weight` | display | `Unit Weight`, `Weight per Unit Length`, `Mass per Unit Length` | optional | STV |
| 21 | `Insulation Thickness` | display (in) | `Insulation Thickness` | optional | – |
| 22 | `Lining Thickness` | display (in) | `Lining Thickness` | optional | – |
| 23 | `Airflow` | display | `Air Flow`, `Airflow`, `Calculated Supply/Exhaust/Return Air Flow`, `Flow` | optional | STV |
| 24 | `Flow` | display | `Flow`, `Flow Rate`, `Actual Flow`, `Demand Flow` | optional | STV |
| 25 | `Pressure Drop` | display | `Pressure Drop`, `Calculated Pressure Drop`, `Fitting Pressure Drop`, `Loss Method` | optional | – |
| 26 | `Cooling Capacity` | display | `Cooling Capacity`, `Total Cooling Capacity`, `Sensible Cooling Capacity` | optional | – |
| 27 | `Heating Capacity` | display | `Heating Capacity`, `Heating Load`, `Total Heating Capacity` | optional | – |
| 28 | `Power` | display | `Power`, `Power Factor`, `Motor Power`, `Input Power` | optional | – |
| 29 | `Voltage` | display | `Voltage` | optional | – |
| 30 | `Current` | display | `Current`, `Current Rating` | optional | – |
| 31 | `Apparent Load` | display | `Apparent Load` | optional | – |
| 32 | `Connected Load` | display | `Connected Load`, `Load Name` | optional | – |
| 33 | `Connector Count` | integer | number of MEP connectors | optional | – |
| 34 | `Connector Flow` | number (internal units) | sum of connector `Flow` | optional | STV |
| 35 | `Connector Demand` | number (internal units) | sum of connector `Demand` | optional | – |
| 36 | `Connector Max Diameter (in)` | in | largest connector radius × 2 | optional | – |
| 37 | `Connector Max Width (in)` | in | largest connector width | optional | – |
| 38 | `Connector Max Height (in)` | in | largest connector height | optional | – |
| 39–58 | *spatial columns* | see below | element location / bounding box | recommended | Schedule |
| 59–67 | *room columns* | see below | room of the element | recommended | Schedule |
| 68 | `Comments` | text | `Comments` | optional | – |
| 69 | `Parameter Snapshot` | text | see below | optional | STV, Schedule |
| 70 | `Assembly Code` | Uniformat code | `Assembly Code` (instance, else type) | **required** (new in P4.3) | – (not read by an engine yet) |

Connector columns 34–35 are empty when the sum is 0; 36–38 likewise. `Assembly Code` is the last
column so readers that use column positions keep working; no engine reads it from the MEP export
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
name contains one of the export's keywords (instance value wins; empty values skipped). Keywords:

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
