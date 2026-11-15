@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Tank Trouble AI Arena Server

set "PY_CMD="
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    set "PY_CMD="%LOCALAPPDATA%\Programs\Python\Python314\python.exe""
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PY_CMD=python"
    ) else (
        where py >nul 2>nul
        if not errorlevel 1 (
            set "PY_CMD=py -3"
        )
    )
)

if not defined PY_CMD (
    echo [ERROR] Python 3.10+ not found on this PC.
    echo Please download Python from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

%PY_CMD% -c "import flask" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing Flask dependency for the first run...
    %PY_CMD% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [INFO] Retrying with Tsinghua PyPI mirror...
        %PY_CMD% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    )
)

echo Starting Tank Trouble AI Code Arena...
echo Browser will open automatically once ready. Keep this window open while playing.
echo.
%PY_CMD% server.py --open
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start server. Check Python / Flask output above.
    pause
)
