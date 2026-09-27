# Concho QTO Revit add-in: installation

This zip is built for **one Revit version** (see the zip name, e.g. `Revit2026`). Use the zip that
matches your Revit.

Contents: `QTO.dll`, `QTO.addin`, `install.ps1`, `INSTALL.md`.

## Install

1. Close Revit.
2. Unzip the whole zip into a folder.
3. In that folder, right-click `install.ps1` → **Run with PowerShell**, or in a PowerShell window:

   ```
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```

   The script copies `QTO.dll` and `QTO.addin` to
   `%AppData%\Autodesk\Revit\Addins\<version>\` and asks before overwriting existing files
   (`-Force` overwrites without asking; `-RevitVersion 2025` installs for another version).
4. Start Revit. If Revit asks whether to load the add-in, choose **Always Load**.
   The commands are under **Add-Ins → External Tools**.

Manual install: copy `QTO.dll` and `QTO.addin` into
`%AppData%\Autodesk\Revit\Addins\<version>\` yourself (right-click `QTO.dll` → Properties →
**Unblock** if Windows marked it as downloaded).

## First export

The first takeoff asks for the export folder. The choice is saved to `concho_addin.json` next to
`QTO.dll`; edit or delete that file to change the folder. After each export a summary shows the
element count and how many elements have an Assembly Code.

Model requirements (columns, Assembly Codes): `docs/model-requirements.md` in the Concho repo.

## Uninstall

Delete `QTO.dll`, `QTO.addin` and `concho_addin.json` from
`%AppData%\Autodesk\Revit\Addins\<version>\`.
