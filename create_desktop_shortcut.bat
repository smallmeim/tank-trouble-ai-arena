@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = [Environment]::GetFolderPath('Desktop'); $ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut((Join-Path $d 'Tank Trouble AI Arena.lnk')); $sc.TargetPath = (Join-Path '%~dp0' 'launch_arena.bat'); $sc.WorkingDirectory = '%~dp0'.TrimEnd('\'); $sc.IconLocation = (Join-Path '%~dp0' 'assets\icon.ico') + ',0'; $sc.WindowStyle = 1; $sc.Description = 'Tank Trouble AI Code Arena'; $sc.Save()"
if errorlevel 1 (
    echo [ERROR] Failed to create Desktop shortcut.
) else (
    echo [OK] Desktop shortcut created: Tank Trouble AI Arena.lnk
)
pause
