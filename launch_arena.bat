@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Tank Trouble AI Arena Server
echo Starting Tank Trouble (GitHub + Python AI Arena)...
echo Browser will open automatically once ready. Keep this window open while playing.
echo.
set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if exist "%PY_EXE%" (
    "%PY_EXE%" server.py --open
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        python server.py --open
    ) else (
        py -3 server.py --open
    )
)
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start server. Check Python / Flask.
    pause
)
