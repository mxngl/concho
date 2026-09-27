# Concho QTO Revit add-in: installation

This zip is built for **one Revit version** (see the zip name, e.g. `Revit2026`). Use the zip that
matches your Revit.

Contents: `QTO.dll`, `QTO.addin`, `install.cmd`, `install.ps1`, `INSTALL.md`.

## Install

1. Close Revit.
2. Unzip the whole zip into a folder.
3. **Double-click `install.cmd`.**
4. Windows shows **"Open File – Security Warning"** because the file comes from the internet.
   Click **Run** (German Windows: **Ausführen**). (If a blue "Windows protected your PC" window
   appears instead, click **More info** (Weitere Informationen) → **Run anyway** (Trotzdem
   ausführen).)

   The installer copies `QTO.dll` and `QTO.addin` to
   `%AppData%\Autodesk\Revit\Addins\<version>\` and asks before overwriting existing files.
   The window stays open until you press Enter, also after an error, so you can read the result.

   **Fallback** (if double-clicking doesn't work): open a PowerShell window in the folder (in
   Explorer: click the address bar, type `powershell`, press Enter) and run

   ```
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```

   `-ExecutionPolicy Bypass` only applies to this one run; Windows blocks unsigned downloaded
   scripts otherwise. `install.cmd` runs the same command. Options: `-Force` overwrites
   without asking, `-RevitVersion 2025` installs for another version, `-NoPause` skips the
   final Enter (for scripted installs); with `install.cmd` they go after it, e.g.
   `install.cmd -Force`.

   Don't use right-click → **Run with PowerShell** on `install.ps1`: for a downloaded script
   Windows' execution policy stops it before it starts, without any message.
5. Start Revit. Revit shows a **security warning for an unsigned add-in** ("The publisher of
   this add-in could not be verified"). Choose **Always Load**; Revit then remembers the choice
   for this add-in.
   Why the warning: Revit only shows a verified publisher for add-ins signed with a
   code-signing certificate, which the Concho project doesn't have. The add-in's vendor in
   `QTO.addin` is "Concho – Maximilian Nagel & Ashmitha Jaysi Sivakumar, Stanford AEC Global
   Teamwork", but that text is not a verified signature.
6. The commands are under **Add-Ins → External Tools**.

Manual install: copy `QTO.dll` and `QTO.addin` into
`%AppData%\Autodesk\Revit\Addins\<version>\` yourself (right-click `QTO.dll` → Properties →
**Unblock** if Windows marked it as downloaded).

## First export

The first takeoff asks for the export folder. The choice is saved to `concho_addin.json` next to
`QTO.dll`; edit or delete that file to change the folder. After each export a summary shows the
element count, how many elements have an Assembly Code and which quantities were not found.
The CSV uses English category names in any Revit language (the Revit name is in the last
column, `Category (local)`).

Model requirements (columns, Assembly Codes): `docs/model-requirements.md` in the Concho repo.

## Uninstall

Delete `QTO.dll`, `QTO.addin` and `concho_addin.json` from
`%AppData%\Autodesk\Revit\Addins\<version>\`.
