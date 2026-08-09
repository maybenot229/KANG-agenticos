# kang_unregister_autostart.ps1 - removes the Startup-folder shortcut
# kang_register_autostart.ps1 created (ADR-017). Safe to run even if
# nothing is registered.

$ErrorActionPreference = "Stop"

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "KANG.lnk"

if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
    Write-Host "Removed: $shortcutPath"
} else {
    Write-Host "No KANG autostart shortcut found at $shortcutPath - nothing to do."
}
