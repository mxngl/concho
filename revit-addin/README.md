# revit-addin

C# Revit add-in (`QTO.dll`) that exports model quantities to the CSV files the Concho engines
consume, and pushes planning results (4D build codes, prefab/Manufacton IDs) back into the model.

Originally developed by Ashmitha Jaysi Sivakumar in
[ashjs2003/IPD_Challenge](https://github.com/ashjs2003/IPD_Challenge) (commit `989a6b7`);
migrated in P1.4.

The C# code was copied unchanged from `IPD_Challenge/QTO` at that commit (P1.4). P4.1 made the
build portable (Revit API from NuGet, one build per Revit version) and replaced the output-folder
search with a config file + folder dialog.

## Files

| File | Purpose |
|---|---|
| `Concho.QTO.sln`, `QTO.csproj` | Solution and SDK-style project (`net8.0-windows`, x64, compiles `*.cs` in this folder); configurations `Debug/Release R25` and `Debug/Release R26` |
| `QTO.addin` | Revit manifest; registers the external commands below |
| `Structural_TakeOff.cs`, `Architecture_TakeOff.cs`, `MEP_TakeOff.cs` | Quantity takeoff commands (CSV export) |
| `SpatialElementData.cs`, `RoomSpatialData.cs` | Spatial data shared by the takeoffs: element location/bounding box, room assignment, room boundary export |
| `ExportSummary.cs` | Summary dialog after each takeoff: element count, % with Assembly Code, missing codes by category |
| `ExportPathHelper.cs` | Reads the export folder from `concho_addin.json` next to the DLL (folder dialog if missing) and builds the CSV file name |
| `Push_TaskName_To_Revit.cs` | Push 4D Build Code command |
| `Push_Manufacton_Parameters_To_Revit.cs`, `Push_Kit_To_Revit.cs`, `Push_Assembly_To_Revit.cs`, `CsvParameterPushHelper.cs` | Prefab parameter push commands and their shared CSV/parameter helper |

## Commands

Registered in `QTO.addin` (shown under Add-Ins → External Tools in Revit):

| Command (`.addin` text) | Class | What it does |
|---|---|---|
| Structural TakeOff | `QTO.Structural_TakeOff` | Exports floors, structural columns/framing/foundations/stiffeners/trusses, structural connections, rebar and structural parts to `<model>_Structural_Schedule.csv`. Floors that have parts are skipped (their parts are exported instead); parts are kept only if their original category is floor, structural, foundation or rebar. |
| Architecture TakeOff | `QTO.Architecture_TakeOff` | Exports walls, doors, windows, floors, roofs, ceilings, curtain panels/mullions, stairs, railings, generic models, casework, furniture, plumbing fixtures and architectural parts to `<model>_Architecture_TakeOff.csv` (ceilings with parts are replaced by their parts). Also writes the room boundaries to `<model>_Room_Boundaries.csv`. |
| MEP TakeOff | `QTO.MEP_TakeOff` | Exports ducts, pipes, cable trays, conduits (with fittings/accessories/flex), plumbing fixtures, mechanical/electrical equipment, electrical and lighting fixtures and sprinklers, including system and connector data, to `<model>_MEP_TakeOff.csv`. |
| Push 4D Build Code | `QTO.Push_TaskName_To_Revit` | Reads `element_id`, `build_code` from `src/Planning_engine/Fuzor_Mapper/outputs/Revit_4D_Build_Code_Map.csv` and writes them into the `4D_Build_Code` text parameter. |
| Push Manufacton Parameters | `QTO.Push_Manufacton_Parameters_To_Revit` | Reads `src/Planning_engine/Prefab_BIM_Mapper/outputs/Revit_Assembly_Id_Map.csv` (`assembly_id`, `catalog_id`) and `Revit_Kit_Parameter_Map.csv` (`kit_id`, `order_id`, `item_name`) and writes them into `Prefab_Assembly_ID`, `Prefab_Catalog_ID`, `Prefab_Kit_ID`, `Prefab_order_ID`, `Prefab_Item_Name`. |

Also in the source, but **not registered in `QTO.addin`** (so not visible in Revit as shipped):

| Class | What it does |
|---|---|
| `QTO.Push_Kit_To_Revit` | Push Kit: writes `kit_id` from `Revit_Kit_Parameter_Map.csv` into `Prefab_Kit_ID` (subset of Push Manufacton Parameters). |
| `QTO.Push_Assembly_To_Revit` | Push Assembly: writes `assembly_id` from `Revit_Assembly_Id_Map.csv` into `Prefab_Assembly_ID` (subset of Push Manufacton Parameters). |

After each takeoff a summary dialog shows the element count, the share of elements with an
`Assembly Code`, and the elements without one grouped by category (top 10 + "…and N more").

The **spatial data export** is not a separate command: every takeoff adds location, bounding box
and room columns per element (`SpatialElementData`, `RoomAssignmentData`), and Architecture
TakeOff writes the room boundary CSV (`RoomBoundaryExporter`).

All push commands match elements by `element_id` (Revit ElementId), only write existing, editable
text parameters, skip elements with conflicting values in the CSV, and show a summary dialog.

## Build

Requires only the .NET 8 SDK; Revit does **not** need to be installed. The Revit API comes from
the [Nice3point.Revit.Api](https://github.com/Nice3point/RevitApi) reference packages
(`Nice3point.Revit.Api.RevitAPI` / `RevitAPIUI`, pinned per Revit year in `QTO.csproj`), which are
compile-time only and not copied to the output.

```
dotnet build Concho.QTO.sln -c "Release R25"   # Revit 2025 -> bin/Release R25/QTO.dll
dotnet build Concho.QTO.sln -c "Release R26"   # Revit 2026 -> bin/Release R26/QTO.dll
```

Both target `net8.0-windows` (Revit 2025 and 2026 run on .NET 8). `EnableWindowsTargeting` is set,
so the build also runs on Linux/macOS for checks. The same `QTO.addin` works for both versions.

**Revit 2024 and older (`net48`) are not built yet.** Open question: it depends on which Revit
version the 2027 teams get (roadmap D8/D2). Adding it means a `net48` target with the
`2024.*` reference packages and checking the code for .NET Framework gaps (e.g. `TryAdd`, the
`OpenFolderDialog` used for the export folder, which needs .NET 8 WPF).

## Installation

Copy `QTO.addin` and the `QTO.dll` built for your Revit version into the same folder, e.g.
`%AppData%\Autodesk\Revit\Addins\2026\` (Revit resolves the relative `<Assembly>` path against
the `.addin` file's folder).

## Export folder (`concho_addin.json`)

The takeoff commands write to the folder set in `concho_addin.json` next to `QTO.dll`:

```json
{
  "export_folder": "%USERPROFILE%\\Documents\\Concho\\exports"
}
```

If the file is missing, has no `export_folder`, or the folder doesn't exist, a folder dialog opens
on the first export and the choice is saved to that file. Cancelling the dialog cancels the export.
A relative path is resolved against the DLL's folder; environment variables (`%USERPROFILE%`) are
expanded. To change the folder, edit or delete the file.

## Current limitations

- **Push commands expect the old repo layout:** they search upward from the DLL for
  `src/Planning_engine/` (IPD_Challenge layout) and read files under `Fuzor_Mapper/outputs/` and
  `Prefab_BIM_Mapper/outputs/`. That layout doesn't exist in this repo; the schedule engines move
  to `engines/schedule/` in P1.7, and the push commands become optional adapters in P3B.6.
- Target shared parameters (`4D_Build_Code`, `Prefab_*`) must already exist in the model as
  editable text parameters.

Release zips per Revit version (P4.2): `.github/workflows/revit-addin-release.yml`, installer
`install/install.ps1` + `install/INSTALL.md`.

## CSV export columns

All files are UTF-8, comma-separated, one row per element, with standard CSV quoting. Parameter
values (`Length`, `Area`, `Volume`, ...) are Revit's display strings (`AsValueString`, i.e. project
units) taken from the instance and, if empty, the type; columns with `(ft)`, `(SF)`, `(CF)`, `(in)`
or `(deg)` are computed numbers in those units (invariant culture, up to 3 decimals). File names
are prefixed with the model file name (`<model>_...csv`). The full contract (unit, source
parameter, required/optional per column, Assembly Codes) is in
[`docs/model-requirements.md`](../docs/model-requirements.md).

### `<model>_Structural_Schedule.csv` and `<model>_Architecture_TakeOff.csv` (56 columns, same header)

`ElementId`, `Category`, `Family`, `Type`, `Original Category`, `Original Family`, `Original Type`,
`Level`, `Mark`, `Assembly Code`, `Assembly Description`, `Length`, `Width`, `Depth`, `Height`,
`Area`, `Volume`, `Weight`, `Unit Weight`, `Material`, `Type Comments`, `Base Level`, `Top Level`,
`Base Offset`, `Top Offset`, *spatial columns*, *room columns*, `Comments`, `Parameter Snapshot`

`Original Category/Family/Type` are filled for Revit parts only (the element the part was cut from).

### `<model>_MEP_TakeOff.csv` (70 columns)

`ElementId`, `Category`, `Family`, `Type`, `Level`, `Mark`, `System Name`, `System Type`,
`Service Type`, `Classification`, `Size`, `Diameter`, `Width`, `Height`, `Length`, `Area`,
`Volume`, `Material`, `Weight`, `Unit Weight`, `Insulation Thickness`, `Lining Thickness`,
`Airflow`, `Flow`, `Pressure Drop`, `Cooling Capacity`, `Heating Capacity`, `Power`, `Voltage`,
`Current`, `Apparent Load`, `Connected Load`, `Connector Count`, `Connector Flow`,
`Connector Demand`, `Connector Max Diameter (in)`, `Connector Max Width (in)`,
`Connector Max Height (in)`, *spatial columns*, *room columns*, `Comments`, `Parameter Snapshot`,
`Assembly Code`

`Assembly Code` was added in P4.3 as the **last** column, so readers that use column positions
keep working (the STV importer reads by column name and gives identical results).

### Shared column groups

- *Spatial columns* (20, `SpatialElementData`): `Location Type` (`Point`, `Curve` or
  `BoundingBox`), `Position X/Y/Z (ft)` (point, curve midpoint or bounding-box center),
  `Start X/Y/Z (ft)`, `End X/Y/Z (ft)` (curves only), `Rotation (deg)` (points only),
  `Bounding Box Min X/Y/Z (ft)`, `Bounding Box Max X/Y/Z (ft)`, `Bounding Box Center X/Y/Z (ft)`.
- *Room columns* (9, `RoomAssignmentData`): `Room Id`, `Room Number`, `Room Name`, `Room Level`,
  `Room Area (SF)`, `Room Volume (CF)`, `Room Location X/Y/Z (ft)`. The room is the family
  instance's room (or to/from room), else the room at the element's location point, curve
  midpoint or bounding-box center.
- `Parameter Snapshot`: `name=value` pairs joined by ` | `, sorted by name, from instance and type
  parameters whose name contains a keyword (per export: size, diameter, width, height, length,
  area, volume, material, thickness, ...; MEP adds flow, pressure, capacity, power, voltage, ...).

### `<model>_Room_Boundaries.csv` (18 columns, written by Architecture TakeOff)

`RoomId`, `RoomNumber`, `RoomName`, `Level`, `Area (SF)`, `Volume (CF)`, `Room Location X (ft)`,
`Room Location Y (ft)`, `Room Location Z (ft)`, `Boundary Loop`, `Segment Index`, `Start X (ft)`,
`Start Y (ft)`, `Start Z (ft)`, `End X (ft)`, `End Y (ft)`, `End Z (ft)`, `Boundary Element Id`

One row per boundary segment (finish-face boundaries) of every placed room with area > 0; a room
without boundaries gets a single row with empty segment columns.
