' kang_start_hidden.vbs - runs kang_start.ps1 with no visible window (ADR-017).
'
' Needed because "powershell.exe -WindowStyle Hidden" alone still flashes a
' console window briefly on some Windows builds; WScript.Shell.Run with
' windowStyle=0 is the standard, dependency-free way to truly hide it.
' Used by the Startup-folder shortcut kang_register_autostart.ps1 creates -
' not meant to be run directly, though double-clicking it works too.

Dim objShell, scriptDir, ps1Path
Set objShell = CreateObject("WScript.Shell")
scriptDir = Left(WScript.ScriptFullName, Len(WScript.ScriptFullName) - Len(WScript.ScriptName))
ps1Path = scriptDir & "kang_start.ps1"
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1Path & """", 0, False
