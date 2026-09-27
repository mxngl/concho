<#
.SYNOPSIS
  Installs the Concho QTO Revit add-in for the current user.

.DESCRIPTION
  Copies QTO.dll and QTO.addin from this folder to
  %AppData%\Autodesk\Revit\Addins\<RevitVersion>\ and asks before overwriting existing files.
  An existing concho_addin.json (export folder) is left untouched.

.PARAMETER RevitVersion
  Revit year, e.g. 2025 or 2026. The release zips set the default to the version they were
  built for.

.PARAMETER Force
  Overwrite existing files without asking.

.PARAMETER NoPause
  Don't wait for Enter at the end (for scripted installs). By default the window stays open,
  also after an error, so a double-click shows the result.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1
#>
param(
    [string]$RevitVersion = '__REVIT_VERSION__',
    [switch]$Force,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
$exitCode = 0

try {
    if ($RevitVersion -notmatch '^\d{4}$') {
        $RevitVersion = Read-Host 'Revit version (e.g. 2026)'
        if ($RevitVersion -notmatch '^\d{4}$') {
            Write-Error "Not a Revit version: '$RevitVersion'"
        }
    }

    $files = @('QTO.dll', 'QTO.addin')
    foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $file))) {
            Write-Error "$file not found next to install.ps1 ($PSScriptRoot). Unzip the whole release zip first."
        }
    }

    if (Get-Process -Name 'Revit' -ErrorAction SilentlyContinue) {
        Write-Warning 'Revit is running. Close Revit first, otherwise QTO.dll cannot be replaced.'
    }

    $target = Join-Path $env:APPDATA "Autodesk\Revit\Addins\$RevitVersion"
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    Write-Host "Installing the Concho QTO add-in for Revit $RevitVersion to $target"

    $installed = 0
    foreach ($file in $files) {
        $source = Join-Path $PSScriptRoot $file
        $destination = Join-Path $target $file

        if ((Test-Path -LiteralPath $destination) -and -not $Force) {
            $answer = Read-Host "$file already exists in $target. Overwrite? [y/N]"
            if ($answer -notmatch '^(y|yes|j|ja)$') {
                Write-Host "  skipped $file"
                continue
            }
        }

        Copy-Item -LiteralPath $source -Destination $destination -Force
        # Files from a downloaded zip carry the internet zone mark; Revit won't load a blocked DLL.
        # ($IsWindows is $null in Windows PowerShell 5.1, $false only in PowerShell 7 on Linux/macOS.)
        if ($IsWindows -ne $false) {
            Unblock-File -LiteralPath $destination
        }
        Write-Host "  copied $file"
        $installed++
    }

    Write-Host ''
    if ($installed -eq $files.Count) {
        Write-Host 'Done. Start Revit and find the commands under Add-Ins > External Tools.'
        Write-Host 'If Revit warns about an unsigned add-in (publisher unknown), choose "Always Load".'
        Write-Host 'The first export asks for the export folder (saved to concho_addin.json next to QTO.dll).'
    } else {
        Write-Host "Done ($installed of $($files.Count) files copied)."
    }
}
catch {
    $exitCode = 1
    Write-Host ''
    Write-Host "Installation failed: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if (-not $NoPause) {
        Write-Host ''
        Read-Host 'Press Enter to close' | Out-Null
    }
}

exit $exitCode
