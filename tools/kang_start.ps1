# kang_start.ps1 - minimal manual launcher for daily use.
#
# NOT the real D016 run model ("core starts at login, lives in the
# tray") - that mechanism (single packaged installer, auto-start,
# ADR-008's single-instance enforcement wired to the core side) is still
# unbuilt. This is a stopgap: it starts the Python Core against the
# real, persistent %KANG_HOME%, waits for the session handshake file the
# Core writes (API-003), then launches the already-built Tauri shell
# (ui/shell/target/debug/kang-shell.exe), which reads that same file
# (ui/shell/src/main.rs::get_session). Manual every time, no autostart,
# no singleton enforcement beyond what already exists today (ADR-008 is
# why there isn't more).
#
# Usage: powershell -File tools/kang_start.ps1
# Stop:  the script prints the Core's PID; Stop-Process -Id <pid> when
#        done (quitting KANG from the tray only closes the shell, not
#        the Core - they are separate processes; the Core keeps running
#        until stopped explicitly or the machine restarts).

$ErrorActionPreference = "Stop"

if (-not $env:KANG_HOME) {
    Write-Error "KANG_HOME is not set. Set it as a permanent User environment variable first (see the 2026-08-08 session handoff)."
    exit 1
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$shellExe = Join-Path $repoRoot "ui\shell\target\debug\kang-shell.exe"

if (-not (Test-Path $shellExe)) {
    Write-Error "kang-shell.exe not found at $shellExe. Build it first: cd ui/shell; cargo build"
    exit 1
}

Write-Host "Starting KANG Core against $env:KANG_HOME ..."
$core = Start-Process -FilePath python `
    -ArgumentList "-m", "kang.kernel.runtime.composition", "$env:KANG_HOME" `
    -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru

$sessionFile = Join-Path $env:KANG_HOME "session.json"
# The Core always rewrites this file at startup, so a stale one from a
# previous run can't be mistaken for a fresh handshake as long as we
# wait for its write time to move past our own start time.
$startedAt = Get-Date
$deadline = $startedAt.AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $sessionFile) {
        if ((Get-Item $sessionFile).LastWriteTime -ge $startedAt) { break }
    }
    Start-Sleep -Milliseconds 200
}

if ((-not (Test-Path $sessionFile)) -or ((Get-Item $sessionFile).LastWriteTime -lt $startedAt)) {
    Write-Error "Core did not write a fresh session.json within 15s. Check it started correctly (PID $($core.Id))."
    exit 1
}

Write-Host "Core is up (PID $($core.Id)). Launching the shell..."
Start-Process -FilePath $shellExe
Write-Host ""
Write-Host "KANG is running in the tray - click the tray icon, then 'Show KANG'."
Write-Host "Core PID: $($core.Id). Stop it when done: Stop-Process -Id $($core.Id)"
