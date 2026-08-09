# kang_register_autostart.ps1 - registers KANG to start at Windows login
# (ADR-017, activating 03_ROADMAP §8's RESERVED "start-at-login" row).
#
# Creates one shortcut in the current user's Startup folder
# (shell:startup) pointing at kang_start_hidden.vbs, which runs
# kang_start.ps1 with no visible window. Idempotent: re-running overwrites
# the same shortcut rather than creating duplicates.
#
# This is a per-user registration on Kang's own machine, run by hand once
# - not part of any installer (the real D016 packaged install is a
# separate, larger, unbuilt decision). To undo:
#   powershell -File tools/kang_unregister_autostart.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$vbsPath = Join-Path $repoRoot "tools\kang_start_hidden.vbs"

if (-not (Test-Path $vbsPath)) {
    Write-Error "kang_start_hidden.vbs not found at $vbsPath."
    exit 1
}

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "KANG.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"$vbsPath`""
$shortcut.WorkingDirectory = $repoRoot
$shortcut.Description = "Start KANG (Core + shell) at login"
$shortcut.Save()

Write-Host "Registered: $shortcutPath"
Write-Host "KANG will start automatically at your next login."
Write-Host "To undo: powershell -File tools/kang_unregister_autostart.ps1"
