@echo off
rem Concho QTO Revit add-in installer: runs install.ps1 without changing the execution policy.
rem Double-click this file (Windows never runs .ps1 files on double-click).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
